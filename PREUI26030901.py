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

# --- 폰트 사이즈 전역 설정 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"

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
    
    # [탭3용 신규 테이블]
    c.execute("CREATE TABLE IF NOT EXISTS stat_gani (gani_hs TEXT, gani_name TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_reduction (code TEXT, content TEXT, rate TEXT, after_target TEXT, installment_months TEXT, installment_count TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_vat_exemption (name TEXT, type_name TEXT, code TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_internal_tax (item_name TEXT, tax_rate TEXT, type_code TEXT, type_name TEXT, tax_kind_code TEXT, unit TEXT, tax_base_price TEXT, agri_tax_yn TEXT)")
    
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

# Gemini API 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 및 세션 관리 ---
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

# DB 상세 정보 공통 함수
def display_hsk_details(hsk_code, prob=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code)).zfill(10)
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]} {f'({prob})' if prob else ''}")

# --- [Tab 1] HS검색 ---
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보(용도/기능/성분/재질) 입력", key="hs_q")
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
                    codes = re.findall(r'\d{10}', res.text)
                    if "100%" in res.text and codes:
                        st.divider(); display_hsk_details(codes[0], "100%")
                except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 ---
with tabs[1]:
    st.markdown(f"""
        <style>
            .custom-header {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: bold; color: #1E3A8A; margin-bottom: 8px; border-left: 4px solid #1E3A8A; padding-left: 8px; }}
            .custom-title {{ font-size: 13px !important; font-weight: bold; color: #334155; margin-bottom: 4px; }}
            .custom-value {{ font-size: {CONTENT_FONT_SIZE} !important; line-height: 1.5; background-color: #F8FAFC; padding: 8px; border-radius: 4px; border: 1px solid #E2E8F0; margin-bottom: 12px; min-height: 60px; }}
            div[data-testid="stDataFrame"] td {{ font-size: {CONTENT_FONT_SIZE} !important; }}
            div[data-testid="stDataFrame"] th {{ font-size: {CONTENT_FONT_SIZE} !important; }}
        </style>
    """, unsafe_allow_html=True)
    target_hs = st.text_input("조회할 HSK 10자리를 입력하세요 (0 포함)", key="hs_info_v2", placeholder="예: 0101211000")
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
                st.markdown(f"<div class='custom-header'>📋 HS {hsk} 상세 리포트</div>", unsafe_allow_html=True)
                cl, cr = st.columns(2)
                with cl:
                    st.markdown("<div class='custom-title'>표준품명</div>", unsafe_allow_html=True)
                    if not std.empty: st.markdown(f"<div class='custom-value'><b>한글:</b> {std['std_name_kr'].values[0]}<br><b>영문:</b> {std['std_name_en'].values[0]}</div>", unsafe_allow_html=True)
                    else: st.markdown("<div class='custom-value'>등록 정보 없음</div>", unsafe_allow_html=True)
                with cr:
                    st.markdown("<div class='custom-title'>기본품명</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='custom-value'><b>국문:</b> {m['name_kr'].values[0]}<br><b>영문:</b> {m['name_en'].values[0]}</div>", unsafe_allow_html=True)
                st.divider()
                st.markdown(f"<div class='custom-header'>💰 관세율 정보</div>", unsafe_allow_html=True)
                if not r_all.empty:
                    r_all['세율'] = r_all['세율'].astype(str) + "%"
                    ra = r_all[r_all['코드'] == 'A']; rc = r_all[r_all['코드'] == 'C']
                    rf = r_all[r_all['코드'].str.startswith('F', na=False)]
                    re_etc = r_all[~r_all['코드'].isin(['A', 'C']) & ~r_all['코드'].str.startswith('F', na=False)]
                    m1, m2 = st.columns(2)
                    with m1: st.metric("기본세율 (A)", ra['세율'].values[0] if not ra.empty else "-")
                    with m2: st.metric("WTO협정세율 (C)", rc['세율'].values[0] if not rc.empty else "-")
                    st.markdown("<div class='custom-title' style='margin-top:10px;'>기타세율</div>", unsafe_allow_html=True)
                    st.dataframe(re_etc, hide_index=True, use_container_width=True)
                    st.markdown("<div class='custom-title'>협정세율 (FTA)</div>", unsafe_allow_html=True)
                    st.dataframe(rf, hide_index=True, use_container_width=True)
                st.divider()
                st.markdown(f"<div class='custom-header'>🛡️ 세관장확인대상 (수출입요건)</div>", unsafe_allow_html=True)
                ci, ce = st.columns(2)
                with ci: st.markdown("<div class='custom-title'>[수입 요건]</div>", unsafe_allow_html=True); st.dataframe(req_i, hide_index=True, use_container_width=True)
                with ce: st.markdown("<div class='custom-title'>[수출 요건]</div>", unsafe_allow_html=True); st.dataframe(req_e, hide_index=True, use_container_width=True)
            else: st.error("정보 없음")

