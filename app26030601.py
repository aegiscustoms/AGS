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
    
    # (수정) 탭3 API 전환에 따라 stat_codes 테이블 관련 로직은 더 이상 필요치 않으나 하위 호환을 위해 유지하거나 생략 가능
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

# --- [Tab 1] HS검색 (관세사님 고정 코드) ---
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

# --- [Tab 2] HS정보 (확정 사양) ---
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

# --- [Tab 3] 통계부호 (수정: 실시간 API 추출 방식 적용) ---
with tabs[2]:
    st.markdown(f"""
        <style>
            .tab3-title {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: bold; color: #1E3A8A; margin-bottom: 5px; }}
            div[data-testid="stDataFrame"] td {{ font-size: {CONTENT_FONT_SIZE} !important; }}
        </style>
    """, unsafe_allow_html=True)
    st.markdown("<div class='tab3-title'>📊 실시간 통계부호 검색 (Uni-Pass API)</div>", unsafe_allow_html=True)
    
    STAT_API_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    
    # 가이드북 API019 기반 구분코드 매핑
    clft_dict = {
        "관세감면/분납부호": "A01",
        "내국세면세/감면부호": "A02",
        "내국세율부호": "A04",
        "용도부호": "A05",
        "보세구역부호": "A08",
        "신고인부호": "A10",
        "항구공항부호": "A11"
    }
    
    col1, col2 = st.columns([1, 2])
    with col1:
        sel_label = st.selectbox("조회 분류 선택", list(clft_dict.keys()), key="api_clft_sel")
        sel_code = clft_dict[sel_label]
    with col2:
        search_kw = st.text_input("검색 키워드 (부호 또는 내역)", placeholder="예: 인천, 농업, A01 등", key="api_stat_kw")

    if st.button("실시간 부호 조회", use_container_width=True):
        if not STAT_API_KEY:
            st.error("통계부호용 인증키(STAT_API_KEY)가 설정되지 않았습니다.")
        else:
            with st.spinner("관세청 서버에서 데이터를 불러오는 중..."):
                # 가이드 API019 URL: statsSgnQry/retrieveStatsSgnBrkd
                url = "https://unipass.customs.go.kr:38010/ext/rest/statsSgnQry/retrieveStatsSgnBrkd"
                params = {"crkyCn": STAT_API_KEY, "statsSgnclftCd": sel_code}
                
                try:
                    res = requests.get(url, params=params, timeout=20)
                    if res.status_code == 200:
                        root = ET.fromstring(res.content)
                        # 에러 체크
                        ntce = root.findtext(".//ntceInfo")
                        if ntce and "존재하지 않는" in ntce:
                            st.error(f"❌ API 인증 실패: {ntce}")
                        else:
                            items = root.findall(".//statsSgnQryVo")
                            if items:
                                data_list = []
                                for item in items:
                                    s_code = item.findtext("statsSgn")
                                    s_name = item.findtext("koreBrkd")
                                    s_rate = item.findtext("itxRt") # 내국세율(해당시)
                                    
                                    # 키워드 필터링 (서버는 전체를 주므로 클라이언트에서 필터)
                                    if not search_kw or (search_kw.upper() in s_code.upper() or search_kw in s_name):
                                        data_list.append({
                                            "통계부호": s_code,
                                            "한글내역": s_name,
                                            "세율/비고": s_rate if s_rate else ""
                                        })
                                
                                if data_list:
                                    st.success(f"✅ {len(data_list)}건의 데이터를 확인했습니다.")
                                    st.dataframe(pd.DataFrame(data_list), hide_index=True, use_container_width=True)
                                else:
                                    st.warning("키워드와 일치하는 데이터가 없습니다.")
                            else:
                                st.warning("조회된 정보가 없습니다.")
                    else:
                        st.error(f"서버 응답 오류 (Status: {res.status_code})")
                except Exception as e:
                    st.error(f"연결 오류: {str(e)}")

# --- [Tab 4] 화물통관진행정보 (고정) ---
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

