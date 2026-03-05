import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io
import requests  # 서버와 통신하기 위해 추가
import xml.etree.ElementTree as ET  # XML 데이터를 해석하기 위해 추가

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
    c.execute("CREATE TABLE IF NOT EXISTS stat_codes (category TEXT, code TEXT, name TEXT)")
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

# --- 2. 통계부호 목록 (내국세면세부호 추가 완료) ---
STAT_LIST = [
    "BL구분코드", "BL분할사유코드", "BL유형코드", "CIQ수속장소구분코드", "COB화물검사결과코드", "COB화물변경사유코드",
    "CY_CFS구분코드", "FIU금융기관코드", "FTA원산지결정기준코드", "IMDG위험물구분코드", "가격신고항목코드", "가격조건코드",
    "가산세면제사유코드", "가족관계코드", "간이수출검사결과코드", "감시분석대상구분코드", "개장검사내역처리상태코드",
    "개장검사물품확인결과코드", "거래근거문서구분코드", "거주상태코드", "건설기계등록기관코드", "건설기계업무코드",
    "건설기계차종코드", "검사검역기관코드", "검사검역소속기관코드", "검사검역지정유형코드", "검사대상비지정사유코드",
    "검사대상해제사유코드", "검사방법코드", "검색기검사처리상태코드", "결손처분사유코드", "결제구분코드", "결제방법코드",
    "경제권종류코드", "계코드", "고발사유코드", "고발의견코드", "고발처분코드", "고지유형코드", "과다환급추징유형코드",
    "과징금코드", "과코드", "관계기관코드", "관내입항지구분코드", "관리대상화물검사결과코드", "관리대상화물검사구분코드",
    "관리대상화물수작업선별사유코드", "관리대상화물조치결과코드", "관리대상화물중량초과구분코드", "관리대상화물해제사유코드",
    "관세감면분납코드", "관세사거래관계기재구분코드", "관세사검사의견기재구분코드", "관세사별제재사유코드", "관세사표창구분코드",
    "관세사품명규격기재구분코드", "관세율구분코드", "관세청관련기관코드", "관세청업종코드", "교육세과세구분코드", "국가기관구분코드",
    "국가코드", "국세청법인구분코드", "국세청법인성격코드", "국세청업종코드", "국코드", "귀책사유코드", "근무반구분코드",
    "까르네물품용도코드", "남북교역구분코드", "남북통행정정항목코드", "납기연장사유코드", "내국물품반출입정정항목코드",
    "내국세구분코드", "내국세면세부호", "내국세세종코드", "농특세과세구분코드", "담당자변경사유코드", "담보업체변경사유코드", 
    "담보업체취소사유코드", "담보제공사유코드", "담보종류코드", "대륙종류코드", "대상업체구분코드", "동향구분코드", "동향유형코드", 
    "마약물품종류코드", "마약약리작용구분코드", "마약은닉장소코드", "마약의약용도구분코드", "마약적발경위구분코드", 
    "마약적발관련자처리상태코드", "마약적발외부기관코드", "마약조직원역할코드", "마약종류코드", "마약코드", 
    "마약투여방법코드", "마약형태코드", "말소구분코드", "물품반입구분코드", "물품용도코드", "물품용역업체항공영업종류코드", 
    "물품용역업체해상영업종류코드", "물품폐기사유코드", "미가산사유코드", "밀수근원코드", "밀수신고접수방법코드", 
    "반입경로코드", "반입유형코드", "반출기간연장구분코드", "반출사유코드", "반출유형코드", "반출입외화용도구분코드", 
    "발각원인코드", "범칙물품상표코드", "범칙물품유형코드", "범칙상세경로코드", "범칙수단코드", "범행동기코드", "법령종류코드", 
    "법령코드", "법무부출입국도시코드", "법조문구분코드", "병역구분코드", "보세구역구분코드", "보세구역반출입정정항목코드", 
    "보세구역반출입화물종류코드", "보세구역부호", "보세운송검사구분코드", "보세운송검사대상구분코드", "보세운송검사지정상태코드", 
    "보세운송검사처리상태코드", "보세운송승인신청담보구분코드", "보세운송승인신청사유코드", "보수작업형태코드", 
    "보정심사생략구분코드", "보정심사수작업선별사유코드", "보정심사처리상태코드", "봉인내역코드", "봉인지정내역처리상태코드", 
    "부가세과세구분코드", "분석기관구분코드", "분할반출입구분코드", "분할통합사유코드", "비위유형코드", "사건근거구분코드", 
    "사업자구분코드", "사업종류코드", "사이트유형코드", "사전세액심사선별기준코드", "사후관리방법코드", "사후관리비대상사유코드", 
    "사후관리조치결과코드", "사후관리조치상태코드", "사후관리종결일자구분코드", "사후관리확인결과코드", "사후관리확인방법코드", 
    "산업단지코드", "상이내역코드", "상표코드", "서류제출변경사유코드", "선기용품적재물품구분코드", "선박일제점검결과코드", 
    "선박종류코드", "선별검사종류코드", "선별사유코드", "선별종류코드", "선원구분코드", "성별코드", "세관구분코드", "세관부호", 
    "세관장확인대상법령코드", "세관처분유형코드", "세외수입위반유형코드", "소요량산정방법코드", "수리전반출승인사유코드", 
    "수리전반출취소사유코드", "수사지휘구분코드", "수입각하사유코드", "수입거래구분코드", "수입검사결과코드", "수입검사구분코드", 
    "수입검사변경사유코드", "수입검사변경코드", "수입검사생략사유코드", "수입귀책사유코드", "수입보완요구사유코드", 
    "수입성질코드", "수입신고구분코드", "수입신고정정사유코드", "수입자구분코드", "수입전산선별사유코드", "수입정정항목코드", 
    "수입조건변경구분코드", "수입조치사항코드", "수입종류코드", "수입취하사유코드", "수입통관계획코드", "수입통관미결사유코드", 
    "수입통관처리상태코드", "수작업선별사유코드", "수작업수납등록사유코드", "수출거래구분코드", "수출검사결과조치코드", 
    "수출검사결과코드", "수출검사구분코드", "수출검사변경사유코드", "수출귀책사유코드", "수출반송사유코드", "수출보완요구사유코드", 
    "수출성질코드", "수출신고각하사유코드", "수출신고구분코드", "수출신고정정사유코드", "수출신고제출서류구분코드", 
    "수출신고처리상태코드", "수출신고취하사유코드", "수출신고항목코드", "수출입신고각하사유코드", "수출자구분코드", 
    "수출접수결과구분코드", "수출종류코드", "수출형태구분코드", "수출형태코드", "신고구분코드", "신고업체페이퍼리스제재사유코드", 
    "신고인부호", "신병조치결과코드", "신청방법코드", "신청서처리상태코드", "신청인구분코드", "심사근거번호구분코드", 
    "심사의견구분코드", "압수물품처분유형코드", "업무영역코드", "업체평가등급코드", "여권발급지역코드", "여행목적코드", 
    "여행자수작업선별사유코드", "여행자우범등급코드", "요건승인기관코드", "요청정보대상구분코드", "용도구분코드", "우범등급코드", 
    "우범사이트추적근원구분코드", "우범사이트품명코드", "우편물기타폐기사유코드", "우편물면세사유코드", "우편물반송사유코드", 
    "우편물종류코드", "우편물통관유의코드", "우편물폐기사유코드", "운송사업종류코드", "운송수단유형코드", "운송수단임차신청사유코드", 
    "운송용기구분코드", "운항계획정정사유코드", "원산지결정기준코드", "원산지증명발급구분코드", "원산지증명서유무구분코드", 
    "원산지표시면제사유코드", "원산지표시방법코드", "원산지표시유무구분코드", "원재료구분코드", "위반유형코드", 
    "위해물품반출입사유코드", "위해물품조치결과코드", "위해물품종류코드", "은닉수법코드", "의무이행요구사유코드", "이사자직업코드", 
    "이체대사결과코드", "인도조건코드", "인증수출자반려취소사유코드", "인증수출자시정보정사유코드", "일제점검선정사유코드", 
    "입출항구분코드", "입출항서류정정항목코드", "입출항정정사유코드", "입출항화물코드", "입항목적코드", "입항적하목록정정항목코드", 
    "자격전환정정사유코드", "자격증종류코드", "자격취득구분코드", "자금원천구분코드", "자동차등록기관코드", "자동차업무코드", 
    "자동차차종코드", "자료제공거부코드", "재수출이행의무종결사유코드", "적발근거코드", "적발기관코드", "적발기법코드", 
    "적발단서코드", "적발유형코드", "적발장소코드", "적발항목코드", "적하목록미제출조치사항코드", "적하목록상이내역코드", 
    "적하목록정정사유코드", "점검조치결과코드", "정보분석대상품목코드", "정보분석등급코드", "정보입수구분코드", "제재유형코드", 
    "조사대상신고번호구분코드", "조사대상업무구분코드", "조사란구분코드", "조사직원교육코드", "조사직원전문분야코드", 
    "조사해제사유코드", "주소변동사유코드", "중량수량단위코드", "중요품목코드", "즉시반출대상품목구분코드", "지인관계코드", 
    "직권정산대상업체사유코드", "직급코드", "직렬코드", "직무보조자구분코드", "직업분류코드", "직업코드", "직원징계종류코드", 
    "직위코드", "징수형태코드", "차량색상코드", "차량용도코드", "체납발생사유코드", "체화공매불출구분코드", "체화해제사유코드", 
    "추가추징납부사유코드", "추가환급사유코드", "추징고지상세사유코드", "추징기관구분코드", "추징발생원인구분코드", "추징사유코드", 
    "출항적하목록정정항목코드", "컨테이너검색기위치코드", "컨테이너길이코드", "컨테이너너비높이코드", "컨테이너종류코드", 
    "통계용선박용도종류코드", "통관고유부호사용정지사유코드", "통관고유부호사용정지해제사유코드", "통관목록검사결과코드", 
    "통관보류사유코드", "통관보류조치코드", "통관우체국코드", "통화코드", "투시결과코드", "특송업체부호", "평가대상업체업종코드", 
    "포상종류코드", "포장종류코드", "피의자관계코드", "하선물품구분코드", "학력코드", "한베트남FTA수량단위코드", 
    "한베트남FTA중량단위코드", "한베트남FTA포장종류코드", "한인니FTA수량단위코드", "한인니FTA중량단위코드", "한인니FTA포장종류코드", 
    "항공기자격정정코드", "항공기종류코드", "항공입항정정항목코드", "항구공항코드", "항해구분코드", "항해입항정정항목코드", 
    "해상항공구분코드", "행정제재유형코드", "허가기관구분코드", "허가수리구분코드", "현장면세배제코드", "혐의자구분코드", 
    "협정구분코드", "혼인관계코드", "화물검사조치결과코드", "화물구분코드", "화물선별구분코드", "화물특성구분코드", 
    "확인적발경위코드", "환급근거서류구분코드", "환급대상정정취하사유코드", "환급대상확인신청서기각사유코드", 
    "환급사후심사착수구분코드", "환급사후심사착수방안구분코드", "환급신청인구분코드", "환급위험도항목구분코드", 
    "환급제증명오류코드", "환급종류코드", "회사구분코드", "휴대품가격평가방법코드", "휴대품검사결과코드", "휴대품검사사유코드", 
    "휴대품면세조항코드", "휴대품세율적용구분코드", "휴대품품명코드", "휴무구분코드", "휴업폐업사유코드"
]

