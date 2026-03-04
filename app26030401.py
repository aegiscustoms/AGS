import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. DB 초기화 및 테이블 구조 설정 ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    # HS코드 마스터
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    # 표준품명
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, std_name_kr TEXT, std_name_en TEXT)")
    # 관세율
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    # 세관장확인 (수입)
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    # 감면/면세부호
    c.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, name TEXT, rate TEXT)")
    conn.commit()
    conn.close()

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    # 관리자 계정 ID: aegis01210
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini API 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 AEGIS 서비스 로그인")
    l_id = st.text_input("아이디")
    l_pw = st.text_input("비밀번호", type="password")
    if st.button("로그인", use_container_width=True):
        conn = sqlite3.connect("users.db")
        res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res and res[0] == 1:
            st.session_state.logged_in = True
            st.session_state.user_id = l_id
            st.session_state.is_admin = bool(res[1])
            st.rerun()
        else: st.error("정보 불일치 또는 승인 대기 상태입니다.")
    st.stop()

# --- 3. 메인 앱 레이아웃 ---
st.sidebar.write(f"✅ {st.session_state.user_id} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# DB 상세 정보 출력 공통 함수
def display_hsk_details(hsk_code, probability=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM req_import WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]} {f'({probability})' if probability else ''}")
        c1, c2 = st.columns(2)
        with c1: st.write("**세율 정보**"); st.dataframe(rates, hide_index=True)
        with c2: st.write("**세관장확인**"); st.dataframe(reqs, hide_index=True)

# [Tab 1] HS검색 (미리보기 + 품명 로직 + 확률 병기)
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)

    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("분석 중..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다.
                    1. 품명: 유저입력('{u_input}')이 있으면 그대로 사용, 없으면 이미지를 보고 '예상품명' 제시.
                    2. 100% 확정 시: 10자리 HSK 코드 옆에 (100%) 표기.
                    3. 미확정 시: 6단위 기준 상위 3순위까지 확률(%)과 함께 추천.
                    결과 하단에 '추천결과: [코드] [확률]' 형식을 지켜주세요."""
                    
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"입력: {u_input}")
                    
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트")
                    st.write(res.text)
                    
                    codes = re.findall(r'\d{10}', res.text)
                    if "100%" in res.text and codes:
                        st.divider()
                        display_hsk_details(codes[0], "100%")
                except Exception as e: st.error(f"오류: {e}")


# --- [Tab 2] 통계부호 (정밀 조회 및 numpy 에러 방지) ---
with tabs[1]:
    target_hs = st.text_input("조회할 HSK 10자리 (숫자만)", key="stat_q")
    if st.button("데이터 조회"):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs)
            conn = sqlite3.connect("customs_master.db")
            m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
            std = pd.read_sql(f"SELECT * FROM standard_names WHERE hs_code = '{hsk}'", conn)
            r = pd.read_sql(f"SELECT * FROM rates WHERE hs_code = '{hsk}'", conn)
            req = pd.read_sql(f"SELECT * FROM req_import WHERE hs_code = '{hsk}'", conn)
            conn.close()

            if not m.empty:
                st.subheader(f"📋 HS {hsk} 상세 정보")
                c1, c2 = st.columns(2)
                with c1:
                    st.info("**기본 품명**")
                    st.write(f"국문: {m['name_kr'].values[0]}")
                    st.write(f"영문: {m['name_en'].values[0]}")
                with c2:
                    st.info("**표준 품명**")
                    if not std.empty:
                        st.write(f"국문: {std['std_name_kr'].values[0]}")
                        st.write(f"영문: {std['std_name_en'].values[0]}")
                    else: st.write("표준품명 정보 없음")

                st.divider()
                st.markdown("### 💰 관세율 분류")
                if not r.empty:
                    # 데이터 타입을 문자열로 강제 변환하여 numpy 연산 에러 방지
                    ra = r[r['type'] == 'A']
                    rc = r[r['type'] == 'C']
                    rf = r[r['type'].str.startswith('F', na=False)]
                    re_etc = r[~r['type'].isin(['A', 'C']) & ~r['type'].str.startswith('F', na=False)]
                    
                    m1, m2 = st.columns(2)
                    # metric 출력 시 str() 처리
                    m1.metric("기본세율(A)", f"{ra['rate'].values[0]}%" if not ra.empty else "-")
                    m2.metric("WTO세율(C)", f"{rc['rate'].values[0]}%" if not rc.empty else "-")
                    
                    st.write("**협정세율(F)**"); st.dataframe(rf, hide_index=True)
                    st.write("**기타세율**"); st.dataframe(re_etc, hide_index=True)

                st.divider()
                st.markdown("### 🛡️ 세관장확인 (수입)")
                if not req.empty: st.table(req)
                else: st.success("세관장확인 대상 품목이 아닙니다.")
            else:
                st.warning("DB에 해당 HS코드가 없습니다. 관리자 탭에서 데이터를 업로드하세요.")

# --- [Tab 7] 관리자 (CSV 업로드) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 데이터베이스 관리")
        mode = st.selectbox("파일 종류 선택", ["HS코드(마스터)", "표준품명", "관세율", "세관장확인(수입)"])
        up = st.file_uploader("CSV 파일 업로드", type="csv")
        if up and st.button("DB 데이터 반영"):
            df = pd.read_csv(up, encoding='utf-8-sig')
            conn = sqlite3.connect("customs_master.db")
            try:
                # 파일별 헤더 매핑 (보내주신 2026 CSV 기준)
                if mode == "HS코드(마스터)":
                    df = df[['HS부호', '한글품목명', '영문품목명']].copy()
                    df.columns = ['hs_code', 'name_kr', 'name_en']
                elif mode == "표준품명":
                    df = df[['HS부호', '표준품명_한글', '표준품명_영문']].copy()
                    df.columns = ['hs_code', 'std_name_kr', 'std_name_en']
                elif mode == "관세율":
                    df = df[['품목번호', '관세율구분', '관세율']].copy()
                    df.columns = ['hs_code', 'type', 'rate']
                elif mode == "세관장확인(수입)":
                    df = df[['HS부호', '신고인확인법령코드명', '요건승인기관코드명', '요건확인서류명']].copy()
                    df.columns = ['hs_code', 'law', 'agency', 'document']
                
                # HS코드 숫자 클렌징
                df['hs_code'] = df['hs_code'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df.to_sql(mode.split('(')[0].lower().replace(" ", "_"), conn, if_exists='replace', index=False)
                st.success(f"{mode} 반영 성공!")
            except Exception as ex: 
                st.error(f"매핑 오류: {ex}. CSV 파일의 헤더명을 확인하세요.")
            conn.close()

# 하단 상담 채널
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")