import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io
import requests
import xml.etree.ElementTree as ET

# --- 전역 설정 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 1, 1)", 
                      (admin_id, admin_pw, "관리자"))
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
    if st.button("로그인"):
        conn = sqlite3.connect("users.db")
        res = conn.execute("SELECT is_approved, is_admin, name FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res:
            if res[0] == 1:
                st.session_state.logged_in = True
                st.session_state.user_id = l_id
                st.session_state.user_name = res[2]
                st.session_state.is_admin = bool(res[1])
                st.rerun()
            else: st.warning("승인 대기 중입니다.")
        else: st.error("정보 불일치")
    st.stop()

# --- 3. 메인 화면 ---
st.sidebar.write(f"✅ {st.session_state.user_name} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (AI) ---
with tabs[0]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>🔍 AI 품목분류 분석</div>", unsafe_allow_html=True)
    u_input = st.text_input("물품 정보를 입력하세요", key="hs_q")
    if st.button("분석 실행", use_container_width=True):
        with st.spinner("AI 분석 중..."):
            try:
                res = model.generate_content(f"관세사 입장에서 '{u_input}'의 HS코드를 추천해줘.")
                st.write(res.text)
            except Exception as e: st.error(e)

# --- [Tab 2] HS정보 (품목별 관세율 API - 진단 모드) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 실시간 관세율 정보 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 10자리", placeholder="예: 8517130000", key="hs_rate_api")
    if st.button("실시간 관세율 조회", use_container_width=True):
        if target_hs:
            with st.spinner("조회 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/itemRateQry/retrieveItemRate"
                params = {"crkyCn": RATE_KEY, "hsCd": target_hs.strip()}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    if res.text.strip():
                        root = ET.fromstring(res.content)
                        items = root.findall(".//itemRateQryVo")
                        if items:
                            data = [{"구분": i.findtext("tarfClsfCd"), "명칭": i.findtext("tarfNm"), "세율": f"{i.findtext('itrt')}%"} for i in items]
                            st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)
                        else:
                            # 데이터가 없을 때 서버가 보낸 메시지 확인
                            st.warning(f"데이터 없음. 서버 메시지: {root.findtext('.//ntceCn') or '없음'}")
                    else: st.error("서버에서 빈 응답을 보냈습니다. 인증키 승인 여부를 확인하세요.")
                except Exception as e: st.error(f"연결 오류: {e}")

# --- [Tab 3] 통계부호 (공통코드 API - 진단 모드) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    # 가이드북 분류코드: 관세감면(001), 내국세면세(002) 등은 실제 관세청 부여 코드여야 함
    clft_dict = {"관세감면": "001", "내국세면세": "002", "보세구역": "003"} 
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("분류", list(clft_dict.keys()))
    with col2: kw = st.text_input("검색어", placeholder="예: 인천")
    if st.button("부호 실시간 검색", use_container_width=True):
        url = "https://unipass.customs.go.kr:38010/ext/rest/cmmnCdQry/retrieveCmmnCd"
        params = {"crkyCn": STAT_KEY, "clftCd": clft_dict[sel_clft]}
        try:
            res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
            if res.text.strip():
                root = ET.fromstring(res.content)
                codes = root.findall(".//cmmnCdQryVo")
                res_list = [{"코드": c.findtext("cd"), "명칭": c.findtext("cdNm")} for c in codes if not kw or kw in c.findtext("cdNm")]
                st.dataframe(pd.DataFrame(res_list), hide_index=True, use_container_width=True)
            else: st.error("서버 응답 없음. 인증키를 확인하세요.")
        except Exception as e: st.error(f"연결 오류: {e}")

# --- [Tab 4] 화물통관진행정보 (고객님 고정 코드) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1: carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2: bl_no = st.text_input("B/L 번호 입력", placeholder="번호 입력", key="bl_final_v3")
    with col3: st.write(""); search_btn = st.button("실시간 조회", use_container_width=True)
    if search_btn and bl_no:
        with st.spinner("조회 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
            params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
            try:
                response = requests.get(url, params=params, timeout=30)
                root = ET.fromstring(response.content)
                info = root.find(".//cargCsclPrgsInfoQryVo")
                if info is not None:
                    st.success(f"상태: {info.findtext('prgsStts')}")
                    history = [{"처리단계": i.findtext("cargTrcnRelaBsopTpcd"), "일시": i.findtext("prcsDttm")} for i in root.findall(".//cargCsclPrgsInfoDtlQryVo")]
                    st.dataframe(pd.DataFrame(history), use_container_width=True)
            except Exception as e: st.error(e)

# --- [Tab 6] 관리자 (사용자 관리 전용) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 사용자 계정 관리")
        conn = sqlite3.connect("users.db")
        df_u = pd.read_sql("SELECT id, name, is_approved FROM users", conn)
        st.table(df_u)
        uid = st.text_input("승인/삭제할 ID 입력")
        c1, c2 = st.columns(2)
        if c1.button("승인 처리"):
            conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (uid,)); conn.commit(); st.rerun()
        if c2.button("계정 삭제"):
            conn.execute("DELETE FROM users WHERE id=?", (uid,)); conn.commit(); st.rerun()
        conn.close()

# --- 하단 푸터 (고객님 고정 사양) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")