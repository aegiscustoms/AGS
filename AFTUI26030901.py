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

# --- [AFTUI26030901] 전역 디자인 설정 ---
st.set_page_config(page_title="AEGIS - 전문 관세 행정 서비스", layout="wide")

TITLE_FONT_SIZE = "16px"
CONTENT_FONT_SIZE = "13px"

st.markdown(f"""
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        * {{ font-family: 'Pretendard', sans-serif; }}
        .stApp {{ background-color: #FFFFFF; }}
        .stTabs [data-baseweb="tab-list"] {{ gap: 24px; background-color: #FFFFFF; border-bottom: 1px solid #E2E8F0; }}
        .stTabs [data-baseweb="tab"] {{ height: 50px; color: #64748B; font-size: 15px; font-weight: 500; }}
        .stTabs [aria-selected="true"] {{ color: #1E3A8A !important; border-bottom: 2px solid #1E3A8A !important; }}
        .custom-header {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: 700; color: #1E3A8A; border-left: 4px solid #1E3A8A; padding-left: 12px; margin: 15px 0; }}
        .stButton > button {{ background-color: #1E3A8A; color: white; border-radius: 6px; font-weight: 600; }}
        .center-table {{ width: 100%; text-align: center !important; border-collapse: collapse; }}
        .center-table th {{ background-color: #F8FAFC !important; color: #1E3A8A !important; text-align: center !important; padding: 12px !important; border-bottom: 2px solid #E2E8F0; }}
        .center-table td {{ text-align: center !important; padding: 10px !important; border-bottom: 1px solid #F1F5F9; font-size: {CONTENT_FONT_SIZE}; }}
    </style>
""", unsafe_allow_html=True)

# --- 1. DB 초기화 ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rate_names (code TEXT, h_name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_export (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_gani (gani_hs TEXT, gani_name TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_reduction (code TEXT, content TEXT, rate TEXT, after_target TEXT, installment_months TEXT, installment_count TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_vat_exemption (name TEXT, type_name TEXT, code TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_internal_tax (item_name TEXT, tax_rate TEXT, type_code TEXT, type_name TEXT, tax_kind_code TEXT, unit TEXT, tax_base_price TEXT, agri_tax_yn TEXT)")
    conn.commit(); conn.close()
init_db()

# Gemini 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key); model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top:100px;'><h1 style='color:#1E3A8A;'>AEGIS</h1></div>", unsafe_allow_html=True)
    cl1, cl2, cl3 = st.columns([1, 1.4, 1])
    with cl2:
        with st.form("login"):
            l_id = st.text_input("아이디")
            l_pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인"):
                conn = sqlite3.connect("users.db")
                res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
                conn.close()
                if res and res[0] == 1:
                    st.session_state.logged_in = True; st.session_state.user_id = l_id; st.session_state.is_admin = bool(res[1]); st.rerun()
    st.stop()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관", "🧮 세액계산"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 ---
with tabs[0]:
    st.markdown("<div class='custom-header'>인공지능 HS코드 분석</div>", unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1])
    u_input = c1.text_input("품명/물품정보 입력", key="hs_q")
    u_img = c2.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"])
    if st.button("HS분석 실행", use_container_width=True):
        with st.spinner("분석 중..."):
            try:
                res = model.generate_content([f"관세사로서 분석: {u_input}", Image.open(u_img) if u_img else ""])
                st.write(res.text)
            except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (로직 복구) ---
