import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. DB 초기화 및 컬럼 자동 보정 ---
def init_db():
    # 보안/회원 DB
    conn_auth = sqlite3.connect("users.db")
    c = conn_auth.cursor()
    # 기본 테이블 생성
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, phone TEXT, email TEXT,
                biz_name TEXT, biz_no TEXT, biz_rep TEXT, biz_type TEXT, biz_item TEXT,
                biz_addr TEXT, tax_email TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    
    # [중요] 기존 DB에 누락된 컬럼이 있다면 자동 추가 (DatabaseError 방지)
    cursor = conn_auth.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in cursor.fetchall()]
    needed_columns = ['phone', 'email', 'biz_name', 'biz_no', 'biz_rep', 'biz_type', 'biz_item', 'biz_addr', 'tax_email']
    for col in needed_columns:
        if col not in columns:
            conn_auth.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
    
    # 관리자 계정 ID: aegis01210 반영
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

    # 관세 데이터 DB
    conn_data = sqlite3.connect("customs_master.db")
    conn_data.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS requirements (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, description TEXT, rate TEXT)")
    conn_data.commit()
    conn_data.close()

init_db()

# --- 2. API 설정 ---
api_key = st.secrets.get("GEMINI_KEY")
if not api_key:
    st.error("❌ API 키가 없습니다. Streamlit Cloud Secrets를 확인하세요.")
    st.stop()
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- 3. 세션 및 로그인 시스템 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    choice = st.sidebar.selectbox("메뉴", ["로그인", "회원가입"])
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
                else: st.error("관리자 승인 대기 중입니다.")
            else: st.error("아이디/비밀번호 불일치")
    else:
        st.title("📝 회원가입")
        with st.form("signup"):
            new_id = st.text_input("아이디")
            new_pw = st.text_input("비밀번호", type="password")
            new_name = st.text_input("성함")
            b_name = st.text_input("상호명")
            b_no = st.text_input("사업자번호")
            if st.form_submit_button("가입 신청"):
                conn = sqlite3.connect("users.db")
                try:
                    conn.execute("INSERT INTO users (id, pw, name, biz_name, biz_no) VALUES (?,?,?,?,?)",
                                 (new_id, hashlib.sha256(new_pw.encode()).hexdigest(), new_name, b_name, b_no))
                    conn.commit()
                    st.success("신청 완료! 승인을 기다려주세요.")
                except: st.error("중복된 아이디입니다.")
                conn.close()
    st.stop()

# --- 4. 메인 어플리케이션 ---
st.sidebar.write(f"✅ 접속: {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# DB 상세 정보 출력 함수
def display_hsk_details(hsk_code, probability=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM requirements WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]} {f'({probability})' if probability else ''}")
        c1, c2 = st.columns(2)
        with c1: st.table(rates)
        with c2: st.table(reqs)

# --- [Tab 1] HS검색 (정밀 교정 버전) ---
with tabs[0]:
    col1, col2 = st.columns([2, 1])
    with col1: 
        u_input = st.text_input("물품 정보 입력 (품명, 용도, 재질 등)", key="main_search_v2")
    with col2: 
        u_img = st.file_uploader("이미지 업로드", type=["jpg", "jpeg", "png"], key="main_img_v2")
    
    # 이미지 미리보기
    if u_img:
        st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)

    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("AI 관세사가 정밀 분석 중입니다..."):
                try:
                    # AI 프롬프트 구성 (품명 및 확률 로직 강화)
                    prompt = f"""당신은 전문 관세사입니다. 다음 규칙에 따라 HS코드를 제안하세요.

                    [출력 지침]
                    1. 품명: 유저가 입력한 '{u_input}'이 있으면 그대로 사용하고, 없으면 이미지를 분석해 '예상품명'을 제시하세요.
                    2. 확실한 경우(100%): HSK 10자리 코드를 제시하고 옆에 (100%)를 기재하세요.
                    3. 불확실한 경우: 6단위(소호) 기준으로 가장 적합한 순서대로 3순위까지 추천하고 각각의 확률을 %로 기재하세요. (예: 1순위 8517.13 (70%))
                    
                    반드시 마지막 줄에 '추천결과: [10자리코드] [확률]' 또는 '추천결과: [6자리코드] [확률]' 형식을 포함하세요.
                    """
                    
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"입력된 물품정보: {u_input}")
                    
                    response = model.generate_content(content)
                    
                    # 1. AI 분석 리포트 출력
                    st.markdown("### 📋 AI 분석 리포트")
                    st.write(response.text)
                    
                    # 2. 결과 파싱 및 DB 상세 정보 연결
                    st.divider()
                    lines = response.text.split('\n')
                    found_code = False

                    for line in lines:
                        # 100% 확정인 경우 10자리 추출
                        if "100%" in line:
                            codes = re.findall(r'\d{10}', line)
                            if codes:
                                display_hsk_details(codes[0], "100%")
                                found_code = True
                                break
                    
                    # 100%가 아닌 경우 6단위 가이드 강조
                    if not found_code:
                        st.info("💡 정확도가 100% 미만인 경우, 위 리포트의 6단위(소호) 추천 순위를 참고하여 상세 정보를 직접 조회해 주세요.")

                except Exception as e:
                    st.error(f"⚠️ 분석 오류 발생: {e}")
        else:
            st.warning("분석을 위해 정보를 입력하거나 이미지를 업로드해 주세요.")

# [Tab 2] 통계부호
with tabs[1]:
    s_q = st.text_input("부호/명칭 검색")
    if st.button("검색"):
        conn = sqlite3.connect("customs_master.db")
        st.table(pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{s_q}%' OR description LIKE '%{s_q}%'", conn))
        conn.close()

# [Tab 3] 세계 HS/세율
with tabs[2]:
    c_name = st.selectbox("국가", ["미국", "EU", "베트남", "중국", "일본"])
    raw_info = st.text_area("해외 사이트 데이터 붙여넣기")
    if st.button("해외 분석"):
        st.write(model.generate_content(f"{c_name} 관세 분석: {raw_data}").text)

# [Tab 7] 관리자 전용
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("운영 관리 (aegis01210)")
        conn = sqlite3.connect("users.db")
        pending = pd.read_sql("SELECT id, name, biz_name, is_approved FROM users WHERE is_approved=0", conn)
        st.subheader("승인 대기 목록")
        st.table(pending)
        tid = st.text_input("승인할 ID")
        if st.button("승인 완료"):
            conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (tid,))
            conn.commit()
            st.success("승인되었습니다.")
        conn.close()

# 하단 상담 채널
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")