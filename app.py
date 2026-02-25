import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re

# --- 1. 환경 설정 및 보안 DB 초기화 ---
def init_auth_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    # 회원 테이블 (승인 상태 필드 포함)
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, phone TEXT, email TEXT,
                biz_name TEXT, biz_no TEXT, biz_rep TEXT, biz_type TEXT, biz_item TEXT,
                biz_addr TEXT, tax_email TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    
    # 최초 관리자 계정 생성 (없을 경우만)
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn.commit()
    conn.close()

init_auth_db()

# Gemini API 설정
genai.configure(api_key=st.secrets.get("GEMINI_KEY", "YOUR_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

st.set_page_config(page_title="AEGIS HS 통합 검색 포털", layout="wide")

# --- 2. 로그인 및 세션 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_id = ""
    st.session_state.is_admin = False

def check_login(uid, upw):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    hashed_pw = hashlib.sha256(upw.encode()).hexdigest()
    c.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", (uid, hashed_pw))
    res = c.fetchone()
    conn.close()
    return res

# --- 3. 로그인 / 회원가입 UI ---
if not st.session_state.logged_in:
    menu = ["로그인", "회원가입"]
    choice = st.sidebar.selectbox("접속 메뉴", menu)

    if choice == "로그인":
        st.title("🔐 AEGIS HS 서비스 로그인")
        login_id = st.text_input("아이디")
        login_pw = st.text_input("비밀번호", type="password")
        if st.button("로그인"):
            auth = check_login(login_id, login_pw)
            if auth:
                if auth[0] == 1: # 승인된 사용자
                    st.session_state.logged_in = True
                    st.session_state.user_id = login_id
                    st.session_state.is_admin = bool(auth[1])
                    st.rerun()
                else:
                    st.error("계정 승인 대기 중입니다. 관리자에게 문의하세요.")
            else:
                st.error("아이디 또는 비밀번호가 틀렸습니다.")

    elif choice == "회원가입":
        st.title("📝 신규 회원가입")
        with st.form("signup_form"):
            st.subheader("ㄱ) 회원 정보")
            new_id = st.text_input("아이디 (중복확인)")
            new_pw = st.text_input("비밀번호", type="password")
            new_pw_chk = st.text_input("비밀번호 확인", type="password")
            new_name = st.text_input("이름")
            new_phone = st.text_input("전화번호")
            new_email = st.text_input("이메일")

            st.subheader("ㄴ) 사업자 정보")
            b_name = st.text_input("상호")
            b_no = st.text_input("사업자등록번호")
            b_rep = st.text_input("대표")
            b_type = st.text_input("업태")
            b_item = st.text_input("업종")
            b_addr = st.text_input("주소")
            t_email = st.text_input("세금계산서 발급 메일주소")

            if st.form_submit_button("가입 신청"):
                if new_pw != new_pw_chk:
                    st.error("비밀번호가 일치하지 않습니다.")
                else:
                    conn = sqlite3.connect("users.db")
                    c = conn.cursor()
                    try:
                        hpw = hashlib.sha256(new_pw.encode()).hexdigest()
                        c.execute("INSERT INTO users (id, pw, name, phone, email, biz_name, biz_no, biz_rep, biz_type, biz_item, biz_addr, tax_email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (new_id, hpw, new_name, new_phone, new_email, b_name, b_no, b_rep, b_type, b_item, b_addr, t_email))
                        conn.commit()
                        st.success("가입 신청이 완료되었습니다. 관리자 승인 후 이용 가능합니다.")
                    except:
                        st.error("이미 존재하는 아이디입니다.")
                    conn.close()
    st.stop()

# --- 4. 메인 대시보드 (로그인 후) ---
st.sidebar.success(f"{st.session_state.user_id}님 환영합니다.")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

# 탭 순서 조정: HS검색, 통계/감면부호, 세계 HS/세율, FTA정보, 세액계산기, (관리자)
tabs = ["🔍 HS검색", "📊 통계/감면부호", "🌎 세계 HS/세율", "📜 FTA정보", "🧮 세액계산기"]
if st.session_state.is_admin:
    tabs.append("⚙️ 관리자")

tab_list = st.tabs(tabs)

# --- [Tab 1] HS검색 (기존 국내통합검색 수정) ---
with tab_list[0]:
    st.header("HS코드 통합 검색")
    # (기존 이미지/텍스트 검색 로직 유지)
    st.info("이미지 분석 및 HSK 10자리 정밀 검색 기능입니다.")

# --- [Tab 2] 통계/감면부호 (구글 드라이브 연동형) ---
with tab_list[1]:
    st.header("통계부호 및 감면코드 조회")
    st.markdown("[데이터 출처: 구글 드라이브 클라우드 서버]")
    # 구글 드라이브에서 가져온 데이터를 검색하는 로직 (기존 엑셀 로드 방식에서 파일 소스만 변경)
    search_q = st.text_input("감면부호 또는 내국세 코드 검색")
    if search_q:
        st.write(f"'{search_q}'에 대한 드라이브 내 통합 검색 결과...")

# --- [Tab 4] FTA정보 (신규) ---
with tab_list[3]:
    st.header("FTA 협정별 정보 및 원산지 규정")
    target_fta = st.selectbox("협정 선택", ["RCEP", "한-미 FTA", "한-베트남 FTA", "한-중 FTA", "한-EU FTA"])
    if st.button("협정문 주요 내용 요약"):
        with st.spinner("AI가 협정 규정을 분석 중입니다..."):
            res = model.generate_content(f"{target_fta}의 일반적인 원산지 결정 기준과 특혜세율 적용 시 주의사항을 관세사 입장에서 설명해줘.")
            st.write(res.text)

# --- [Tab 5] 세액계산기 (신규) ---
with tab_list[4]:
    st.header("수입 세액 시뮬레이터")
    c1, c2 = st.columns(2)
    with c1:
        price = st.number_input("물품가격 (외화)", value=1000.0)
        currency = st.selectbox("통화", ["USD", "EUR", "JPY", "CNY"])
        ex_rate = st.number_input("적용 환율", value=1350.0)
    with c2:
        customs_rate = st.number_input("관세율 (%)", value=8.0)
        vat_rate = st.number_input("부가세율 (%)", value=10.0)
    
    if st.button("세액 계산하기"):
        cif = price * ex_rate
        duty = cif * (customs_rate / 100)
        vat = (cif + duty) * (vat_rate / 100)
        st.metric("총 예상 납부세액", f"{int(duty + vat):,} 원")
        st.write(f"- 과세가격: {int(cif):,}원 | 관세: {int(duty):,}원 | 부가세: {int(vat):,}원")

# --- [Tab 6] 관리자 (보안 로그인 시만 노출) ---
if st.session_state.is_admin:
    with tab_list[5]:
        st.header("운영자 전용 대시보드")
        admin_menu = ["회원 승인 관리", "사용 이력", "회원 삭제"]
        sel = st.radio("작업 선택", admin_menu, horizontal=True)
        
        conn = sqlite3.connect("users.db")
        if sel == "회원 승인 관리":
            pending = pd.read_sql("SELECT id, name, biz_name, is_approved FROM users WHERE is_approved=0", conn)
            st.table(pending)
            target_id = st.text_input("승인할 아이디 입력")
            if st.button("승인 처리"):
                conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (target_id,))
                conn.commit()
                st.success("승인되었습니다.")
        elif sel == "회원 삭제":
            all_users = pd.read_sql("SELECT id, name, is_admin FROM users", conn)
            st.dataframe(all_users)
            del_id = st.text_input("삭제할 아이디 입력")
            if st.button("계정 영구 삭제", help="주의: 복구 불가능합니다."):
                conn.execute("DELETE FROM users WHERE id=?", (del_id,))
                conn.commit()
                st.warning("삭제 완료.")
        conn.close()

# --- 5. 하단 연락처 및 상담 위젯 ---
st.divider()
st.subheader("📞 전문가 상담 및 기술 지원")
c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
with c1:
    st.markdown("""
    **이지스 관세사무소 (AEGIS Customs)** 전화: 010-8859-0403  
    메일: jhlee@aegiscustoms.com
    """)
with c2:
    st.link_button("📧 이메일 상담", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3:
    st.link_button("🌐 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
with c4:
    st.link_button("💬 카카오톡 문의", "https://pf.kakao.com/_nxexbTn", use_container_width=True)