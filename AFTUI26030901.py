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
        .stButton > button {{ background-color: #1E3A8A !important; color: white !important; border-radius: 6px; font-weight: 600; width: 100%; }}
        .center-table {{ width: 100%; text-align: center !important; border-collapse: collapse; }}
        .center-table th {{ background-color: #F8FAFC !important; color: #1E3A8A !important; text-align: center !important; padding: 12px !important; border-bottom: 2px solid #E2E8F0; }}
        .center-table td {{ text-align: center !important; padding: 10px !important; border-bottom: 1px solid #F1F5F9; font-size: {CONTENT_FONT_SIZE}; }}
    </style>
""", unsafe_allow_html=True)

# --- 인코딩 안전 로드 함수 ---
def safe_read_csv(uploaded_file):
    try:
        # 1차 시도: utf-8-sig (BOM 포함)
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, encoding='utf-8-sig', engine='python')
    except:
        try:
            # 2차 시도: cp949 (일반적인 엑셀 CSV)
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='cp949', engine='python')
        except:
            # 3차 시도: euc-kr
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='euc-kr', engine='python')

# --- 1. 초기 DB 설정 ---
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

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", ("aegis01210", admin_pw))
    conn_auth.commit(); conn_auth.close()

init_db()

# Gemini 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top:100px;'><h1 style='color:#1E3A8A; font-size:42px; font-weight:800;'>AEGIS</h1></div>", unsafe_allow_html=True)
    cl1, cl2, cl3 = st.columns([1, 1.4, 1])
    with cl2:
        with st.form("login_form"):
            l_id = st.text_input("아이디")
            l_pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인"):
                conn = sqlite3.connect("users.db")
                res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                                   (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
                conn.close()
                if res and res[0] == 1:
                    st.session_state.logged_in = True; st.session_state.user_id = l_id; st.session_state.is_admin = bool(res[1]); st.rerun()
                else: st.error("정보 불일치 또는 승인 대기")
    st.stop()

# --- 3. 메인 인터페이스 ---
st.sidebar.markdown(f"### 👤 {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False; st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관", "🧮 세액계산"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (PREUI 프롬프트 복구) ---
with tabs[0]:
    st.markdown("<div class='custom-header'>인공지능 HS코드 분석</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보(용도/기능/성분/재질) 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if u_img: st.image(Image.open(u_img), caption="📸 분석 이미지", width=300)
    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("분석 중..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다. 아래 지침에 따라 HS코드를 분류하고 리포트를 작성하세요.
                    1. 품명: (유저입력 '{u_input}' 참고하여 예상 품명 제시)
                    2. 추천결과:
                       - 1순위가 100%인 경우: "1순위 [코드] 100%"만 출력하고 종료.
                       - 미확정인 경우: 상위 3순위까지 추천하되 3순위가 낮으면 2순위까지만.
                       - 형식: "n순위 [코드] [확률]%" """
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"상세 정보: {u_input}")
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트"); st.write(res.text)
                except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (PREUI 로직 복구) ---
with tabs[1]:
    st.markdown("<div class='custom-header'>HS 통합 정보 조회</div>", unsafe_allow_html=True)
    target_hs = st.text_input("HSK 10자리를 입력하세요", key="hs_info_v2", placeholder="예: 0101211000")
    if st.button("데이터 통합 조회", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs).zfill(10)
            conn = sqlite3.connect("customs_master.db")
            m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
            std = pd.read_sql(f"SELECT base_name, std_name_kr, std_name_en FROM standard_names WHERE hs_code = '{hsk}'", conn)
            r_query = f"SELECT r.type as '코드', n.h_name as '세율명칭', r.rate as '세율' FROM rates r LEFT JOIN rate_names n ON r.type = n.code WHERE r.hs_code = '{hsk}'"
            r_all = pd.read_sql(r_query, conn)
            req_i = pd.read_sql(f"SELECT law as '관련법령', agency as '확인기관', document as '구비서류' FROM req_import WHERE hs_code = '{hsk}'", conn)
            req_e = pd.read_sql(f"SELECT law as '관련법령', agency as '확인기관', document as '구비서류' FROM req_export WHERE hs_code = '{hsk}'", conn)
            conn.close()
            if not m.empty:
                st.markdown(f"#### 📋 HS {hsk} 상세 리포트")
                c1, c2 = st.columns(2)
                with c1: st.markdown("**표준품명**"); st.success(std['base_name'].values[0] if not std.empty else "없음")
                with c2: st.markdown("**기본품명**"); st.info(f"{m['name_kr'].values[0]}\n\n({m['name_en'].values[0]})")
                
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
                
                st.divider(); st.markdown("**🛡️ 세관장확인대상**")
                ci, ce = st.columns(2)
                with ci: st.write("[수입]"); st.dataframe(req_i, hide_index=True, use_container_width=True)
                with ce: st.write("[수출]"); st.dataframe(req_e, hide_index=True, use_container_width=True)

# --- [Tab 3] 통계부호 (필드명 PREUI 복구) ---
with tabs[2]:
    st.markdown("<div class='custom-header'>통계부호 통합 검색 (2026)</div>", unsafe_allow_html=True)
    s_tabs = {"간이세율(2026)": "stat_gani", "관세감면부호(2026)": "stat_reduction", "내국세면세부호(2026)": "stat_vat_exemption", "내국세율(2026)": "stat_internal_tax"}
    col1, col2 = st.columns([1.2, 2])
    sel_name = col1.selectbox("분류 선택", ["선택하세요"] + list(s_tabs.keys()), key="stat_sel_v3")
    search_kw = col2.text_input("검색어 입력", key="stat_kw_v3")
    
    if st.button("조회 실행", use_container_width=True) and sel_name != "선택하세요":
        conn = sqlite3.connect("customs_master.db"); tbl = s_tabs[sel_name]
        if sel_name == "간이세율(2026)":
            df = pd.read_sql(f"SELECT gani_name as '간이품명', gani_hs as '간이HS부호', rate as '세율' FROM {tbl} WHERE gani_name LIKE '%{search_kw}%'", conn)
            if not df.empty: df['세율'] = df['세율'].astype(str) + "%"
        elif sel_name == "관세감면부호(2026)":
            df = pd.read_sql(f"SELECT content as '관세감면분납조항내용', code as '관세감면분납코드', rate as '관세감면율', after_target as '사후관리대상여부', installment_months, installment_count FROM {tbl} WHERE content LIKE '%{search_kw}%'", conn)
            if not df.empty:
                df['관세감면율'] = df['관세감면율'].astype(str) + "%"
                df['분납개월수'] = df['installment_months'].apply(lambda x: str(x) if str(x) not in ['0', '0.0'] else "")
                df['분납횟수'] = df['installment_count'].apply(lambda x: str(x) if str(x) not in ['0', '0.0'] else "")
                df = df.drop(columns=['installment_months', 'installment_count'])
        elif sel_name == "내국세면세부호(2026)":
            df = pd.read_sql(f"SELECT name as '내국세부가세감면명', type_name as '구분명', code as '내국세부가세감면코드' FROM {tbl} WHERE name LIKE '%{search_kw}%'", conn)
        elif sel_name == "내국세율(2026)":
            df = pd.read_sql(f"SELECT item_name as '신고품명', tax_rate as '내국세율', type_code as '내국세율구분코드', type_name as '내국세율구분코드명', tax_kind_code as '내국세세종코드', unit as '금액기준중수량단위', tax_base_price as '개소세과세기준가격', agri_tax_yn as '농특세과세여부' FROM {tbl} WHERE item_name LIKE '%{search_kw}%'", conn)
            if not df.empty: df['내국세율'] = df['내국세율'].astype(str) + "%"
        conn.close(); st.dataframe(df, hide_index=True, use_container_width=True)

# --- [Tab 4] 화물통관 (양방향 자동입력 구현) ---
with tabs[3]:
    st.markdown("<div class='custom-header'>화물통관 실시간 조회</div>", unsafe_allow_html=True)
    if "bl_input" not in st.session_state: st.session_state.bl_input = ""
    if "mrn_input" not in st.session_state: st.session_state.mrn_input = ""
    c_y, c_b, c_m = st.columns([1, 2, 2])
    year = c_y.selectbox("입항년도", [2026, 2025, 2024])
    bl_val = c_b.text_input("B/L 번호", value=st.session_state.bl_input)
    mrn_val = c_m.text_input("화물관리번호", value=st.session_state.mrn_input)
    if st.button("실시간 조회", use_container_width=True):
        API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
        url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
        params = {"crkyCn": API_KEY, "blYy": str(year), "hblNo": bl_val.upper(), "cargMtNo": mrn_val.upper()}
        res = requests.get(url, params=params)
        if res.status_code == 200:
            root = ET.fromstring(res.content); info = root.find(".//cargCsclPrgsInfoQryVo")
            if info is not None:
                st.session_state.bl_input = info.findtext("hblNo") or info.findtext("mblNo")
                st.session_state.mrn_input = info.findtext("cargMtNo")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("현재상태", info.findtext("prgsStts"))
                m2.metric("품명", info.findtext("prnm")[:12])
                m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                m4.metric("현재위치", info.findtext("shedNm")[:10])
                hist = [{"처리단계": i.findtext("cargTrcnRelaBsopTpcd"), "처리일시": i.findtext("prcsDttm"), "장소": i.findtext("shedNm")} for i in root.findall(".//cargCsclPrgsInfoDtlQryVo")]
                st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
                st.rerun()

# --- [Tab 5] 세액계산 (즉시 반영 로직) ---
with tabs[4]:
    st.markdown("<div class='custom-header'>🧮 예상 세액계산기</div>", unsafe_allow_html=True)
    if "calc_duty" not in st.session_state: st.session_state.calc_duty = 8.0
    if "calc_type" not in st.session_state: st.session_state.calc_type = "A"
    with st.container(border=True):
        st.write("**📍 1. 과세가격(CIF) 및 품목 입력**")
        cl, cr = st.columns(2)
        with cl:
            p_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0)
            p_frt = st.number_input("운임 (Freight)", min_value=0)
            p_ins = st.number_input("보험료 (Insurance)", min_value=0)
        with cr:
            p_ex = st.number_input("환율", value=1350.0)
            st.write("품목분류(HSK)")
            h1, h2 = st.columns([0.7, 0.3])
            hs_in = h1.text_input("HSK 입력", label_visibility="collapsed")
            if h2.button("적용"):
                conn = sqlite3.connect("customs_master.db")
                r_df = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{hs_in}' AND type IN ('A', 'C')", conn)
                if not r_df.empty:
                    st.session_state.calc_duty = float(str(r_df['rate'].values[0]).replace('%',''))
                    st.session_state.calc_type = r_df['type'].values[0]; st.rerun()
            r1, r2 = st.columns(2)
            a_d = r1.number_input(f"관세율({st.session_state.calc_type}, %)", value=st.session_state.calc_duty)
            a_v = r2.number_input("부가세율(%)", value=10.0)
        cif = int((p_price * p_ex) + p_frt + p_ins)
        st.info(f"**과세표준 (CIF KRW): {cif:,.0f} 원**")
    if st.button("세액 계산 실행", use_container_width=True, type="primary"):
        d = int(cif * (a_d/100)); v = int((cif + d) * (a_v/100))
        st.markdown(f"<div style='font-size: 24px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 20px; border-radius: 8px;'>💰 예상세액: {d+v:,.0f} 원</div>", unsafe_allow_html=True)
        st.write(pd.DataFrame({"세종": ["관세", "부가세"], "세액": [f"{d:,.0f}", f"{v:,.0f}"]}).to_html(index=False, classes='center-table'), unsafe_allow_html=True)

# --- [Tab 6] 관리자 (인코딩 완전 해결) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.markdown("<div class='custom-header'>관리자 데이터 센터</div>", unsafe_allow_html=True)
        st.subheader("📁 1. 마스터 및 요건 관리")
        m_list = ["HS코드(마스터)", "표준품명", "관세율", "관세율구분", "세관장확인(수입)", "세관장확인(수출)"]
        cols = st.columns(3)
        for i, m_name in enumerate(m_list):
            with cols[i%3]:
                st.write(f"**{m_name}**")
                up = st.file_uploader(m_name, type="csv", key=f"ad_{m_name}", label_visibility="collapsed")
                if up and st.button("반영", key=f"btn_{m_name}"):
                    df = safe_read_csv(up)
                    if df is not None:
                        conn = sqlite3.connect("customs_master.db")
                        t_map = {"HS코드(마스터)": "hs_master", "표준품명": "standard_names", "관세율": "rates", "세관장확인(수입)": "req_import", "세관장확인(수출)": "req_export"}
                        if m_name in t_map: df.to_sql(t_map[m_name], conn, if_exists='replace', index=False)
                        elif m_name == "관세율구분": df.to_sql("rate_names", conn, if_exists='replace', index=False)
                        st.success(f"{m_name} 완료"); conn.close()
                    else: st.error("파일 읽기 실패")
        st.divider()
        st.subheader("📊 2. 2026 통계부호 관리")
        s_list = ["간이세율(2026)", "관세감면부호(2026)", "내국세면세부호(2026)", "내국세율(2026)"]
        s_cols = st.columns(2)
        for i, s_name in enumerate(s_list):
            with s_cols[i%2]:
                st.write(f"**{s_name}**")
                s_up = st.file_uploader(s_name, type="csv", key=f"sup_{s_name}", label_visibility="collapsed")
                if s_up and st.button("반영", key=f"sbtn_{s_name}"):
                    sdf = safe_read_csv(s_up)
                    if sdf is not None:
                        conn = sqlite3.connect("customs_master.db")
                        s_map = {"간이세율(2026)": "stat_gani", "관세감면부호(2026)": "stat_reduction", "내국세면세부호(2026)": "stat_vat_exemption", "내국세율(2026)": "stat_internal_tax"}
                        sdf.to_sql(s_map[s_name], conn, if_exists='replace', index=False)
                        st.success(f"{s_name} 완료"); conn.close()
                    else: st.error("파일 읽기 실패")

# --- 푸터 ---
st.divider()
f1, f2, f3, f4 = st.columns([2.5, 1, 1, 1])
f1.write("**📞 010-8859-0403 (이지스 관세사무소)**")
f2.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
f3.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
f4.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")