# --- 3. 로그인 및 세션 관리 ---
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

# --- 4. 메인 탭 구성 ---
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
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM req_import WHERE hs_code = '{code_clean}'", conn)
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

# --- [Tab 2] HS정보 (12px, 0보정 조회) ---
with tabs[1]:
    st.markdown("<style>.custom-text { font-size: 15px !important; } .custom-value { font-size: 12px !important; background-color: #F8FAFC; padding: 4px; border-radius: 4px; }</style>", unsafe_allow_html=True)
    target_hs = st.text_input("조회할 HSK 10자리 (0 포함)", key="hs_info_input", placeholder="예: 0101211000")
    if st.button("데이터 통합 조회", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs).zfill(10)
            conn = sqlite3.connect("customs_master.db")
            m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
            std = pd.read_sql(f"SELECT * FROM standard_names WHERE hs_code = '{hsk}'", conn)
            r = pd.read_sql(f"SELECT r.type as '세율코드', n.h_name as '세율명칭', r.rate as '세율' FROM rates r LEFT JOIN rate_names n ON r.type = n.code WHERE r.hs_code = '{hsk}'", conn)
            req_i = pd.read_sql(f"SELECT law, agency, document FROM req_import WHERE hs_code = '{hsk}'", conn)
            req_e = pd.read_sql(f"SELECT law, agency, document FROM req_export WHERE hs_code = '{hsk}'", conn)
            conn.close()
            if not m.empty:
                st.markdown(f"#### 📋 HS {hsk} 상세 정보")
                c1, c2 = st.columns(2)
                with c1: st.markdown(f"**[기본 품명]**\n<div class='custom-value'>국문: {m['name_kr'].values[0]}<br>영문: {m['name_en'].values[0]}</div>", unsafe_allow_html=True)
                with c2: st.markdown(f"**[표준 품명]**", unsafe_allow_html=True)
                if not std.empty: st.markdown(f"<div class='custom-value'>품명(B): {std['base_name'].values[0]}<br>표준(E): {std['std_name_kr'].values[0]}</div>", unsafe_allow_html=True)
                if not r.empty:
                    r['세율'] = r['세율'].astype(str) + "%"
                    st.write("**💰 관세율 정보**"); st.dataframe(r.style.set_properties(**{'text-align': 'center'}), hide_index=True, use_container_width=True)
                st.write("**🛡️ 세관장확인**"); col_i, col_e = st.columns(2)
                with col_i: st.write("수입"); st.table(req_i)
                with col_e: st.write("수출"); st.table(req_e)
            else: st.error("정보가 없습니다.")

