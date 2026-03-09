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

# --- [AFTUI26030901] 전역 디자인 설정 (엘박스 스타일) ---
st.set_page_config(page_title="AEGIS - 전문 관세 행정 데이터 포털", layout="wide")

TITLE_FONT_SIZE = "16px"
CONTENT_FONT_SIZE = "13px"

st.markdown(f"""
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        * {{ font-family: 'Pretendard', sans-serif; }}
        .stApp {{ background-color: #FFFFFF; }}

        /* 엘박스 스타일 내비게이션 */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 24px;
            background-color: #FFFFFF;
            padding: 0px 20px;
            border-bottom: 1px solid #E2E8F0;
        }}
        .stTabs [data-baseweb="tab"] {{
            height: 50px;
            background-color: transparent;
            border: none;
            color: #64748B;
            font-size: 15px;
            font-weight: 500;
        }}
        .stTabs [aria-selected="true"] {{
            color: #1E3A8A !important;
            border-bottom: 2px solid #1E3A8A !important;
        }}

        /* 섹션 헤더 디자인 */
        .custom-header {{ 
            font-size: {TITLE_FONT_SIZE} !important; 
            font-weight: 700; 
            color: #1E3A8A; 
            margin-bottom: 16px; 
            border-left: 4px solid #1E3A8A; 
            padding-left: 12px; 
            margin-top: 10px;
        }}

        /* 전문가용 카드 섹션 */
        .custom-card {{
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            background-color: #FFFFFF;
        }}

        /* 버튼 커스텀 */
        .stButton > button {{
            background-color: #1E3A8A;
            color: white;
            border-radius: 6px;
            border: none;
            font-weight: 600;
        }}
        
        /* 중앙 정렬 테이블 */
        .center-table {{ width: 100%; text-align: center !important; border-collapse: collapse; }}
        .center-table th {{ background-color: #F8FAFC !important; color: #1E3A8A !important; text-align: center !important; padding: 12px !important; border-bottom: 2px solid #E2E8F0; }}
        .center-table td {{ text-align: center !important; padding: 10px !important; border-bottom: 1px solid #F1F5F9; font-size: {CONTENT_FONT_SIZE}; }}
    </style>
""", unsafe_allow_html=True)

# --- 1. 초기 DB 설정 (PREUI와 동일하게 유지) ---
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

# Gemini API
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top:100px;'><h1 style='color:#1E3A8A; font-size:42px; font-weight:800;'>AEGIS</h1><p style='color:#64748B;'>전문 관세 행정 데이터 포털 서비스</p></div>", unsafe_allow_html=True)
    cl1, cl2, cl3 = st.columns([1, 1.4, 1])
    with cl2:
        with st.container(border=True):
            l_id = st.text_input("아이디", placeholder="사업자번호 또는 아이디")
            l_pw = st.text_input("비밀번호", type="password", placeholder="비밀번호")
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
                else: st.error("정보 불일치 또는 승인 대기")
    st.stop()