# --- [Tab 3] 통계부호 (검색 및 출력 로직 고도화) ---
with tabs[2]:
    st.markdown(f"<style>.tab3-title {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: bold; color: #1E3A8A; margin-bottom: 5px; }}</style>", unsafe_allow_html=True)
    st.markdown("<div class='tab3-title'>📊 통계부호 통합 검색 (2026)</div>", unsafe_allow_html=True)

    stat_tables = {
        "간이세율(2026)": "stat_gani",
        "관세감면부호(2026)": "stat_reduction",
        "내국세면세부호(2026)": "stat_vat_exemption",
        "내국세율(2026)": "stat_internal_tax"
    }
    
    col1, col2 = st.columns([1.2, 2])
    with col1:
        sel_name = st.selectbox("통계부호 명칭 선택", ["선택하세요"] + list(stat_tables.keys()), key="stat_sel_v2")
    
    if sel_name != "선택하세요":
        conn = sqlite3.connect("customs_master.db")
        check = conn.execute(f"SELECT count(*) FROM {stat_tables[sel_name]}").fetchone()[0]
        
        if check == 0:
            st.warning(f"⚠️ {sel_name} 대상 통계부호가 DB에 저장되지 않았습니다.")
            conn.close()
        else:
            with col2:
                search_kw = st.text_input(f"🔍 {sel_name} 검색 키워드", placeholder="내용 또는 품명을 입력하세요", key="stat_kw_v2")
            
            if st.button("조회 실행", use_container_width=True):
                tbl = stat_tables[sel_name]
                
                if sel_name == "간이세율(2026)":
                    # 출력값: 1) 간이품명 2) 간이HS부호 3) 세율(%)
                    df = pd.read_sql(f"SELECT gani_name as '간이품명', gani_hs as '간이HS부호', rate as '세율' FROM {tbl} WHERE gani_name LIKE '%{search_kw}%'", conn)
                    if not df.empty:
                        df['세율'] = df['세율'].astype(str) + "%"

                elif sel_name == "관세감면부호(2026)":
                    # 출력값: 1) 조항내용 2) 코드 3) 감면율(%) 4) 사후관리 5) 분납(0 제외)
                    df = pd.read_sql(f"SELECT content as '관세감면분납조항내용', code as '관세감면분납코드', rate as '관세감면율', after_target as '사후관리대상여부', installment_months, installment_count FROM {tbl} WHERE content LIKE '%{search_kw}%'", conn)
                    if not df.empty:
                        # 관세감면율 뒤에 % 추가
                        df['관세감면율'] = df['관세감면율'].astype(str) + "%"
                        # 0이 아닌 경우만 표기
                        df['분납개월수'] = df['installment_months'].apply(lambda x: str(x) if str(x) != '0' and str(x) != '0.0' else "")
                        df['분납횟수'] = df['installment_count'].apply(lambda x: str(x) if str(x) != '0' and str(x) != '0.0' else "")
                        df = df.drop(columns=['installment_months', 'installment_count'])

                elif sel_name == "내국세면세부호(2026)":
                    # 출력값: 1) 감면명 2) 구분명 3) 코드
                    df = pd.read_sql(f"SELECT name as '내국세부가세감면명', type_name as '구분명', code as '내국세부가세감면코드' FROM {tbl} WHERE name LIKE '%{search_kw}%'", conn)

                elif sel_name == "내국세율(2026)":
                    # 출력값: 1) 신고품명 2) 내국세율(%) 3) 코드 4) 코드명 5) 세종코드 6) 단위 7) 기준가격 8) 농특세
                    df = pd.read_sql(f"SELECT item_name as '신고품명', tax_rate as '내국세율', type_code as '내국세율구분코드', type_name as '내국세율구분코드명', tax_kind_code as '내국세세종코드', unit as '금액기준중수량단위', tax_base_price as '개소세과세기준가격', agri_tax_yn as '농특세과세여부' FROM {tbl} WHERE item_name LIKE '%{search_kw}%'", conn)
                    if not df.empty:
                        # 내국세율 뒤에 % 추가
                        df['내국세율'] = df['내국세율'].astype(str) + "%"
                
                conn.close()
                if not df.empty:
                    st.success(f"✅ {len(df)}건의 결과를 찾았습니다.")
                    st.dataframe(df, hide_index=True, use_container_width=True)
                else:
                    st.warning("일치하는 검색 결과가 없습니다.")
    else:
        st.info("조회하실 통계부호를 선택해 주세요.")

