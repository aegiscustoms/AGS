import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. DB 초기화 및 관리자 설정 ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    c = conn_auth.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, phone TEXT, email TEXT,
                biz_name TEXT, biz_no TEXT, biz_rep TEXT, biz_type TEXT, biz_item TEXT,
                biz_addr TEXT, tax_email TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    
    # 관리자 계정 ID: aegis01210 (오타 수정 반영)
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

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

# --- 3. 로그인 및 세션 관리 ---
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
            else: st.error("정보가 일치하지 않습니다.")
    # 회원가입 폼 생략 (기존 로직과 동일)
    st.stop()

# --- 4. 메인 탭 구성 ---
st.sidebar.write(f"✅ 접속: {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tab_names = ["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"]
if st.session_state.is_admin: tab_names.append("⚙️ 관리자")
tabs = st.tabs(tab_names)

# DB 상세 조회 함수
def display_hsk_details(hsk_code, probability=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM requirements WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]} ({probability})")
        c1, c2 = st.columns(2)
        with c1: st.write("**적용 세율**"); st.table(rates)
        with c2: st.write("**수입 요건**"); st.table(reqs)

# --- [Tab 1] HS검색 ---
with tabs[0]:
    col1, col2 = st.columns([2, 1])
    with col1: u_input = st.text_input("품명/물품정보 입력", key="hs_q")
    with col2: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    
    # 이미지 미리보기 (요청 반영)
    if u_img:
        st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)

    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("AI 관세사가 정밀 분석 중입니다..."):
                try:
                    # 품명 로직 및 확률 로직 프롬프트 (요청 반영)
                    prompt = f"""당신은 전문 관세사입니다. 다음 규칙에 따라 HS코드를 제안하세요.
                    1. 품명: 유저 입력('{u_input}')이 있으면 그 명칭을 그대로 사용하고, 없으면 이미지를 분석해 '예상품명'을 제시하세요.
                    2. 확실한 경우(100%): HSK 10자리 코드를 제시하고 옆에 (100%)를 기재하세요.
                    3. 불확실한 경우: 6단위(소호) 기준으로 가장 적합한 순서대로 3순위까지 추천하고 각각의 확률을 %로 기재하세요.
                    4. 답변 마지막에 '추천결과: [코드] [확률]' 형식을 반드시 포함하세요.
                    """
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"입력정보: {u_input}")
                    
                    res = model.generate_content(content)
                    st.markdown("### 📋 AI 분석 리포트")
                    st.write(res.text)
                    
                    # 100% 결과 시 DB 자동 연동
                    lines = res.text.split('\n')
                    for line in lines:
                        if "100%" in line:
                            code_10 = re.findall(r'\d{10}', line)
                            if code_10: 
                                st.divider()
                                display_hsk_details(code_10[0], "100%")
                                break
                except Exception as e: st.error(f"오류 발생: {e}")

# --- [Tab 2] 통계부호 (간소화 버전) ---
with tabs[1]:
    s_q = st.text_input("", placeholder="검색할 부호 또는 명칭을 입력하세요")
    if st.button("검색"):
        conn = sqlite3.connect("customs_master.db")
        res = pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{s_q}%' OR description LIKE '%{s_q}%'", conn)
        conn.close()
        st.table(res)

# --- [Tab 3] 세계 HS/세율 ---
with tabs[2]:
    st.header("🌎 세계 HS/세율 가이드")
    c_name = st.selectbox("국가 선택", ["미국", "EU", "베트남", "중국", "일본"])
    c_hs = st.text_input("현지 HS코드")
    raw_data = st.text_area("해외 사이트 데이터 붙여넣기")
    if st.button("해외 분석 실행"):
        res = model.generate_content(f"{c_name} HS {c_hs} 분석: {raw_data}")
        st.markdown(res.text)

# --- 나머지 탭들 및 상담 위젯 ---
with tabs[3]: st.info("📜 FTA 정보 수집 중입니다.")
with tabs[4]: st.info("📦 화물통관진행정보 준비 중입니다.")
with tabs[5]: st.write("🧮 세액계산기 영역")

# 하단 상담 채널 (요청 반영)
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1:
    st.markdown("### 📞 상담: 010-8859-0403")
    st.write("이지스 관세사무소 (jhlee@aegiscustoms.com)")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)