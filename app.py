import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re

# --- 1. 초기 DB 및 관리자 설정 ---
def init_db():
    conn = sqlite3.connect("users.db")
    admin_id = "aegis01210" # 수정된 관리자 아이디
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    conn.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn.commit()
    conn.close()

init_db()

# --- 2. API 설정 (보안 강화) ---
# Streamlit Cloud Secrets에 GEMINI_KEY가 등록되어 있어야 합니다.
api_key = st.secrets.get("GEMINI_KEY")
if not api_key:
    st.error("❌ API 키를 찾을 수 없습니다. Streamlit Cloud의 Settings -> Secrets에 'GEMINI_KEY'를 등록해주세요.")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- 3. 로그인 시스템 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 AEGIS 서비스 로그인")
    l_id = st.text_input("아이디")
    l_pw = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
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
            else: st.error("승인 대기 중입니다.")
        else: st.error("정보 불일치")
    st.stop()

# --- 4. 메인 기능 ---
st.sidebar.write(f"✅ 접속중: {st.session_state.user_id}")
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
    
    prob_text = f" ({probability})" if probability else ""
    if not master.empty:
        st.success(f"✅ [{code_clean}]{prob_text} {master['name_kr'].values[0]}")
        c1, c2 = st.columns(2)
        with c1: st.write("**적용 세율**"); st.table(rates)
        with c2: st.write("**수입 요건**"); st.table(reqs)
    else:
        st.warning(f"DB에 {code_clean} 정보가 없습니다.")

# [Tab 1] HS검색 (수정된 로직 반영)
with tabs[0]:
    col1, col2 = st.columns([2, 1])
    with col1: u_input = st.text_input("HSK 10자리 또는 품명")
    with col2: u_img = st.file_uploader("이미지 분석", type=["jpg", "png"])
    
    if st.button("HS분석 실행"):
        if u_img or u_input:
            with st.spinner("AI 분석 중..."):
                prompt = """당신은 전문 관세사입니다. 다음 규칙에 따라 HS코드를 제안하세요.
                1. 확실한 경우(100%): HSK 10자리 코드를 제시하고 옆에 (100%)를 기재하세요.
                2. 불확실한 경우: 6단위(소호) 기준으로 가장 적합한 순서대로 3순위까지 추천하고 각각의 확률을 %로 기재하세요.
                3. 답변 마지막에 '추천결과: [코드] [확률]' 형식을 지켜주세요.
                """
                content = [prompt]
                if u_img: content.append(Image.open(u_img))
                if u_input: content.append(f"물품정보: {u_input}")
                
                res = model.generate_content(content)
                st.write(res.text)
                
                # 결과 파싱 및 DB 연동
                lines = res.text.split('\n')
                for line in lines:
                    if "100%" in line:
                        code = re.findall(r'\d{10}', line)
                        if code: display_hsk_details(code[0], "100%")
                    elif any(x in line for x in ["1순위", "2순위", "3순위"]):
                        code_6 = re.findall(r'\d{6}', line)
                        if code_6: st.info(f"💡 추천 소호(6단위): {code_6[0]} - 상세 정보를 위해 10단위를 입력해주세요.")

# [Tab 2] 통계부호 (검색창 + 버튼)
with tabs[1]:
    s_q = st.text_input("", placeholder="부호 또는 명칭 입력")
    if st.button("통계부호 검색"):
        conn = sqlite3.connect("customs_master.db")
        res = pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{s_q}%' OR description LIKE '%{s_q}%'", conn)
        conn.close()
        st.table(res)

# [Tab 3] 세계 HS/세율
with tabs[2]:
    c_name = st.selectbox("국가", ["미국", "EU", "베트남", "중국", "일본"])
    raw_data = st.text_area("해외 사이트 정보 복사/붙여넣기")
    if st.button("분석"):
        res = model.generate_content(f"{c_name} 관세 분석: {raw_data}")
        st.markdown(res.text)

with tabs[3]: st.info("FTA 정보를 수집 중입니다.")
with tabs[4]: st.info("화물통관진행정보를 준비 중입니다.")
with tabs[5]: st.write("세액계산기 로직 영역")

# [관리자 탭]
if st.session_state.is_admin:
    with tabs[6]:
        st.write(f"⚙️ {st.session_state.user_id} 관리자 페이지")
        # 회원 관리 로직...

# 하단 상담 채널
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 메일", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3: st.link_button("🌐 홈피", "https://aegiscustoms.com/", use_container_width=True)
with c4: st.link_button("💬 카톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)