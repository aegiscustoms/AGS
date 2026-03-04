import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. 초기 데이터베이스 및 보안 설정 ---
def init_db():
    # 회원 관리 DB
    conn_auth = sqlite3.connect("users.db")
    # 관리자 계정 ID: aegis01210 반영
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, phone TEXT, email TEXT,
                biz_name TEXT, biz_no TEXT, biz_rep TEXT, biz_type TEXT, biz_item TEXT,
                biz_addr TEXT, tax_email TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    # 최초 관리자 계정 생성
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

    # 관세 마스터 DB
    conn_data = sqlite3.connect("customs_master.db")
    conn_data.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS requirements (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, description TEXT, rate TEXT)")
    conn_data.commit()
    conn_data.close()

init_db()

# --- 2. 제미나이 AI API 설정 ---
api_key = st.secrets.get("GEMINI_KEY")
if not api_key:
    st.error("❌ API 키가 설정되지 않았습니다. Streamlit Cloud의 Secrets 메뉴에 'GEMINI_KEY'를 등록해주세요.")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- 3. 로그인 및 세션 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_id = ""
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    choice = st.sidebar.selectbox("접속 메뉴", ["로그인", "회원가입"])
    
    if choice == "로그인":
        st.title("🔐 AEGIS 서비스 로그인")
        l_id = st.text_input("아이디")
        l_pw = st.text_input("비밀번호", type="password")
        if st.button("로그인", use_container_width=True):
            conn = sqlite3.connect("users.db")
            res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                               (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
            conn.close()
            if res:
                if res[0] == 1:
                    st.session_state.logged_in = True
                    st.session_state.user_id = l_id
                    st.session_state.is_admin = bool(res[1])
                    st.rerun()
                else: st.error("관리자 승인 대기 중입니다. 승인 후 이용 가능합니다.")
            else: st.error("아이디 또는 비밀번호가 틀렸습니다.")
            
    else: # 회원가입 UI
        st.title("📝 서비스 이용 신청")
        with st.form("signup_form"):
            st.subheader("ㄱ) 회원 기본 정보")
            new_id = st.text_input("아이디 (중복확인)")
            new_pw = st.text_input("비밀번호", type="password")
            new_pw_chk = st.text_input("비밀번호 확인", type="password")
            new_name = st.text_input("성함")
            new_phone = st.text_input("전화번호")
            new_email = st.text_input("이메일")
            st.subheader("ㄴ) 사업자 정보")
            b_name = st.text_input("상호명")
            b_no = st.text_input("사업자등록번호")
            b_rep = st.text_input("대표자명")
            b_type = st.text_input("업태")
            b_item = st.text_input("업종")
            b_addr = st.text_input("사업장 주소")
            t_email = st.text_input("세금계산서 수신 메일")
            
            if st.form_submit_button("가입 신청하기"):
                if new_pw != new_pw_chk: st.error("비밀번호가 일치하지 않습니다.")
                else:
                    conn = sqlite3.connect("users.db")
                    try:
                        hpw = hashlib.sha256(new_pw.encode()).hexdigest()
                        conn.execute("INSERT INTO users (id, pw, name, phone, email, biz_name, biz_no, biz_rep, biz_type, biz_item, biz_addr, tax_email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (new_id, hpw, new_name, new_phone, new_email, b_name, b_no, b_rep, b_type, b_item, b_addr, t_email))
                        conn.commit()
                        st.success("신청 완료! 관리자 승인 후 안내드립니다.")
                    except: st.error("이미 존재하는 아이디입니다.")
                    conn.close()
    st.stop()

# --- 4. 메인 어플리케이션 UI (로그인 성공 시) ---
st.sidebar.success(f"✅ 접속 중: {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

# 탭 순서: HS검색, 통계부호, 세계 HS/세율, FTA정보, 화물통관진행정보, 세액계산기
tab_names = ["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"]
if st.session_state.is_admin: tab_names.append("⚙️ 관리자")
tabs = st.tabs(tab_names)

# [공통 함수] DB 상세 정보 출력
def display_hsk_details(hsk_code, probability=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM requirements WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    
    prob_suffix = f" ({probability})" if probability else ""
    if not master.empty:
        st.success(f"✅ [{code_clean}]{prob_suffix} {master['name_kr'].values[0]}")
        c1, c2 = st.columns(2)
        with c1: st.write("**적용 세율**"); st.table(rates)
        with c2: st.write("**수입 요건**"); st.table(reqs)

# --- [Tab 1] HS검색 ---
with tabs[0]:
    col1, col2 = st.columns([2, 1])
    with col1: u_input = st.text_input("물품 정보 입력 (품명, 용도, 재질 등)", key="hs_input")
    with col2: u_img = st.file_uploader("이미지 업로드", type=["jpg", "jpeg", "png"], key="hs_img")
    
    # 이미지 미리보기
    if u_img:
        st.image(Image.open(u_img), caption="📸 분석 대상 이미지", use_container_width=True)

    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("AI 관세사가 분석 중입니다..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다. 다음 규칙에 따라 HS코드를 제안하세요.
                    1. 품명 출력: 유저 입력('{u_input}')이 있으면 그 품명을 사용하고, 없으면 이미지를 분석해 '예상품명'을 제시하세요.
                    2. 확실한 경우(100%): HSK 10자리 코드를 제시하고 옆에 (100%)를 기재하세요.
                    3. 불확실한 경우: 6단위(소호) 기준으로 가장 적합한 순서대로 3순위까지 추천하고 각각의 확률을 %로 기재하세요.
                    4. 답변 마지막에 '추천결과: [코드] [확률]' 형식을 포함하세요.
                    """
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"유저 정보: {u_input}")
                    
                    response = model.generate_content(content)
                    st.markdown("### 📋 AI 분석 리포트")
                    st.write(response.text)
                    
                    # 100% 결과 시 DB 연동 상세 출력
                    lines = response.text.split('\n')
                    for line in lines:
                        if "100%" in line:
                            code_10 = re.findall(r'\d{10}', line)
                            if code_10: display_hsk_details(code_10[0], "100%")
                except Exception as e: st.error(f"분석 오류: {e}")

# --- [Tab 2] 통계부호 ---
with tabs[1]:
    s_q = st.text_input("", placeholder="검색할 부호 또는 명칭을 입력하세요", key="stat_input")
    if st.button("검색 실행"):
        conn = sqlite3.connect("customs_master.db")
        res = pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{s_q}%' OR description LIKE '%{s_q}%'", conn)
        conn.close()
        if not res.empty: st.table(res)
        else: st.warning("검색 결과가 없습니다.")

# --- [Tab 3] 세계 HS/세율 ---
with tabs[2]:
    st.header("🌎 세계 HS 및 실시간 세율 가이드")
    country = st.selectbox("조회 국가", ["미국", "EU", "베트남", "중국", "일본"])
    world_hs = st.text_input("현지 HS코드 입력")
    raw_info = st.text_area("해외 사이트 데이터 복사/붙여넣기")
    if st.button("해외 세율 정밀 분석"):
        with st.spinner("다국어 데이터 분석 중..."):
            res = model.generate_content(f"{country}의 HS {world_hs} 정보 분석: {raw_info}")
            st.markdown(res.text)

# --- [Tab 4, 5, 6] 준비 중 ---
with tabs[3]: st.info("📜 FTA 정보 RAW 데이터 수집 및 업데이트 중입니다.")
with tabs[4]: st.info("📦 화물통관진행정보 조회 기능을 준비 중입니다.")
with tabs[5]:
    st.header("🧮 세액 계산기")
    p_val = st.number_input("물품가격(원화기준)", value=1000000)
    r_val = st.number_input("관세율(%)", value=8.0)
    if st.button("세액 계산하기"):
        duty = p_val * (r_val/100)
        vat = (p_val + duty) * 0.1
        st.success(f"관세: {int(duty):,}원 | 부가세: {int(vat):,}원 | 합계: {int(duty+vat):,}원")

# --- [Tab 7] 관리자 전용 (aegis01210 전용) ---
if st.session_state.is_admin:
    with tabs[6]:
        st.header("⚙️ 운영 관리 (aegis01210 전용)")
        m = st.radio("관리 메뉴", ["회원 승인 관리", "사용자 삭제"], horizontal=True)
        conn = sqlite3.connect("users.db")
        if m == "회원 승인 관리":
            pending = pd.read_sql("SELECT id, name, biz_name FROM users WHERE is_approved=0", conn)
            st.table(pending)
            tid = st.text_input("승인할 ID 입력")
            if st.button("계정 승인"):
                conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (tid,))
                conn.commit(); st.success("승인 완료")
        elif m == "사용자 삭제":
            users = pd.read_sql("SELECT id, name FROM users", conn)
            st.table(users)
            did = st.text_input("삭제할 ID 입력")
            if st.button("영구 삭제"):
                conn.execute("DELETE FROM users WHERE id=?", (did,))
                conn.commit(); st.warning("삭제 완료")
        conn.close()

# --- 5. 하단 연락처 및 상담 채널 (이지스 관세사무소) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1:
    st.markdown("### 📞 상담 문의: 010-8859-0403")
    st.write("이지스 관세사무소 | 이종혁 관세사 (jhlee@aegiscustoms.com)")
with c2: st.link_button("📧 이메일 상담", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)