# --- [Tab 3] 통계부호 (자동완성 & 유연검색 보강) ---
with tabs[2]:
    st.subheader("📊 통계부호 통합 검색")
    target_cat = st.selectbox("검색할 카테고리 입력/선택", STAT_LIST, help="목록에서 찾거나 직접 입력하여 검색하세요.")
    search_kw = st.text_input("키워드 검색 (한글내역)", placeholder="검색할 명칭 입력 (예: 부칙7조)")
    if st.button("부호 조회", use_container_width=True):
        if search_kw:
            clean_kw = f"%{search_kw.replace(' ', '%')}%"
            conn = sqlite3.connect("customs_master.db")
            query = "SELECT code as '통계코드', name as '한글내역' FROM stat_codes WHERE category = ? AND name LIKE ?"
            res = pd.read_sql(query, conn, params=(target_cat, clean_kw))
            conn.close()
            if not res.empty:
                st.markdown(f"**🔍 '{target_cat}' 검색 결과**")
                st.dataframe(res.style.set_properties(**{'text-align': 'center', 'font-size': '12px'}), hide_index=True, use_container_width=True)
            else: st.warning(f"'{target_cat}' 카테고리에 '{search_kw}'를 포함하는 명칭이 없습니다.")

import requests
import xml.etree.ElementTree as ET