with tabs[1]:
    st.markdown("<div class='custom-header'>HS 통합 정보 조회</div>", unsafe_allow_html=True)
    t_hs = st.text_input("HSK 10자리 입력", placeholder="예: 0101211000")
    if st.button("데이터 통합 조회", use_container_width=True):
        hsk = re.sub(r'[^0-9]', '', t_hs).zfill(10)
        conn = sqlite3.connect("customs_master.db")
        m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
        # [수정] 표준품명: HS부호에서 검색, 출력값은 '품명'필드(base_name)
        std = pd.read_sql(f"SELECT base_name as '품명', std_name_kr, std_name_en FROM standard_names WHERE hs_code = '{hsk}'", conn)
        r_query = f"SELECT r.type as '코드', n.h_name as '세율명칭', r.rate as '세율' FROM rates r LEFT JOIN rate_names n ON r.type = n.code WHERE r.hs_code = '{hsk}'"
        r_all = pd.read_sql(r_query, conn)
        req_i = pd.read_sql(f"SELECT law, agency, document FROM req_import WHERE hs_code = '{hsk}'", conn)
        conn.close()
        
        if not m.empty:
            st.info(f"**[{hsk}]** {m['name_kr'].values[0]}")
            c1, c2 = st.columns(2)
            c1.markdown("**표준품명**"); c1.write(std['품명'].values[0] if not std.empty else "없음")
            c2.markdown("**기본품명**"); c2.write(f"{m['name_kr'].values[0]}\n({m['name_en'].values[0]})")
            
            # 관세율 배치 로직 복구
            if not r_all.empty:
                r_all['세율'] = r_all['세율'].astype(str) + "%"
                ra = r_all[r_all['코드'] == 'A']; rc = r_all[r_all['코드'] == 'C']
                rf = r_all[r_all['코드'].str.startswith('F', na=False)]
                re_etc = r_all[~r_all['코드'].isin(['A', 'C']) & ~r_all['코드'].str.startswith('F', na=False)]
                
                m1, m2 = st.columns(2)
                m1.metric("기본세율 (A)", ra['세율'].values[0] if not ra.empty else "-")
                m2.metric("WTO협정세율 (C)", rc['세율'].values[0] if not rc.empty else "-")
                st.write("**기타세율**"); st.dataframe(re_etc, hide_index=True, use_container_width=True)
                st.write("**협정세율 (FTA)**"); st.dataframe(rf, hide_index=True, use_container_width=True)

# --- [Tab 3] 통계부호 (출력값 PREUI 복구) ---
with tabs[2]:
    st.markdown("<div class='custom-header'>통계부호 통합 검색</div>", unsafe_allow_html=True)
    s_tabs = {"간이세율(2026)": "stat_gani", "관세감면부호(2026)": "stat_reduction", "내국세면세부호(2026)": "stat_vat_exemption", "내국세율(2026)": "stat_internal_tax"}
    col1, col2 = st.columns([1, 2])
    sel = col1.selectbox("분류 선택", ["선택하세요"] + list(s_tabs.keys()))
    kw = col2.text_input("검색어")
    if st.button("조회 실행") and sel != "선택하세요":
        conn = sqlite3.connect("customs_master.db"); tbl = s_tabs[sel]
        if sel == "내국세면세부호(2026)":
            df = pd.read_sql(f"SELECT name as '내국세부가세감면명', type_name as '구분명', code as '내국세부가세감면코드' FROM {tbl} WHERE name LIKE '%{kw}%'", conn)
        elif sel == "내국세율(2026)":
            df = pd.read_sql(f"SELECT item_name as '신고품명', tax_rate as '내국세율', type_code as '내국세율구분코드', type_name as '내국세율구분코드명', tax_kind_code as '내국세세종코드', unit as '금액기준중수량단위', tax_base_price as '개소세과세기준가격', agri_tax_yn as '농특세과세여부' FROM {tbl} WHERE item_name LIKE '%{kw}%'", conn)
            if not df.empty: df['내국세율'] = df['내국세율'].astype(str) + "%"
        else: # 간이세율, 관세감면은 기존 고도화 로직 유지
            df = pd.read_sql(f"SELECT * FROM {tbl}", conn)
        st.dataframe(df, hide_index=True, use_container_width=True); conn.close()

# --- [Tab 4] 화물통관 (자동 연동 및 레이아웃 복구) ---
with tabs[3]:
    st.markdown("<div class='custom-header'>화물통관 진행정보</div>", unsafe_allow_html=True)
    if "bl_val" not in st.session_state: st.session_state.bl_val = ""
    if "mrn_val" not in st.session_state: st.session_state.mrn_val = ""
    
    col1, col2, col3 = st.columns([1, 2, 2])
    year = col1.selectbox("입항년도", [2026, 2025, 2024])
    bl_input = col2.text_input("B/L 번호", value=st.session_state.bl_val)
    mrn_input = col3.text_input("화물관리번호", value=st.session_state.mrn_val)
    
    if st.button("실시간 조회", use_container_width=True):
        API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
        url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
        params = {"crkyCn": API_KEY, "blYy": str(year), "hblNo": bl_input.upper(), "cargMtNo": mrn_input.upper()}
        res = requests.get(url, params=params)
        if res.status_code == 200:
            root = ET.fromstring(res.content); info = root.find(".//cargCsclPrgsInfoQryVo")
            if info is not None:
                # 상호 입력 업데이트
                st.session_state.bl_val = info.findtext("hblNo") or info.findtext("mblNo")
                st.session_state.mrn_val = info.findtext("cargMtNo")
                # 4대 지표 동일행 출력
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("현재상태", info.findtext("prgsStts"))
                m2.metric("품명", info.findtext("prnm")[:12])
                m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                m4.metric("현재위치", info.findtext("shedNm")[:10])
                # 이력 출력
                history = [{"처리단계": i.findtext("cargTrcnRelaBsopTpcd"), "처리일시": i.findtext("prcsDttm"), "장소": i.findtext("shedNm")} for i in root.findall(".//cargCsclPrgsInfoDtlQryVo")]
                st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
                st.rerun()