# --- 3. 메인 인터페이스 ---
st.sidebar.markdown(f"### 👤 {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관", "🧮 세액계산"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 ---
with tabs[0]:
    st.markdown("<div class='custom-header'>인공지능 HS코드 분석</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/용도/기능/재질 정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)
    
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
                    st.markdown("### 📋 분석 리포트")
                    st.write(res.text)
                except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 ---
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
                st.markdown(f"#### 📦 HS {hsk} 상세 정보")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**기본품명**")
                    st.info(f"{m['name_kr'].values[0]}\n\n({m['name_en'].values[0]})")
                with col2:
                    st.markdown("**표준품명**")
                    if not std.empty: st.success(f"{std['std_name_kr'].values[0]}\n\n({std['std_name_en'].values[0]})")
                    else: st.warning("정보 없음")
                
                st.markdown("---")
                st.markdown("**💰 관세율 정보**")
                if not r_all.empty:
                    r_all['세율'] = r_all['세율'].astype(str) + "%"
                    st.dataframe(r_all, hide_index=True, use_container_width=True)
                
                st.markdown("---")
                st.markdown("**🛡️ 수출입 요건**")
                c_i, c_e = st.columns(2)
                with c_i: st.write("[수입]"); st.dataframe(req_i, hide_index=True, use_container_width=True)
                with c_e: st.write("[수출]"); st.dataframe(req_e, hide_index=True, use_container_width=True)
            else: st.error("정보 없음")

# --- [Tab 3] 통계부호 ---
with tabs[2]:
    st.markdown("<div class='custom-header'>통계부호 통합 검색 (2026)</div>", unsafe_allow_html=True)
    stat_tables = {"간이세율(2026)": "stat_gani", "관세감면부호(2026)": "stat_reduction", "내국세면세부호(2026)": "stat_vat_exemption", "내국세율(2026)": "stat_internal_tax"}
    col1, col2 = st.columns([1.2, 2])
    with col1: sel_name = st.selectbox("항목 선택", ["선택하세요"] + list(stat_tables.keys()), key="stat_sel_v2")
    if sel_name != "선택하세요":
        with col2: search_kw = st.text_input(f"🔍 {sel_name} 검색 키워드", placeholder="내용 또는 품명 입력", key="stat_kw_v2")
        if st.button("조회 실행", use_container_width=True):
            conn = sqlite3.connect("customs_master.db"); tbl = stat_tables[sel_name]
            if sel_name == "간이세율(2026)":
                df = pd.read_sql(f"SELECT gani_name as '간이품명', gani_hs as '간이HS부호', rate as '세율' FROM {tbl} WHERE gani_name LIKE '%{search_kw}%'", conn)
                if not df.empty: df['세율'] = df['세율'].astype(str) + "%"
            elif sel_name == "관세감면부호(2026)":
                df = pd.read_sql(f"SELECT content as '조항내용', code as '코드', rate as '감면율', installment_months, installment_count FROM {tbl} WHERE content LIKE '%{search_kw}%'", conn)
                if not df.empty:
                    df['감면율'] = df['감면율'].astype(str) + "%"
                    df['분납개월'] = df['installment_months'].apply(lambda x: str(x) if str(x) not in ['0', '0.0'] else "")
                    df = df.drop(columns=['installment_months', 'installment_count'])
            elif sel_name == "내국세율(2026)":
                df = pd.read_sql(f"SELECT item_name as '신고품명', tax_rate as '내국세율' FROM {tbl} WHERE item_name LIKE '%{search_kw}%'", conn)
                if not df.empty: df['내국세율'] = df['내국세율'].astype(str) + "%"
            else: df = pd.read_sql(f"SELECT * FROM {tbl} WHERE name LIKE '%{search_kw}%'", conn)
            conn.close()
            st.dataframe(df, hide_index=True, use_container_width=True)

# --- [Tab 4] 화물통관 ---
with tabs[3]:
    st.markdown("<div class='custom-header'>화물통관 진행정보 실시간 조회</div>", unsafe_allow_html=True)
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1: year = st.selectbox("입항년도", [2026, 2025, 2024])
    with col2: bl = st.text_input("B/L 번호")
    with col3: st.write(""); search_btn = st.button("실시간 조회")
    
    if search_btn and bl:
        with st.spinner(" Uni-Pass 연결 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
            params = {"crkyCn": CR_API_KEY, "blYy": str(year), "hblNo": bl.strip().upper()}
            try:
                res = requests.get(url, params=params, timeout=30)
                root = ET.fromstring(res.content)
                info = root.find(".//cargCsclPrgsInfoQryVo")
                if info is not None:
                    st.success(f"현재 상태: {info.findtext('prgsStts')}")
                    m1, m2 = st.columns(2)
                    m1.metric("품명", info.findtext("prnm")[:15])
                    m2.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                else: st.warning("정보 없음")
            except: st.error("조회 중 오류 발생")

# --- [Tab 5] 세액계산기 (PREUI 로직 완전 복구) ---
with tabs[4]:
    st.markdown("<div class='custom-header'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    if "duty_rate_widget" not in st.session_state: st.session_state["duty_rate_widget"] = 8.0
    if "selected_rate_type" not in st.session_state: st.session_state["selected_rate_type"] = "A"

    with st.container(border=True):
        st.write("**📍 1. 과세가격(CIF) 및 품목 입력**")
        cl, cr = st.columns(2)
        with cl:
            item_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0, key="calc_price")
            freight = st.number_input("운임 (Freight)", min_value=0, key="calc_frt")
            insurance = st.number_input("보험료 (Insurance)", min_value=0, key="calc_ins")
        with cr:
            ex_rate = st.number_input("적용 환율", value=1350.0, key="calc_ex")
            st.write("품목분류 적용")
            h1, h2 = st.columns([0.7, 0.3])
            with h1: hs_in = st.text_input("HS Code", key="calc_hs")
            with h2: 
                if st.button("적용", key="calc_apply"):
                    if hs_in:
                        hsk = re.sub(r'[^0-9]', '', hs_in).zfill(10)
                        conn = sqlite3.connect("customs_master.db")
                        rate_df = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{hsk}' AND type IN ('A', 'C')", conn)
                        conn.close()
                        if not rate_df.empty:
                            st.session_state["duty_rate_widget"] = float(str(rate_df['rate'].values[0]).replace('%', ''))
                            st.session_state["selected_rate_type"] = rate_df['type'].values[0]
                            st.rerun()

        st.markdown("---")
        r1, r2 = st.columns(2)
        with r1: d_rate = st.number_input(f"관세율 ({st.session_state['selected_rate_type']}, %)", value=st.session_state["duty_rate_widget"], key="d_rate_ui")
        with r2: v_rate = st.number_input("부가세율 (%)", value=10.0)
        
        cif_krw = int((item_price * ex_rate) + freight + insurance)
        st.info(f"**과세표준 (CIF KRW): {cif_krw:,.0f} 원**")

    if st.button("세액 계산 실행", use_container_width=True, type="primary"):
        duty = int(cif_krw * (d_rate/100))
        vat = int((cif_krw + duty) * (v_rate/100))
        st.markdown(f"<div style='font-size: 24px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 20px; border-radius: 8px;'>💰 예상세액: {duty+vat:,.0f} 원</div>", unsafe_allow_html=True)
        res_df = pd.DataFrame({"세종": ["관세", "부가세"], "세액(원)": [f"{duty:,.0f}", f"{vat:,.0f}"]})
        st.write(res_df.to_html(index=False, classes='center-table'), unsafe_allow_html=True)

# --- [Tab 6] 관리자 (PREUI 로직 100% 복구 및 버튼 활성화) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.markdown("<div class='custom-header'>관리자 데이터 센터</div>", unsafe_allow_html=True)
        
        # 1. HS 마스터 관리 (업로드 + 반영 버튼 구조 복구)
        st.subheader("📁 1. HS 마스터 및 요건 관리")
        m_list = ["HS코드(마스터)", "표준품명", "관세율", "관세율구분", "세관장확인(수입)", "세관장확인(수출)"]
        cols = st.columns(3)
        for i, m_name in enumerate(m_list):
            with cols[i%3]:
                st.write(f"**{m_name}**")
                up = st.file_uploader(f"{m_name}", type="csv", key=f"ad_{m_name}", label_visibility="collapsed")
                if up and st.button(f"반영", key=f"btn_{m_name}"):
                    try:
                        try: df = pd.read_csv(up, encoding='utf-8-sig')
                        except: df = pd.read_csv(up, encoding='cp949')
                        conn = sqlite3.connect("customs_master.db")
                        if m_name == "HS코드(마스터)":
                            df_map = df[['HS부호', '한글품목명', '영문품목명']].copy()
                            df_map.columns = ['hs_code', 'name_kr', 'name_en']
                        elif m_name == "표준품명":
                            df_map = df[['품명', 'HS부호', '표준품명_한글', '표준품명_영문']].copy()
                            df_map.columns = ['base_name', 'hs_code', 'std_name_kr', 'std_name_en']
                        elif m_name == "관세율":
                            df_map = df[['품목번호', '관세율구분', '관세율']].copy()
                            df_map.columns = ['hs_code', 'type', 'rate']
                        elif m_name == "관세율구분":
                            df_map = df[['상세통계부호', '한글내역']].copy()
                            df_map.columns = ['code', 'h_name']
                            df_map.to_sql('rate_names', conn, if_exists='replace', index=False)
                        elif "세관장확인" in m_name:
                            df_map = df[['HS부호', '신고인확인법령코드명', '요건승인기관코드명', '요건확인서류명']].copy()
                            df_map.columns = ['hs_code', 'law', 'agency', 'document']
                        
                        if 'hs_code' in df_map.columns: 
                            df_map['hs_code'] = df_map['hs_code'].astype(str).str.replace(r'[^0-9]', '', regex=True).str.zfill(10)
                        
                        target_tbl = {"HS코드(마스터)": "hs_master", "표준품명": "standard_names", "관세율": "rates", "세관장확인(수입)": "req_import", "세관장확인(수출)": "req_export"}
                        if m_name in target_tbl: df_map.to_sql(target_tbl[m_name], conn, if_exists='replace', index=False)
                        conn.close(); st.success(f"{m_name} 완료")
                    except Exception as e: st.error(f"오류: {e}")

        st.divider()
        # 2. 통계부호 관리 (업로드 + 반영 버튼 구조 복구)
        st.subheader("📊 2. 2026 통계부호 관리")
        stat_list = ["간이세율(2026)", "관세감면부호(2026)", "내국세면세부호(2026)", "내국세율(2026)"]
        s_cols = st.columns(2)
        for i, s_name in enumerate(stat_list):
            with s_cols[i%2]:
                st.write(f"**{s_name}**")
                s_up = st.file_uploader(f"{s_name} 업로드", type="csv", key=f"up_{s_name}", label_visibility="collapsed")
                if s_up and st.button(f"반영", key=f"sbtn_{s_name}"):
                    try:
                        try: sdf = pd.read_csv(s_up, encoding='utf-8-sig')
                        except: sdf = pd.read_csv(s_up, encoding='cp949')
                        conn = sqlite3.connect("customs_master.db")
                        if s_name == "간이세율(2026)":
                            sdf_map = sdf[['간이HS부호', '간이품명', '변경후세율']].copy()
                            sdf_map.columns = ['gani_hs', 'gani_name', 'rate']
                            sdf_map.to_sql('stat_gani', conn, if_exists='replace', index=False)
                        elif s_name == "관세감면부호(2026)":
                            sdf_map = sdf[['관세감면분납코드', '관세감면분납조항내용', '관세감면율', '사후관리대상여부', '분납개월수', '분납횟수']].copy()
                            sdf_map.columns = ['code', 'content', 'rate', 'after_target', 'installment_months', 'installment_count']
                            sdf_map.to_sql('stat_reduction', conn, if_exists='replace', index=False)
                        elif s_name == "내국세면세부호(2026)":
                            sdf_map = sdf[['내국세부가세감면명', '구분명', '내국세부가세감면코드']].copy()
                            sdf_map.columns = ['name', 'type_name', 'code']
                            sdf_map.to_sql('stat_vat_exemption', conn, if_exists='replace', index=False)
                        elif s_name == "내국세율(2026)":
                            sdf_map = sdf[['신고품명', '내국세율', '내국세율구분코드', '내국세율구분코드명', '내국세세종코드', '금액기준중수량단위', '개소세과세기준가격', '농특세과세여부']].copy()
                            sdf_map.columns = ['item_name', 'tax_rate', 'type_code', 'type_name', 'tax_kind_code', 'unit', 'tax_base_price', 'agri_tax_yn']
                            sdf_map.to_sql('stat_internal_tax', conn, if_exists='replace', index=False)
                        conn.close(); st.success(f"{s_name} 완료")
                    except Exception as e: st.error(f"오류: {e}")

# --- 하단 푸터 (PREUI 사양 완벽 복구) ---
st.divider()
f1, f2, f3, f4 = st.columns([2.5, 1, 1, 1])
with f1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with f2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with f3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with f4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")