# --- [Tab 4] 화물통관진행정보 ---
with tabs[3]:
    st.markdown(f"<div class='custom-header'>📦 실시간 화물통관 진행정보 조회</div>", unsafe_allow_html=True)
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    if not CR_API_KEY: st.error("API 키 미설정"); st.stop()
    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1: carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2: bl_no = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL 번호", key="bl_v3")
    with col3: st.write(""); search_btn = st.button("실시간 조회", use_container_width=True)
    if search_btn:
        if bl_no:
            with st.spinner("가져오는 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
                try:
                    response = requests.get(url, params=params, timeout=30)
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        t_cnt = root.findtext(".//tCnt")
                        if t_cnt and int(t_cnt) > 0:
                            info = root.find(".//cargCsclPrgsInfoQryVo")
                            st.success(f"✅ 상태: {info.findtext('prgsStts')}")
                            m1, m2, m3 = st.columns(3)
                            m1.metric("상태", info.findtext('prgsStts')); m2.metric("품명", info.findtext("prnm")[:12]); m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                            st.markdown("---")
                            history = []
                            for item in root.findall(".//cargCsclPrgsInfoDtlQryVo"):
                                history.append({"처리단계": item.findtext("cargTrcnRelaBsopTpcd"), "처리일시": item.findtext("prcsDttm"), "장치장/내용": item.findtext("shedNm") if item.findtext("shedNm") else item.findtext("rlbrCn")})
                            st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
                        else: st.warning("결과 없음")
                except Exception as e: st.error(f"연결 실패: {e}")

# --- [Tab 5] 세액계산기 ---
with tabs[4]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    if "duty_rate_widget" not in st.session_state: st.session_state["duty_rate_widget"] = 8.0
    if "selected_rate_type" not in st.session_state: st.session_state["selected_rate_type"] = "A"

    with st.container(border=True):
        st.write("**📍 1. 과세가격(CIF) 및 품목 입력**")
        col_left, col_right = st.columns(2)
        with col_left:
            item_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0, key="calc_item_price")
            freight = st.number_input("운임 (Freight, KRW)", min_value=0, value=0, key="calc_freight")
            insurance = st.number_input("보험료 (Insurance, KRW)", min_value=0, value=0, key="calc_insurance")
        with col_right:
            exchange_rate = st.number_input("적용 환율", min_value=1.0, value=1350.0, key="calc_ex_rate")
            st.write("품목분류 (HS코드 10자리)")
            hs_col1, hs_col2 = st.columns([0.7, 0.3])
            with hs_col1: input_hs = st.text_input("HS Code", label_visibility="collapsed", placeholder="예: 0101211000", key="calc_hs_code_input")
            with hs_col2:
                if st.button("적용", use_container_width=True):
                    if input_hs:
                        hsk_clean = re.sub(r'[^0-9]', '', input_hs).zfill(10)
                        try:
                            conn = sqlite3.connect("customs_master.db")
                            query = f"SELECT type, rate FROM rates WHERE hs_code = '{hsk_clean}' AND type IN ('A', 'C')"
                            rate_df = pd.read_sql(query, conn)
                            conn.close()
                            if not rate_df.empty:
                                def parse_rate(v):
                                    if isinstance(v, str): return float(v.replace('%', ''))
                                    return float(v)
                                rate_df['rate_num'] = rate_df['rate'].apply(parse_rate)
                                min_row = rate_df.loc[rate_df['rate_num'].idxmin()]
                                st.session_state["duty_rate_widget"] = float(min_row['rate_num'])
                                st.session_state["selected_rate_type"] = min_row['type']
                                st.toast(f"HS {hsk_clean} 적용 완료"); st.rerun()
                            else: st.warning("해당 HS코드의 A/C 세율 정보가 없습니다.")
                        except Exception as e: st.error(f"조회 오류: {e}")

            rate_col1, rate_col2 = st.columns(2)
            with rate_col1: applied_duty_rate = st.number_input(f"관세율 (구분:{st.session_state['selected_rate_type']}, %)", min_value=0.0, key="duty_rate_widget")
            with rate_col2: applied_vat_rate = st.number_input("부가세율 (%)", min_value=0.0, value=10.0, key="calc_vat_rate")

        cif_krw = int((item_price * exchange_rate) + freight + insurance)
        st.info(f"**과세표준 (CIF KRW): {cif_krw:,.0f} 원**")

    if st.button("세액 계산 실행", use_container_width=True, type="primary"):
        tax_duty = int(cif_krw * (st.session_state["duty_rate_widget"] / 100))
        tax_vat = int((cif_krw + tax_duty) * (applied_vat_rate / 100))
        total_tax = tax_duty + tax_vat
        st.markdown(f"<div style='font-size: 22px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #FCA5A5;'>💰 예상세액: {total_tax:,.0f} 원</div>", unsafe_allow_html=True)
        st.markdown("### 📊 세액 산출 상세")
        res_df = pd.DataFrame({"세종": ["관세", "부가가치세"], "세액(원)": [f"{tax_duty:,.0f}", f"{tax_vat:,.0f}"]})
        st.markdown("""<style>.center-table { width: 100%; text-align: center !important; } .center-table th { background-color: #F3F4F6 !important; text-align: center !important; } .center-table td { text-align: center !important; font-size: 16px; }</style>""", unsafe_allow_html=True)
        st.write(res_df.to_html(index=False, classes='center-table'), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("""<div style='font-size: 12px; color: #6B7280; line-height: 1.8; border-left: 3px solid #D1D5DB; padding-left: 10px; background-color: #F9FAFB; padding: 10px;'>※ 개별소비세, 주세, 교육세 등 내국세 부과대상의 예상세액은 관세사와 상담 부탁드립니다.<br>※ 예상세액은 실제 세액과 다를 수 있으므로 참조의 목적으로만 이용하시기 바랍니다.</div>""", unsafe_allow_html=True)

# --- [Tab 6] 관리자 (탭3 신규 업로드 로직 통합) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 관리자 데이터 센터")
        
        # 📁 1. HS 마스터 관리
        st.subheader("📁 1. HS 마스터 관리")
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
                        
                        if 'hs_code' in df_map.columns: df_map['hs_code'] = df_map['hs_code'].astype(str).str.replace(r'[^0-9]', '', regex=True).str.zfill(10)
                        target_tbl = {"HS코드(마스터)": "hs_master", "표준품명": "standard_names", "관세율": "rates", "세관장확인(수입)": "req_import", "세관장확인(수출)": "req_export"}
                        if m_name in target_tbl: df_map.to_sql(target_tbl[m_name], conn, if_exists='replace', index=False)
                        conn.close(); st.success(f"{m_name} 반영 성공")
                    except Exception as e: st.error(f"오류: {e}")

        st.divider()
        
        # 📁 2. 통계부호 관리 (신규 추가)
        st.subheader("📁 2. 통계부호 관리 (탭3 전용)")
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
                        
                        conn.close(); st.success(f"{s_name} DB 반영 완료")
                    except Exception as e: st.error(f"오류: {e}")

# 하단 푸터 (고정)
st.divider(); c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")