# --- [Tab 4] 화물통관진행정보 (실제 XML 결과 기반 최종 보정) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    
    if not CR_API_KEY:
        st.error("⚠️ Streamlit Secrets에 'UNIPASS_API_KEY'가 설정되지 않았습니다.")
        st.stop()

    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1:
        carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2:
        bl_no = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL 번호", key="bl_final_v3")
    with col3:
        st.write("") 
        search_btn = st.button("실시간 조회", use_container_width=True)

    if search_btn:
        if not bl_no:
            st.warning("B/L 번호를 입력해 주세요.")
        else:
            with st.spinner("관세청 유니패스에서 데이터를 가져오는 중..."):
                # 실제 테스트 성공하신 URL 적용
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                
                params = {
                    "crkyCn": CR_API_KEY,
                    "blYy": str(carg_year),
                    "hblNo": bl_no.strip().upper()
                }
                
                try:
                    # 타임아웃을 30초로 넉넉히 설정
                    response = requests.get(url, params=params, timeout=30)
                    
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        
                        # tCnt: 결과 건수 확인
                        t_cnt = root.findtext(".//tCnt")
                        
                        if t_cnt and int(t_cnt) > 0:
                            # 1. 일반 정보 (cargCsclPrgsInfoQryVo)
                            info = root.find(".//cargCsclPrgsInfoQryVo")
                            
                            # 실제 XML 태그인 prgsStts(반출완료 등)와 csclPrgsStts(수입신고수리 등) 활용
                            current_status = info.findtext('prgsStts') # 현재 진행 상태
                            st.success(f"✅ 화물 확인됨: {current_status}")
                            
                            m1, m2, m3 = st.columns(3)
                            m1.metric("진행상태", current_status)
                            m2.metric("품명", info.findtext("prnm")[:12] if info.findtext("prnm") else "-")
                            m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")

                            # 상세 요약 (12px)
                            st.markdown("---")
                            st.markdown(f"""
                            <div class='custom-text'>
                            <b>• 선박/항공기명:</b> {info.findtext('shipNm')}<br>
                            <b>• 입항일자:</b> {info.findtext('etprDt')}<br>
                            <b>• 현재위치:</b> {info.findtext('shcoFlco')}<br>
                            <b>• MBL 번호:</b> {info.findtext('mblNo')}
                            </div>
                            """, unsafe_allow_html=True)

                            # 2. 상세 이력 (cargCsclPrgsInfoDtlQryVo)
                            st.markdown("#### 🕒 처리 단계별 상세 이력")
                            history = []
                            for item in root.findall(".//cargCsclPrgsInfoDtlQryVo"):
                                history.append({
                                    "처리단계": item.findtext("cargTrcnRelaBsopTpcd"),
                                    "처리일시": item.findtext("prcsDttm"),
                                    "장치장/내용": item.findtext("shedNm") if item.findtext("shedNm") else item.findtext("rlbrCn"),
                                    "포장개수": f"{item.findtext('pckGcnt')} {item.findtext('pckUt')}"
                                })
                            
                            df_hist = pd.DataFrame(history)
                            st.dataframe(
                                df_hist.style.set_properties(**{'text-align': 'center', 'font-size': '12px'}),
                                hide_index=True, use_container_width=True
                            )
                        else:
                            st.warning("조회된 정보가 없습니다. 번호나 연도를 확인하세요.")
                    else:
                        st.error(f"❌ 접속 오류 (Status: {response.status_code})")
                except Exception as e:
                    st.error(f"⚠️ 연결 실패: {str(e)}")
                    st.info("사내 네트워크 차단이 의심됩니다. 모바일 핫스팟으로 연결 후 다시 시도해 보세요.")

