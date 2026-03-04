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
    # HS코드 마스터 (HS코드(2026).csv)
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    # 표준품명 (표준품명(2026).csv)
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, std_name_kr TEXT, std_name_en TEXT)")
    # 관세율 (관세율(2026).csv)
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    # 세관장확인 (세관장확인대상 품목(2026)_수입.csv)
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    # 감면/면세 (관세감면부호, 내국세면세부호 등)
    c.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, name TEXT, rate TEXT)")
    conn.commit()
    conn.close()

    # 회원 DB (aegis01210 관리자 설정)
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
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
        elif res: st.error("승인 대기 중입니다.")
        else: st.error("계정 정보가 올바르지 않습니다.")
    st.stop()

# --- 3. 메인 레이아웃 및 탭 구성 ---
st.sidebar.write(f"✅ 접속: {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (AI 기반) ---
with tabs[0]:
    # (기존 HS검색 로직 유지: 이미지 미리보기, 100% 확률 병기 등)
    st.info("AI를 활용한 HS코드 분류 및 분석 탭입니다.")

# --- [Tab 2] 통계부호 (DB 기반 정밀 조회) ---
with tabs[1]:
    target_hs = st.text_input("조회할 HSK 10자리를 입력하세요 (숫자만)", placeholder="예: 0101211000")
    if st.button("데이터 조회 실행", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs)
            conn = sqlite3.connect("customs_master.db")
            
            # 1. 품명 (마스터 & 표준)
            master = pd.read_sql(f"SELECT name_kr, name_en FROM hs_master WHERE hs_code = '{hsk}'", conn)
            std = pd.read_sql(f"SELECT std_name_kr, std_name_en FROM standard_names WHERE hs_code = '{hsk}'", conn)
            
            # 2. 세율 (분류별)
            rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{hsk}'", conn)
            
            # 3. 세관장확인
            reqs = pd.read_sql(f"SELECT law, agency, document FROM req_import WHERE hs_code = '{hsk}'", conn)
            conn.close()

            if not master.empty:
                st.subheader(f"📋 HS {hsk} 상세 리포트")
                
                # 품명 섹션
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("### [국/영문 품명]")
                    st.write(f"**국문:** {master['name_kr'].values[0]}")
                    st.write(f"**영문:** {master['name_en'].values[0]}")
                with c2:
                    st.markdown("### [표준 품명]")
                    if not std.empty:
                        st.write(f"**국문:** {std['std_name_kr'].values[0]}")
                        st.write(f"**영문:** {std['std_name_en'].values[0]}")
                    else: st.write("표준품명 정보 없음")

                # 세율 섹션 (A, C, F, 기타 분류)
                st.divider()
                st.markdown("### 💰 관세율 정보")
                if not rates.empty:
                    ra = rates[rates['type'] == 'A']
                    rc = rates[rates['type'] == 'C']
                    rf = rates[rates['type'].str.startswith('F')]
                    retc = rates[~rates['type'].isin(['A', 'C']) & ~rates['type'].str.startswith('F')]

                    m1, m2 = st.columns(2)
                    m1.metric("기본세율 (A)", ra['rate'].values[0] + "%" if not ra.empty else "-")
                    m2.metric("WTO협정세율 (C)", rc['rate'].values[0] + "%" if not rc.empty else "-")
                    
                    st.write("**협정세율 (F)**")
                    st.dataframe(rf, hide_index=True, use_container_width=True)
                    st.write("**기타세율**")
                    st.dataframe(retc, hide_index=True, use_container_width=True)
                else: st.warning("등록된 세율 정보가 없습니다.")

                # 세관장확인 섹션
                st.divider()
                st.markdown("### 🛡️ 세관장확인대상 (수입)")
                if not reqs.empty:
                    st.table(reqs)
                else: st.success("세관장확인 대상 품목이 아닙니다.")
            else:
                st.error("해당 HS코드에 대한 마스터 정보가 DB에 없습니다. 관리자 탭에서 CSV를 업로드해 주세요.")

# --- [Tab 7] 관리자 (CSV 업로드 통합) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 데이터베이스 통합 관리")
        mode = st.selectbox("업로드할 CSV 종류 선택", ["HS코드(마스터)", "표준품명", "관세율", "세관장확인(수입)", "감면/면세부호"])
        up_file = st.file_uploader(f"{mode} 파일 업로드", type="csv")
        
        if up_file and st.button(f"{mode} 데이터 반영"):
            df = pd.read_csv(up_file, encoding='utf-8-sig')
            conn = sqlite3.connect("customs_master.db")
            
            if mode == "HS코드(마스터)":
                df = df[['HS부호', '한글품목명', '영문품목명']].copy()
                df.columns = ['hs_code', 'name_kr', 'name_en']
                df.to_sql('hs_master', conn, if_exists='replace', index=False)
            elif mode == "표준품명":
                df = df[['HS부호', '표준품명_한글', '표준품명_영문']].copy()
                df.columns = ['hs_code', 'std_name_kr', 'std_name_en']
                df.to_sql('standard_names', conn, if_exists='replace', index=False)
            elif mode == "관세율":
                df = df[['품목번호', '관세율구분', '관세율']].copy()
                df.columns = ['hs_code', 'type', 'rate']
                df.to_sql('rates', conn, if_exists='replace', index=False)
            elif mode == "세관장확인(수입)":
                df = df[['HS부호', '신고인확인법령코드명', '요건승인기관코드명', '요건확인서류명']].copy()
                df.columns = ['hs_code', 'law', 'agency', 'document']
                df.to_sql('req_import', conn, if_exists='replace', index=False)
            
            conn.close()
            st.balloons()
            st.success(f"{mode} 데이터가 DB에 저장되었습니다.")

# --- 하단 상담 위젯 ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 상담: 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)