# --- [Tab 5] 세액계산기 (레이아웃 최적화 및 A vs C 비교 로직) ---
with tabs[4]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.write("**📍 1. 과세가격(CIF) 및 품목 입력**")
        
        # 레이아웃 구성을 위한 컬럼 분리
        col_left, col_right = st.columns(2)
        
        # 오른쪽 열 로직을 먼저 처리 (HS코드 입력에 따른 적용세율 결정을 위해)
        with col_right:
            # 1. 오른쪽 상단: 적용환율
            exchange_rate = st.number_input("적용 환율", min_value=1.0, value=1350.0, key="calc_ex_rate")
            
            # 2. 오른쪽 중간: 품목분류 (HS코드 10자리)
            input_hs = st.text_input("품목분류 (HS코드 10자리)", placeholder="예: 0101211000", key="calc_hs_code")
            
            # --- HS코드 연동 및 A vs C 세율 비교 로직 ---
            auto_duty_rate = 8.0  # 기본값
            if input_hs:
                hsk_clean = re.sub(r'[^0-9]', '', input_hs).zfill(10)
                conn = sqlite3.connect("customs_master.db")
                # A세율(기본)과 C세율(WTO)을 모두 조회
                rate_df = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{hsk_clean}' AND type IN ('A', 'C')", conn)
                conn.close()
                
                if not rate_df.empty:
                    try:
                        # 숫자형 변환
                        rate_df['rate'] = rate_df['rate'].astype(float)
                        a_val = rate_df[rate_df['type'] == 'A']['rate'].min()
                        c_val = rate_df[rate_df['type'] == 'C']['rate'].min()
                        
                        # A와 C 중 낮은 세율 선택 로직
                        if pd.notnull(a_val) and pd.notnull(c_val):
                            auto_duty_rate = min(a_val, c_val)
                        elif pd.notnull(a_val):
                            auto_duty_rate = a_val
                        elif pd.notnull(c_val):
                            auto_duty_rate = c_val
                    except:
                        pass
            
            # 3. 오른쪽 하단: 적용세율 (자동 계산된 값이 기본값으로 들어감)
            applied_duty_rate = st.number_input("적용세율 (%)", min_value=0.0, value=auto_duty_rate, key="calc_duty_rate")

        # 왼쪽 열 구성
        with col_left:
            # 1. 왼쪽 상단: 물품가격
            item_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0, key="calc_item_price")
            
            # 2. 왼쪽 중간: 운임
            freight = st.number_input("운임 (Freight, KRW)", min_value=0, value=0, key="calc_freight")
            
            # 3. 왼쪽 하단: 보험료
            insurance = st.number_input("보험료 (Insurance, KRW)", min_value=0, value=0, key="calc_insurance")

        # 과세가격(CIF) 합계 표시
        cif_krw = int((item_price * exchange_rate) + freight + insurance)
        st.info(f"**과세표준 (CIF KRW): {cif_krw:,.0f} 원**")

    # 2. 기타 세종 세율 설정 (순서 조정을 위한 준비)
    with st.expander("📍 2. 기타 세율 설정"):
        c1, c2, c3 = st.columns(3)
        with c1:
            v_rate = st.number_input("부가세율 (%)", min_value=0.0, value=10.0)
        with c2:
            excise_rate = st.number_input("개별소비세율 (%)", min_value=0.0, value=0.0)
            liquor_rate = st.number_input("주세율 (%)", min_value=0.0, value=0.0)
        with c3:
            edu_rate = st.number_input("교육세율 (%)", min_value=0.0, value=0.0)
            rural_rate = st.number_input("농특세율 (%)", min_value=0.0, value=0.0)

    # 3. 계산 실행 및 결과 출력 (요청하신 순서 반영)
    if st.button("세액 계산 실행", use_container_width=True):
        # 관세
        tax_duty = int(cif_krw * (applied_duty_rate / 100))
        # 개별소비세
        tax_excise = int((cif_krw + tax_duty) * (excise_rate / 100))
        # 주세
        tax_liquor = int((cif_krw + tax_duty) * (liquor_rate / 100))
        # 교육세 (개소세 또는 주세 기준)
        tax_edu = int((tax_excise + tax_liquor) * (edu_rate / 100))
        # 농특세
        tax_rural = int((tax_duty + tax_excise) * (rural_rate / 100))
        # 부가가치세 (모든 세종 합산액 기준)
        vat_base = cif_krw + tax_duty + tax_excise + tax_liquor + tax_edu + tax_rural
        tax_vat = int(vat_base * (v_rate / 100))
        
        total_tax = tax_duty + tax_vat + tax_excise + tax_liquor + tax_edu + tax_rural

        st.success("### 📊 세액 산출 결과")
        # 요청 순서: 관세, 부가세, 개소세, 주세, 교육세, 농특세
        res_df = pd.DataFrame({
            "세종": ["관세", "부가가치세", "개별소비세", "주세", "교육세", "농어촌특별세"],
            "세액 (원)": [tax_duty, tax_vat, tax_excise, tax_liquor, tax_edu, tax_rural]
        })
        st.table(res_df.style.format({"세액 (원)": "{:,.0f}"}))
        st.metric("💰 총 납부세액 합계", f"{total_tax:,.0f} 원")

# --- [Tab 6] 관리자 (고정: 탭3 DB관리 로직은 자동 비활성화됨) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 관리자 데이터 센터")
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
                        conn.close(); st.success("성공")
                    except Exception as e: st.error(f"오류: {e}")

# 하단 푸터 (고정)
st.divider(); c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")