# --- [Tab 6] 관리자 (일괄 업로드 열 매핑 보정) ---
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
                        df = pd.read_csv(up, encoding='utf-8-sig')
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
                        conn.close(); st.success("성공")
                    except Exception as e: st.error(f"오류: {e}")

        st.divider()
        st.subheader("📊 2. 통계부호 일괄 관리")
        multi_files = st.file_uploader("CSV 파일 드래그 (파일명=카테고리명)", type="csv", accept_multiple_files=True)
        if multi_files and st.button("🚀 일괄 업로드 실행", use_container_width=True):
            conn = sqlite3.connect("customs_master.db")
            total = 0
            for f in multi_files:
                cat = f.name.split('.')[0]
                if cat in STAT_LIST:
                    try:
                        try: df = pd.read_csv(f, encoding='utf-8-sig')
                        except: df = pd.read_csv(f, encoding='cp949')
                        # 관세청 구조: No(0), 코드(1), 명칭(2) -> [1, 2] 열 추출
                        df_stat = df.iloc[:, [1, 2]].copy()
                        df_stat.columns = ['code', 'name']
                        df_stat['category'] = cat
                        conn.execute("DELETE FROM stat_codes WHERE category = ?", (cat,))
                        df_stat.to_sql('stat_codes', conn, if_exists='append', index=False)
                        total += 1
                    except Exception as e: st.error(f"{cat} 오류: {e}")
            conn.commit(); conn.close(); st.success(f"완료: {total}개")

# 하단 상담 채널
st.divider(); c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")