# --- [Tab 5] 세액계산기 (레이아웃 및 로직 전면 수정) ---
with tabs[4]:
    st.markdown("<div class='custom-header'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    if "calc_duty_rate" not in st.session_state: st.session_state.calc_duty_rate = 8.0
    if "calc_rate_type" not in st.session_state: st.session_state.calc_rate_type = "A"

    with st.container(border=True):
        st.write("**📍 1. 과세가격(CIF) 및 품목 입력**")
        c_left, c_right = st.columns(2)
        with c_left:
            p_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0)
            p_frt = st.number_input("운임 (Freight)", min_value=0)
            p_ins = st.number_input("보험료 (Insurance)", min_value=0)
        with c_right:
            p_ex = st.number_input("적용 환율", value=1350.0)
            st.write("품목분류(HSK)")
            h_col1, h_col2 = st.columns([0.7, 0.3])
            p_hs = h_col1.text_input("HSK 입력", label_visibility="collapsed")
            if h_col2.button("적용"):
                conn = sqlite3.connect("customs_master.db")
                r_df = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{p_hs}' AND type IN ('A', 'C')", conn)
                if not r_df.empty:
                    st.session_state.calc_duty_rate = float(str(r_df['rate'].values[0]).replace('%',''))
                    st.session_state.calc_rate_type = r_df['type'].values[0]; st.rerun()
            
            # 관세율, 부가세율 우측 하단 배치
            r_col1, r_col2 = st.columns(2)
            applied_d = r_col1.number_input(f"관세율({st.session_state.calc_rate_type}, %)", value=st.session_state.calc_duty_rate)
            applied_v = r_col2.number_input("부가세율(%)", value=10.0)
            
        cif_sum = int((p_price * p_ex) + p_frt + p_ins)
        st.info(f"**과세표준 (CIF KRW): {cif_sum:,.0f} 원**")

    if st.button("세액 계산 실행", use_container_width=True, type="primary"):
        d_val = int(cif_sum * (applied_d/100)); v_val = int((cif_sum + d_val) * (applied_v/100))
        st.markdown(f"<div style='font-size: 24px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 20px; border-radius: 8px;'>💰 예상세액: {d_val+v_val:,.0f} 원</div>", unsafe_allow_html=True)
        st.write(pd.DataFrame({"세종": ["관세", "부가세"], "세액": [f"{d_val:,.0f}", f"{v_val:,.0f}"]}).to_html(index=False, classes='center-table'), unsafe_allow_html=True)

# --- [Tab 6] 관리자 (기능 보존) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.markdown("<div class='custom-header'>관리자 데이터 센터</div>", unsafe_allow_html=True)
        m_list = ["HS코드(마스터)", "표준품명", "관세율", "관세율구분", "세관장확인(수입)", "세관장확인(수출)"]
        cols = st.columns(3)
        for i, m in enumerate(m_list):
            with cols[i%3]:
                st.write(f"**{m}**")
                up = st.file_uploader(m, type="csv", key=f"ad_{m}", label_visibility="collapsed")
                if up and st.button(f"반영", key=f"btn_{m}"):
                    conn = sqlite3.connect("customs_master.db")
                    pd.read_csv(up).to_sql(m, conn, if_exists='replace', index=False); st.success("완료")

# --- 푸터 (복구) ---
st.divider()
f1, f2, f3, f4 = st.columns([2.5, 1, 1, 1])
f1.write("**📞 010-8859-0403 (이지스 관세사무소)**")
f2.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
f3.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
f4.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")