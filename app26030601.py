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

# --- 전역 설정 및 폰트 사양 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"

# 관세청 서버의 봇 차단을 방지하기 위한 표준 브라우저 헤더
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 (내부 관리용) ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    # 이지스 전용 데이터인 표준품명 테이블 유지
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    conn.commit()
    conn.close()

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini AI 설정
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
        res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res and res[0] == 1:
            st.session_state.logged_in = True
            st.session_state.user_id = l_id
            st.session_state.is_admin = bool(res[1])
            st.rerun()
        else: st.error("정보 불일치 또는 승인 대기")
    st.stop()

# --- 3. 메인 탭 구성 ---
st.sidebar.write(f"✅ {st.session_state.user_id} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (Gemini AI) ---
with tabs[0]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>🔍 AI 기반 HS코드 분석</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명 및 물품정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if st.button("분석 실행", use_container_width=True):
        with st.spinner("AI가 HS코드를 분류 중입니다..."):
            try:
                prompt = f"당신은 전문 관세사입니다. 다음 물품 '{u_input}'에 가장 적합한 HSK 10자리를 추천하고 분류 근거를 제시하세요."
                content = [prompt]
                if u_img: content.append(Image.open(u_img))
                res = model.generate_content(content)
                st.markdown("### 📋 분석 리포트")
                st.write(res.text)
            except Exception as e: st.error(f"분석 오류: {e}")

# --- [Tab 2] HS정보 (실시간 관세율 API) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 실시간 품목별 관세율 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 10자리 입력", placeholder="예: 8517130000", key="hs_rate_api")

    if st.button("실시간 관세율 조회", use_container_width=True):
        if not target_hs: st.warning("HS코드를 입력하세요.")
        else:
            with st.spinner("관세청 서버에서 최신 세율 데이터를 가져오는 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/itemRateQry/retrieveItemRate"
                params = {"crkyCn": RATE_KEY, "hsCd": target_hs.strip()}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    if res.text:
                        root = ET.fromstring(res.content)
                        items = root.findall(".//itemRateQryVo")
                        if items:
                            rate_list = []
                            for i in items:
                                rate_list.append({
                                    "구분": i.findtext("tarfClsfCd"),
                                    "세율명칭": i.findtext("tarfNm"),
                                    "세율": f"{i.findtext('itrt')}%",
                                    "시작일": i.findtext("aplyStrtDt")
                                })
                            df = pd.DataFrame(rate_list)
                            # 메트릭 표시
                            m1, m2 = st.columns(2)
                            with m1:
                                val_a = df[df['구분']=='A']['세율'].values
                                st.metric("기본세율 (A)", val_a[0] if len(val_a)>0 else "-")
                            with m2:
                                val_c = df[df['구분']=='C']['세율'].values
                                st.metric("WTO세율 (C)", val_c[0] if len(val_c)>0 else "-")
                            st.dataframe(df.style.set_properties(**{'font-size': CONTENT_FONT_SIZE, 'text-align': 'center'}), hide_index=True, use_container_width=True)
                        else: st.warning("조회된 데이터가 없습니다.")
                    else: st.error("관세청 서버 응답이 비어있습니다.")
                except Exception as e: st.error(f"API 호출 오류: {e}")

# --- [Tab 3] 통계부호 (실시간 공통코드 API) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    
    # 가이드 기반 주요 분류코드 매핑
    clft_dict = {"관세감면코드": "001", "내국세면세부호": "002", "보세구역": "003", "세관부호": "004"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("부호 분류", list(clft_dict.keys()))
    with col2: kw = st.text_input("검색어 (부호 또는 명칭)", placeholder="예: 인천, 감면")

    if st.button("부호 실시간 검색", use_container_width=True):
        with st.spinner("최신 코드 마스터를 조회 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cmmnCdQry/retrieveCmmnCd"
            params = {"crkyCn": STAT_KEY, "clftCd": clft_dict[sel_clft]}
            try:
                res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                if res.text:
                    root = ET.fromstring(res.content)
                    codes = root.findall(".//cmmnCdQryVo")
                    if codes:
                        res_list = []
                        for c in codes:
                            c_name, c_id = c.findtext("cdNm"), c.findtext("cd")
                            if not kw or (kw in c_name or kw in c_id):
                                res_list.append({"코드": c_id, "명칭": c_name, "설명": c.findtext("cdDesc")})
                        st.dataframe(pd.DataFrame(res_list).style.set_properties(**{'font-size': CONTENT_FONT_SIZE}), hide_index=True, use_container_width=True)
                    else: st.warning("데이터가 없습니다.")
                else: st.error("서버 응답 오류")
            except Exception as e: st.error(f"API 호출 오류: {e}")

# --- [Tab 4] 화물통관진행정보 (기존 유지 및 헤더 보강) ---
with tabs[3]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📦 실시간 화물 추적 (Uni-Pass)</div>", unsafe_allow_html=True)
    CARGO_KEY = st.secrets.get("CARGO_API_KEY", "").strip()
    
    c1, c2 = st.columns([1, 2])
    with c1: yy = st.selectbox("입항년도", [2026, 2025, 2024], index=0)
    with c2: bl = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL")

    if st.button("화물 실시간 조회", use_container_width=True):
        if not bl: st.warning("번호를 입력하세요.")
        else:
            with st.spinner("화물 진행 정보를 가져오는 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                params = {"crkyCn": CARGO_KEY, "blYy": str(yy), "hblNo": bl.strip().upper()}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    root = ET.fromstring(res.content)
                    info = root.find(".//cargCsclPrgsInfoQryVo")
                    if info is not None:
                        st.success(f"현재 상태: {info.findtext('prgsStts')}")
                        st.markdown(f"**품명:** {info.findtext('prnm')} | **중량:** {info.findtext('ttwg')} {info.findtext('wghtUt')}")
                    else: st.warning("조회 결과가 없습니다.")
                except Exception as e: st.error(f"API 오류: {e}")

# --- [Tab 6] 관리자 (이지스 고유 데이터 관리) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 관리자 데이터 센터")
        st.subheader("📁 표준품명 및 내부 데이터 관리")
        up_std = st.file_uploader("표준품명 CSV 업로드", type="csv")
        if up_std and st.button("표준품명 반영"):
            df = pd.read_csv(up_std, encoding='utf-8-sig')
            conn = sqlite3.connect("customs_master.db")
            df.to_sql('standard_names', conn, if_exists='replace', index=False)
            conn.close(); st.success("반영 완료")

# 하단 상담 채널
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")