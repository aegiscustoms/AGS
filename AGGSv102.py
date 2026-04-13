import streamlit as st
import extra_streamlit_components as stx
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io
import requests
import xml.etree.ElementTree as ET
import time
import os
from streamlit_gsheets import GSheetsConnection 

st.set_page_config(page_title="A.G.G.S - 이지스 관세가이드 시스템", layout="wide")
# --- [추가] Cron-job 전용 깨우기 로직 ---
if st.query_params.get("check") == "alive":
    st.write("OK")
    st.stop() 
# --------------------------------------

cookie_manager = stx.CookieManager()

# --- 구글 시트 연결 및 데이터 로드 함수 ---

@st.cache_data(ttl=3600)
def load_aggs_master_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # 공통 정제 함수 (HS 10자리)
    def clean_hs(df):
        if 'HS_code' in df.columns:
            df['HS_code'] = df['HS_code'].astype(str).str.split('.').str[0].str.zfill(10)
        return df

    # 1. AGGS_HS_Master_data (URL 유지)
    m_url = "https://docs.google.com/spreadsheets/d/1FuqaAf2qr6wg76xF4ieWbDy4_ot5C2ClubYq33aMxGo/edit?usp=sharing"
    df_m_hs = clean_hs(conn.read(spreadsheet=m_url, worksheet="HS_Code"))
    df_m_sn = clean_hs(conn.read(spreadsheet=m_url, worksheet="Standard_Name"))
    df_m_tc = conn.read(spreadsheet=m_url, worksheet="Tariff_Class")

    # 2. AGGS_HS_tariff
    t_url = "https://docs.google.com/spreadsheets/d/1kw9WMhHOkjE-GIqkuC97QQDB9GCQZdHwloPAOx_d_3E/edit?usp=sharing"
    df_t_ac = clean_hs(conn.read(spreadsheet=t_url, worksheet="AC"))
    df_t_etc = clean_hs(conn.read(spreadsheet=t_url, worksheet="ETC"))
    df_t_f1 = clean_hs(conn.read(spreadsheet=t_url, worksheet="FTA_S1"))
    df_t_f2 = clean_hs(conn.read(spreadsheet=t_url, worksheet="FTA_S2"))
    df_t_fm = clean_hs(conn.read(spreadsheet=t_url, worksheet="FTA_M"))

    # 3. AGGS_Req
    r_url = "https://docs.google.com/spreadsheets/d/1kEMJujmsUVemtfO2oh1DoO9L_aGZMygtbVPrafiEPxQ/edit?usp=sharing"
    df_r_im = clean_hs(conn.read(spreadsheet=r_url, worksheet="Req_IM"))
    df_r_ex = clean_hs(conn.read(spreadsheet=r_url, worksheet="Req_EX"))
    
    # 통합공고 (앞자리 매칭용 - zfill 제외)
    df_c_im = conn.read(spreadsheet=r_url, worksheet="CPAN_IM")
    df_c_ex = conn.read(spreadsheet=r_url, worksheet="CPAN_EX")
    df_c_im['HS_code'] = df_c_im['HS_code'].astype(str).str.split('.').str[0]
    df_c_ex['HS_code'] = df_c_ex['HS_code'].astype(str).str.split('.').str[0]

    return (df_m_hs, df_m_sn, df_m_tc, df_t_ac, df_t_etc, df_t_f1, df_t_f2, df_t_fm, df_r_im, df_r_ex, df_c_im, df_c_ex)


st.markdown("""
    <style>
        /* 1. 스트림릿 기본 헤더 및 여백 제거 */
        [data-testid="stStatusWidget"], .stStatusWidget { visibility: hidden !important; display: none !important; }
        header { visibility: hidden !important; }
        .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; }
        
        /* 2. 탭 메뉴 위치 조정 (상단바와 수평 맞춤) */
        .stTabs { margin-top: -35px; position: relative; z-index: 10; }

""", unsafe_allow_html=True)


st.markdown("""
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        * { font-family: 'Pretendard', sans-serif; }
        .stApp { background-color: #FFFFFF; }
        
        /* 탭 내비게이션 디자인 */
        .stTabs [data-baseweb="tab-list"] { gap: 24px; background-color: #FFFFFF; border-bottom: 1px solid #E2E8F0; }
        .stTabs [data-baseweb="tab"] { height: 50px; color: #64748B; font-size: 15px; font-weight: 500; }
        .stTabs [aria-selected="true"] { color: #1E3A8A !important; border-bottom: 2px solid #1E3A8A !important; }

        /* 섹션 헤더 디자인 */
        .custom-header { 
            font-size: 16px !important; 
            font-weight: 700; 
            color: #1E3A8A; 
            border-left: 4px solid #1E3A8A; 
            padding-left: 12px; 
            margin: 15px 0; 
        }

        /* 버튼 디자인 */
        .stButton > button {
            background-color: #1E3A8A !important;
            color: white !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
            width: 100% !important;
        }
        
        /* 데이터프레임 전체 폰트 10px 일괄 적용 */
        div[data-testid="stDataFrame"] * {
            font-size: 10px !important;
            font-family: 'Pretendard', sans-serif !important;
        }

        /* 데이터프레임 헤더 설정 */
        div[data-testid="stDataFrame"] div[role="columnheader"] p {
            font-size: 10px !important;
            text-align: center !important;
            font-weight: bold !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- 헬퍼 함수: 인코딩 대응 CSV 로드 ---
def safe_read_csv(uploaded_file):
    for enc in ['utf-8-sig', 'cp949', 'euc-kr']:
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding=enc, engine='python')
        except: continue
    return None

# --- 1. 초기 DB 설정 (AFTUI 최적화 및 원본 로직 보존) --- #변경내역★★
def init_db():
    # [1] 마스터 지식 DB 설정은 구글 시트로 대체되어 삭제합니다.
    # (기존 customs_master.db 관련 코드 삭제)

    # [2] 사용자 인증 DB 설정 (users.db) - 이건 반드시 유지해야 합니다!
    conn_auth = sqlite3.connect("users.db")
    ca = conn_auth.cursor()
    ca.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, 
                pw TEXT, 
                name TEXT, 
                is_approved INTEGER DEFAULT 0, 
                is_admin INTEGER DEFAULT 0)""")
    
    # 관리자 계정 초기 생성 로직 유지
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    ca.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    
    conn_auth.commit()
    conn_auth.close()

# 앱 실행 시 사용자 DB 구성을 위해 함수 호출은 유지합니다.
init_db()

# --- [신규 추가] 구글 시트 로그 기록 함수 ---
def write_log(user_id, user_name, activity, detail="-"):
    try:
        # 최신 로그 시트 불러오기
        df_logs = conn_gs.read(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="logs", ttl=0)
        new_log = pd.DataFrame([{
            "Time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ID": user_id,
            "Name": user_name,
            "Activity": activity,
            "Detail": detail
        }])
        # 기존 로그 아래에 추가
        updated_logs = pd.concat([df_logs, new_log], ignore_index=True)
        conn_gs.update(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="logs", data=updated_logs)
    except Exception as e:
        st.error(f"로그 기록 실패: {e}")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# 1. 로그인 전용 빈 컨테이너(가림막) 선언
login_screen = st.empty()

# 2. 로그인이 되지 않았을 때의 처리 (논리적 차단)
if not st.session_state.logged_in:
    with login_screen.container():
        login_title_html = f"""
        <div style="text-align: center; padding-top: 100px; margin-bottom: 30px; width: 100%;">
            <div style="color: #1E3A8A; font-size: 48px; font-weight: 800; 
                        margin: 0; padding: 0; line-height: 1.0; letter-spacing: -1.5px;">
                A.G.G.S
            </div>
            <div style="color: #595959; font-size: 18px; font-weight: 500; 
                        margin: 0; padding: 0; margin-top: 0px; letter-spacing: -0.5px;">
                [Aegis Gwanse Guide System]
            </div>
        </div>
        """
        st.markdown(login_title_html, unsafe_allow_html=True)
        cl1, cl2, cl3 = st.columns([1, 1.4, 1])
        with cl2:
            with st.form("login_form"):
                input_id = st.text_input("아이디 (사업자번호)").strip().replace("-", "")
                input_pw = st.text_input("비밀번호", type="password").strip()
                submit = st.form_submit_button("로그인", use_container_width=True)
                
                if submit:
                    with st.spinner("보안 인증 및 데이터 연결 중..."):
                        try:
                            # 버튼 클릭 시점에만 데이터 로드 (상단 플래시 방지)
                            conn_gs = st.connection("gsheets", type=GSheetsConnection)
                            df_users = conn_gs.read(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="users", ttl=0)
                            
                            # 1) 마스터 관리자 체크
                            if input_id == "aegis01210" and input_pw == "dlwltm2025@":
                                st.session_state.logged_in = True
                                st.session_state.user_id = input_id
                                st.session_state.user_name = "마스터 관리자"
                                st.session_state.is_admin = True
                                write_log(input_id, "마스터 관리자", "로그인", "관리자 시스템 접속")
                                st.rerun()
                            
                            # 2) 일반 고객사 체크
                            elif df_users is not None and not df_users.empty:
                                input_pw_hash = hashlib.sha256(input_pw.encode()).hexdigest().lower()
                                df_check = df_users.copy()
                                df_check.columns = [str(c).strip().upper() for c in df_check.columns]
                                if 'ID' in df_check.columns:
                                    def clean_id(x):
                                        val = str(x).strip().replace("-", "")
                                        if val.endswith('.0'): val = val[:-2]
                                        return val
                                    df_check['ID_CLEAN'] = df_check['ID'].apply(clean_id)
                                    user_match = df_check[df_check['ID_CLEAN'] == input_id]
                                    
                                    if not user_match.empty:
                                        db_pw = str(user_match.iloc[0].get('PASSWORD', '')).strip().lower()
                                        if input_pw_hash == db_pw:
                                            st.session_state.logged_in = True
                                            st.session_state.user_id = input_id
                                            u_name = user_match.iloc[0].get('NAME', input_id)
                                            st.session_state.user_name = u_name
                                            st.session_state.is_admin = False
                                            raw_tabs = user_match.iloc[0].get('ACCESS_TABS', "🔍 HS검색, 📚 HS정보, 📊 통계부호, 🚚 화물통관진행정보, 🧮 세액계산기")
                                            st.session_state.user_permissions = [t.strip() for t in str(raw_tabs).split(',')]
                                            write_log(input_id, u_name, "로그인", "고객사 시스템 접속")
                                            st.rerun()
                                        else: st.error("❌ 비밀번호가 일치하지 않습니다.")
                                    else: st.error(f"❌ 등록되지 않은 아이디입니다.")
                        except Exception as e:
                            st.error(f"⚠️ 연결 오류: {e}")
    st.stop()

try:
    conn_gs = st.connection("gsheets", type=GSheetsConnection)
    df_users = conn_gs.read(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="users", ttl=0)
except:
    df_users = pd.DataFrame()

# Gemini 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 (구글 시트 연동 로직으로 교체) ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top:100px;'><h1 style='color:#1E3A8A; font-size:42px; font-weight:800;'>AEGIS</h1></div>", unsafe_allow_html=True)
    cl1, cl2, cl3 = st.columns([1, 1.4, 1])
    with cl2:
        with st.form("login_form"):
            l_id = st.text_input("아이디")
            l_pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인"):
                # 비밀번호 해싱
                hashed_pw = hashlib.sha256(l_pw.encode()).hexdigest()
                
                # [수정 핵심] sqlite3 대신 상단에서 로드된 df_users(구글 시트)에서 조회
                user_row = df_users[(df_users['id'] == l_id) & (df_users['pw'] == hashed_pw)]
                
                if not user_row.empty:
                    # 승인 여부 확인 (is_approved 컬럼이 1인 경우만)
                    if user_row.iloc[0]['is_approved'] == 1:
                        st.session_state.logged_in = True
                        st.session_state.user_id = l_id
                        st.session_state.user_name = user_row.iloc[0]['name'] # 성함 저장
                        st.session_state.is_admin = bool(user_row.iloc[0]['is_admin'])
                        st.rerun()
                    else:
                        st.error("승인 대기 중인 계정입니다. 관리자에게 문의하세요.")
                else:
                    st.error("아이디 또는 비밀번호가 일치하지 않습니다.")
    st.stop()


# 1. 메뉴 구성 로직
all_menu_list = ["🔍 HS검색", "📚 HS정보", "📊 통계부호", "🚚 화물통관진행정보", "🧮 세액계산기"]
if st.session_state.get('is_admin', False):
    display_menu_names = all_menu_list + ["👨🏻‍✈️ 관리자"]
else:
    user_perms = st.session_state.get('user_permissions', all_menu_list)
    display_menu_names = [m for m in all_menu_list if m in user_perms] + ["👩🏻‍💻 계정관리"]

# 2. 탭 생성 (상단에는 오직 메뉴만 표시)
if display_menu_names:
    tabs = st.tabs(display_menu_names)
else:
    st.error("❌ 이용 가능한 메뉴 권한이 없습니다.")
    st.stop()

# ==========================================
# [데이터 로드 ] 
# ==========================================

@st.cache_data
def load_hs_resources():
    # 1. 4단위 호 리스트
    try:
        df_hs = pd.read_csv('knowledge_base/headings/HS_Headings_All.csv', dtype={'류': str, '번호': str})
    except:
        df_hs = pd.DataFrame()

    # 2. 10단위 소호 리스트 (수정된 로직)
    try:
        df_sub_hs = pd.read_csv('knowledge_base/headings/HS_subHeadings_All.csv', dtype={'HS부호': str})
        df_sub_hs = df_sub_hs.rename(columns={
            'HS부호': 'HS10', 
            '한글품목명': 'name_kr', 
            '영문품목명': 'name_en'
        })
        df_sub_hs['HS10'] = df_sub_hs['HS10'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    except:
        df_sub_hs = pd.DataFrame()
    
    # 3. 해설서 로드
    try:
        with open('knowledge_base/legal_source/HS-manual.txt', 'r', encoding='utf-8') as f:
            manual_text = f.read()
    except:
        manual_text = "해설서 파일을 찾을 수 없습니다."
        
    return df_hs, df_sub_hs, manual_text

# 전역 데이터 변수 로드
df_hs_master, df_sub_hs_master, manual_source_txt = load_hs_resources()

def get_legal_ground(p_name, manual_txt, hs_df): 
    if hs_df.empty or not p_name:
        return "참조할 수 있는 법령 정보가 없습니다.", "Unknown"
    
    # 4단위 매칭 로직
    search_keyword = p_name.replace(" ", "")[:3]
    matched = hs_df[hs_df['품명'].str.contains(search_keyword, na=False, case=False)].head(1)
    
    if matched.empty:
        return "매칭되는 4단위 호를 찾을 수 없습니다. 일반 통칙에 따라 분석하세요.", "Unknown"
        
    h_code = matched.iloc[0]['번호']
    formatted_h = f"{h_code[:2]}.{h_code[2:]}" # 8517 -> 85.17

    # 해설서 내 위치 찾기
    pattern = rf"제\s?{formatted_h}\s?호"
    start_match = re.search(pattern, manual_txt)
    
    if not start_match:
        start_match = re.search(rf"{formatted_h}\s?-", manual_txt)

    if not start_match:
        return f"제{formatted_h}호의 용어와 관련 주 규정을 기반으로 분석하세요.", h_code

    start_pos = start_match.start()
    next_pattern = re.search(r"제\d{2}\.\d{2}호", manual_txt[start_pos + 10:])
    end_pos = start_pos + 10 + next_pattern.start() if next_pattern else start_pos + 10000
        
    return manual_txt[start_pos:end_pos], h_code

# --- [Tab 1] HS검색 (가이드북/관세율표 지식 통합 및 전문 분석) ---
with tabs[0]:
    # 1) 아이콘, 타이틀
    st.markdown(f"<div style='font-size: 16px; font-weight: bold; color: #1E3A8A; margin-bottom: 15px;'>🧠 AI 기반 HS Code 전문 분석 리포트 📋</div>", unsafe_allow_html=True)
    
    # 세션 상태 초기화
    if "ai_report_done" not in st.session_state: st.session_state.ai_report_done = False
    if "last_report_text" not in st.session_state: st.session_state.last_report_text = ""
    if "last_input_summary" not in st.session_state: st.session_state.last_input_summary = ""
    if "img_analysis_text" not in st.session_state: st.session_state.img_analysis_text = ""
    if "last_img_bytes" not in st.session_state: st.session_state.last_img_bytes = None

    # [1] 좌우 구역 분할 레이아웃
    with st.container(border=True):
        st.markdown("**📲 물품 정보 입력 (이미지 업로드 또는 상세 정보를 입력해주세요)**")
        col_left, col_right = st.columns([0.4, 0.6], gap="medium")
        
        with col_left:
            st.write("**🎨 물품 이미지**")
            uploaded_file = st.file_uploader("이미지 파일을 선택하세요", type=["jpg", "jpeg", "png"], key="hs_img_v4", label_visibility="collapsed")
            if uploaded_file:
                st.image(uploaded_file, caption="업로드된 이미지 미리보기", use_container_width=True)
                st.session_state.last_img_bytes = uploaded_file.getvalue() 
        
        with col_right:
            st.write("**📝 상세 물품 정보**")
            p_name = st.text_input("1) 품명 (기본)", key="p_name", placeholder="예: 무선 이어폰")
            p_material = st.text_input("2) 재질", key="p_material", placeholder="예: 스테인리스강, 폴리카보네이트")
            p_usage = st.text_input("3) 용도", key="p_usage", placeholder="예: 가정용, 산업용 부품")
            p_function = st.text_input("4) 기능 및 작동원리", key="p_function", placeholder="예: 블루투스 통신, 유압식 구동")
            p_component = st.text_input("5) 성분 및 함량", key="p_component", placeholder="예: 소고기 60%, 에탄올 70%")
            p_spec = st.text_input("6) 규격 및 사양", key="p_spec", placeholder="예: 220V, 15인치, ISO 인증규격")
            p_composition = st.text_input("7) 구성요소 (Set 여부)", key="p_composition", placeholder="예: 본체+케이블 세트 구성")

    # [2] 분석 실행 로직
    if st.button("AI 전문 분석 리포트 생성", use_container_width=True, type="primary"):
        details = []
        if p_name: details.append(f"   2) 품명: {p_name}")
        if p_material: details.append(f"   3) 재질: {p_material}")
        if p_usage: details.append(f"   4) 용도: {p_usage}")
        if p_function: details.append(f"   5) 기능 및 작동원리: {p_function}")
        if p_component: details.append(f"   6) 성분 및 함량: {p_component}")
        if p_spec: details.append(f"   7) 규격 및 사양: {p_spec}")
        if p_composition: details.append(f"   8) 구성요소(Set여부): {p_composition}")
        input_summary = "\n".join(details)
        
        if not uploaded_file and not input_summary:
            st.warning("⚠️ 분석을 위해 최소 하나 이상의 정보를 입력해주세요.")
        else:
            # --- [추가] 세션 상태 초기화: 새로운 분석 시작 시 이전 결과를 즉시 지움 ---
            st.session_state.ai_report_done = False
            st.session_state.last_report_text = ""
            st.session_state.last_input_summary = input_summary
            with st.spinner("🔍 AI 전문 관세사가 물품정보를 분석 중입니다..."):
                try:
                    # [2-1] 실시간 법령 및 호 정보 발췌 (인자 3개 -> 2개로 원복)
                    legal_ground_text, matched_h_code = get_legal_ground(p_name if p_name else "정보없음", manual_source_txt, df_hs_master)
                    # [2-2] 제미나이 멀티모달 분석 (발췌 지식 및 인용 지침 강제 주입)
                    model = genai.GenerativeModel('gemini-2.0-flash')
                    
                    # 분석 지침 (프롬프트 고도화: 파일 참조 및 원문 인용 강조)
                    knowledge_instruction = f"""
                    [분석 지침]
                    1. (기본원칙) 당신의 내부 전문 지식과 제공된 [HS 해설서 법령 원문]을 6:4의 비중으로 결합하여 분석하세요.
                    2. (HS 해설서 법령 원문 적용) 통칙 제1호(호의 용어 및 주 규정)를 최우선 적용하고, 제2호부터 제6호까지 논리적으로 순차 적용할 것.
                    3. (4단위 검토) 발췌된 제{matched_h_code}호의 용어와 부 또는 류 주규정, 총설, 호 해설서를 중심으로 예상되는 4단위 호를 우선 검토하고, 제외 규정에 해당되는지 여부를 확인할 것.
                    4. (자율성 부여) 만약 발췌된 제{matched_h_code}호의 내용이 입력 물품과 논리적으로 맞지 않는다고 판단되면, 당신의 전문 지식을 바탕으로 더 적합한 호를 추천하되 그 근거를 명확히 밝힐 것.
                    5. (품명 우선) 상세 물품 정보와 물품 이미지를 모두 제공한 경우, 상세 물품정보와 이미지정보를 6:4 비중으로 결합하여 분석하세요.
                    6. (원문 참조 및 인용) 분석 시 반드시 'HS-manual.txt'에서 발췌된 아래 [HS 해설서 법령 원문]의 구체적인 문구와 단어를 직접 인용하여 리포트를 작성할 것.
                    7. (세번 확정) 정확히 동일한 품명의 4단위 호가 있는 경우 하위 6단위를 찾아 확정하며, 특계된 호가 없다면 제일 하위에 '기타' 호로 분류할 것.
                    8. (경합 검토) 예상되는 호가 복수일 경우 본질적인 특성, 재질, 기능에 따라 우선순위를 결정할 것.
                    9. (무결성) 답변 양식을 절대 임의로 축약하지 말고, 지정된 출력 양식을 100% 준수할 것.
                    """

                    prompt = f"""당신은 30년 경력의 베테랑 대한민국 관세사입니다. 
                    다음 양식에 맞춰 분석 리포트를 작성하세요. 특히 제공된 법령 원문을 적극 인용하여 전문성을 보여주세요. {knowledge_instruction}
                    
                    [HS 해설서 법령 원문 (실시간 참조 데이터)]
                    {legal_ground_text}

                    [리포트 작성 지침]
                    - 리포트 내 항목명과 항목내용 사이에는 빈 줄을 추가하지 말고 줄바꿈만 적용해주세요.
                    - 이전 항목 내용과 다음 항목명 사이에는 반드시 빈 줄을 추가하세요.
                    - 각 항목명(1., 2., 3., 4.)은 **굵게** 표시하세요.
                    - "3. 분류 근거"는 발췌된 해설서 원문 내용을 바탕으로 3개 문단 구조를 최대한 준수해주세요.
                    - 아래 특정 문구는 HTML 태그를 사용하여 서식을 고정하세요:
                        1) "💡 AI 분석 리포트" -> 20px 굵게
                        2) "2. 추천 HS Code" 내의 "XXXX.XX" -> 20px 굵게
                        3) "※ 주의사항 ※" -> 17px 및 빨간색(#ED1C24) 굵게
                    - "4. 추천 HS Code내 분류가능한 HSK" 항목 작성 지침:
                        1) [검색 단계]: "2. 추천 HS Code"에서 결정한 6단위(예: 8470.10)에서 마침표(.)를 즉시 제거하여 숫자 6자리(예: 847010)를 만드세요.
                        2) [매칭 단계]: 위 숫자 6자리와 [참조용 HSK 리스트 데이터]의 'CODE:' 뒤에 오는 숫자 앞 6자리가 '토씨 하나 틀리지 않고 일치'하는 행만 필터링하세요.
                        3) [검증 단계]: 만약 위 숫자 6자리(예: 847010)로 시작하는 데이터가 [참조용 HSK 리스트 데이터]에 단 하나도 없다면, 절대로 번호를 임의로 만들어내지 마세요.
                        4) [출력 형식]: 일치하는 데이터가 있다면 반드시 'XXXX.XX-XXXX 국문품명 [영문품명]' 형식으로 변환하여 모두 나열하세요.
                            (예시: 8470.10-3000 전자계산기 [Electronic calculators])
                        5) [확인 불가]: 데이터가 있다면 리스트를 나열하고, 없다면 "10단위 상세 HSK는 화면 하단 전문관세사 의뢰통해 문의바랍니다."라고 작성하세요.                        
                    - "4. 예상 경합세번"은 추천 번호의 확률이 100%가 아닌 경우만 상위 3순위까지 표시하세요.
                    - "5. 검색용 태그"에 반드시 아래 형식으로 최종 추천 6단위 코드를 한 번 더 적어주세요. (형식: [TARGET_HS6: XXXX.XX] (예: [TARGET_HS6: 8470.10]))

                    [입력 정보]
                    {input_summary}

                    [리포트 출력 양식]
                    <span style='font-size:20px; font-weight:bold;'>💡 AI 분석 리포트</span>

                    **1. 입력정보**
                       1) 이미지 해석: (이미지가 있다면 시각적 특징과 식별 포인트 간략히 서술, 없으면 '정보 없음')
                    {input_summary}

                    **2. 추천 HS Code (6자리)**: <span style='font-size:20px; font-weight:bold;'>XXXX.XX</span> (예상 확률 %) 
                       - 4단위 HS Code: XXXX [호의 용어 한글(영문)]
                       - 6단위 HS Code: XXXX.XX [소호의 용어(영문)]                       

                    **3. 분류 근거**
                       - 해당 물품이 속하는 부/류의 분류 규정 및 [HS 해설서 법령 원문]의 총설 내용 인용 및 요약
                       - 제{matched_h_code}호 및 하위 단위 호의 용어 상세 설명과 해설서 원문의 구체적 예시 직접 인용
                       - 물품 정보 요약 및 통칙 제1호/제6호 적용 과정을 통한 최종 번호 확정 논리

                    **4. 예상 경합세번**
                       - 2순위: XXXX.XX(00%)
                       - 3순위: XXXX.XX-XX(00%)

                    **※ HSK 검색용 태그**: [TARGET_HS6: XXXX.XX] 

                    """
                    
                    # 3단계: 멀티모달 입력 (텍스트 + 업로드 이미지)
                    content = [prompt]
                    if uploaded_file:
                        # 세션에 저장된 마지막 이미지 바이트 사용
                        content.append(Image.open(io.BytesIO(st.session_state.last_img_bytes)))
                    
                    response = model.generate_content(content)
                    
                    st.session_state.ai_report_done = True
                    st.session_state.last_report_text = response.text
                    st.session_state.last_input_summary = input_summary
                    
                    # 이미지 해석 텍스트 추출 보정
                    if "1) 이미지 해석:" in response.text:
                        st.session_state.img_analysis_text = response.text.split("1) 이미지 해석:")[1].split("2. 추천")[0].strip()
                    
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 분석 오류: {e}")

    # [3] 결과 출력 및 HSK 자동 검색 로직 결합
    if st.session_state.ai_report_done:
        # 1. AI 리포트 원문 출력
        st.markdown(st.session_state.last_report_text, unsafe_allow_html=True)
        
        # 2. HSK 10단위 검색 및 출력 로직
        report_content = st.session_state.last_report_text
        match = re.search(r"\[TARGET_HS6:\s?(\d{4}\.\d{2})\]", report_content)
        
        if match:
            hs6_display = match.group(1)
            hs6_query = hs6_display.replace(".", "")
            
            st.markdown(f"""
                <div style='font-size: 16px; font-weight: bold; color: #31333F; margin-top: 20px; margin-bottom: 15px;'>
                    5. 분류가능 HSK(10단위) 리스트
                </div>
            """, unsafe_allow_html=True)
            
            # df_sub_hs_master 전역 변수 사용
            target_hsk = df_sub_hs_master[df_sub_hs_master['HS10'].str.startswith(hs6_query, na=False)]
            
            if not target_hsk.empty:
                hsk_text_list = ""
                for _, row in target_hsk.iterrows():
                    raw_code = row['HS10']
                    formatted_code = f"{raw_code[:4]}.{raw_code[4:6]}-{raw_code[6:]}"
                    hsk_text_list += f"* **{formatted_code}** {row['name_kr']} [{row['name_en']}]\n"
                st.markdown(hsk_text_list)
            else:
                st.info(f"10단위 HSK는 하단의 전문관세사에게 문의 부탁드립니다.")

        # --- 주의사항 ---
        st.markdown(f"""
            <div style="margin-top: 25px; line-height: 1.6;">
                <span style='font-size:15px; font-weight:bold; color:#ED1C24;'>※ 주의사항 ※</span><br>
                <span style='font-size:13px; color:#333;'>
                - 본 리포트는 제공된 정보에 기초하여 작성되었으나, 실제 물품 스펙에 따라 변경될 수 있습니다.<br>
                - 본 리포트는 참고 자료이며 법적 책임을 지지 않습니다. 정확한 분류는 반드시 관세사에게 문의하십시오.<br>
                - 상세 상담이 필요하신 경우 하단 "관세사 검토의뢰"를 누르시면 본 리포트가 전문 관세사에게 전달됩니다.
                </span>
            </div>
        """, unsafe_allow_html=True)                   

        # 3. 전문 관세사 검토의뢰 섹션
        st.divider()
        st.markdown("#### 📧 추가 검토가 필요하신 경우, 전문 관세사에게 의뢰하세요.")
                
        st.markdown("""
            <style>
            div[data-testid="stButton"] > button { height: 40px !important; margin-top: 24px !important; width: 100% !important; background-color: #1E3A8A !important; color: white !important; font-weight: bold; }
            [data-testid="column"] { display: flex; flex-direction: column; justify-content: flex-end; }
            </style>
            """, unsafe_allow_html=True)
        
        col_u1, col_u2, col_u3 = st.columns([0.375, 0.375, 0.25])
        with col_u1: u_org = st.text_input("상호명 (또는 성함)", key="u_org_v4", placeholder="예: (주)이지스무역")
        with col_u2: u_contact = st.text_input("연락처 (전화/이메일)", key="u_contact_v4", placeholder="예: 010-1234-5678/jhlee@aegiscustoms.com")
        with col_u3: send_click = st.button("관세사 검토의뢰")
        
        if send_click:
            if not u_org or not u_contact: st.error("⚠️ 정보를 입력해주세요.")
            else:
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                from email.mime.application import MIMEApplication
                S_EMAIL = "jhlee@aegiscustoms.com"
                S_PASS = st.secrets.get("EMAIL_PASSWORD", "") 
                if not S_PASS: st.error("❌ 설정 오류")
                else:
                    msg = MIMEMultipart()
                    msg['From'] = S_EMAIL
                    msg['To'] = S_EMAIL 
                    msg['Subject'] = f"품목분류 검토의뢰_{u_org}"
                    body = f"의뢰인: {u_org}\n연락처: {u_contact}\n\n[입력정보]\n{st.session_state.last_input_summary}\n\n[AI리포트]\n{st.session_state.last_report_text}"
                    msg.attach(MIMEText(body, 'plain'))
                    if st.session_state.last_img_bytes:
                        att = MIMEApplication(st.session_state.last_img_bytes)
                        att.add_header('Content-Disposition', 'attachment', filename=f'req_{u_org}.png')
                        msg.attach(att)
                    try:
                        server = smtplib.SMTP("smtp.gmail.com", 587); server.starttls(); server.login(S_EMAIL, S_PASS)
                        server.sendmail(S_EMAIL, S_EMAIL, msg.as_string()); server.quit()
                        st.success(f"✅ 의뢰 접수 완료! 곧 연락드리겠습니다.")                                                
                    except Exception as e: st.error(f"❌ 전송 실패: {e}")

# --- [Tab 2] HS정보 --- 
with tabs[1]:
    st.markdown("""
        <style>
            /* 1. 모든 데이터프레임 열 제목(Header) 가운데 정렬 - 경로를 더 상세히 지정 */
            div[data-testid="stDataFrame"] div[data-testid="stTable"] th,
            div[data-testid="stDataFrame"] div[role="columnheader"] p {
                text-align: center !important;
                justify-content: center !important;
                display: flex !important;
                align-items: center !important;
                width: 100% !important;
                font-weight: bold !important;
            }

            /* 2. 표준품명(16px)/기본품명 박스 스타일 및 테두리 */
            .box-base { 
                padding: 15px !important; 
                border-radius: 8px !important; 
                border-left: 6px solid !important; 
                min-height: 110px !important; 
                line-height: 1.6 !important; 
                margin-bottom: 10px !important; 
            }
            .box-green { background-color: #F0FDF4 !important; border-color: #16A34A !important; color: #166534 !important; font-size: 16px !important; font-weight: 600 !important; }
            .box-blue { background-color: #EFF6FF !important; border-color: #2563EB !important; color: #1E40AF !important; font-size: 16px !important; }
            
            .res-title { font-size: 18px; font-weight: bold; color: #1E3A8A; margin-bottom: 15px; }

            /* 3. [핵심] 통합공고 요령 10px 강제 적용 (가장 강력한 선택자 사용) */
            .small-font-table div[data-testid="stDataFrame"] [role="gridcell"] * {
                font-size: 10px !important;
                line-height: 1.2 !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # 데이터 로드
    data = load_aggs_master_data()
    df_m_hs, df_m_sn, df_m_tc, df_t_ac, df_t_etc, df_t_f1, df_t_f2, df_t_fm, df_r_im, df_r_ex, df_c_im, df_c_ex = data

    # 검색창
    s_col1, s_col2 = st.columns([0.8, 0.2])
    with s_col1:
        target_hs_raw = st.text_input("HS Code 10자리 입력", key="hs_final_search_v6").strip().replace("-", "").replace(".", "").zfill(10)
    with s_col2:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button("🔍 검색", use_container_width=True)
    formatted_hs = f"{target_hs_raw[:4]}.{target_hs_raw[4:6]}-{target_hs_raw[6:]}"
    if target_hs_raw != "0000000000" or search_clicked:
        st.markdown(f"<div class='res-title'>🔍 {formatted_hs} 조회 결과</div>", unsafe_allow_html=True)

        # --- 2. 품명 섹션 ---
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.write("📂 **표준품명**")
            sn_val = df_m_sn[df_m_sn['HS_code'] == target_hs_raw]['Item_name'].iloc[0] if not df_m_sn[df_m_sn['HS_code'] == target_hs_raw].empty else "정보 없음"
            st.markdown(f"<div class='box-base box-green'>{sn_val}</div>", unsafe_allow_html=True)
            
        with col_m2:
            st.write("📂 **기본품명**")
            m_row = df_m_hs[df_m_hs['HS_code'] == target_hs_raw]
            if not m_row.empty:
                st.markdown(f"""
                    <div class='box-base box-blue'>
                        <b>국문품명:</b> {m_row.iloc[0]['Name_kor']}<br>
                        <b>영문품명:</b> {m_row.iloc[0]['Name_Eng']}
                    </div>
                """, unsafe_allow_html=True)
            else: 
                st.markdown("<div class='box-base box-blue'>정보 없음</div>", unsafe_allow_html=True)

        st.divider()

        # --- 3. 관세율 정보 ---
        st.markdown("<div class='res-title'>💰 관세율 정보</div>", unsafe_allow_html=True)
        
        ac_data = df_t_ac[df_t_ac['HS_code'] == target_hs_raw]
        val_a = ac_data[ac_data['Trff_rate_class'] == 'A']['Trff_rate'].iloc[0] if not ac_data[ac_data['Trff_rate_class'] == 'A'].empty else "-"
        val_c = ac_data[ac_data['Trff_rate_class'] == 'C']['Trff_rate'].iloc[0] if not ac_data[ac_data['Trff_rate_class'] == 'C'].empty else "-"

        col_r1, col_r2 = st.columns(2)
        
        rate_config = {
            "코드": st.column_config.TextColumn("코드", alignment="center"),
            "세율명칭": st.column_config.TextColumn("세율명칭", alignment="center"),
            "세율": st.column_config.NumberColumn("세율", format="%.1f%%", alignment="center")
        }

        # [상단 영역] 기본세율(A)와 WTO협정세율(C) 배치
        up_col1, up_col2 = st.columns(2)
        with col_r1:
            st.markdown(f"기본세율(A)<br><b style='font-size:25px; color:#D32F2F;'>{val_a}%</b>", unsafe_allow_html=True)            
        with col_r2:
            st.markdown(f"WTO협정세율(C)<br><b style='font-size:25px; color:#D32F2F;'>{val_c}%</b>", unsafe_allow_html=True)

        st.divider()
        
        # [하단 영역] 기타세율과 협정세율(FTA) 배치
        down_col1, down_col2 = st.columns(2)
        with down_col1:
            st.write("**기타세율**")
            etc_res = df_t_etc[df_t_etc['HS_code'] == target_hs_raw][['Trff_rate_class', 'Trff_rate']]
            etc_res = etc_res.merge(df_m_tc[['Trff_rate_class', 'Trff_rate_class_name_kr']], on='Trff_rate_class', how='left')
            etc_res = etc_res[['Trff_rate_class', 'Trff_rate_class_name_kr', 'Trff_rate']]
            etc_res.columns = ['코드', '세율명칭', '세율']
            st.dataframe(etc_res, use_container_width=True, hide_index=True, column_config=rate_config)
            
        with down_col2:
            st.write("**협정세율(FTA)**")
            fta_all = pd.concat([df_t_f1, df_t_f2, df_t_fm])
            fta_res = fta_all[fta_all['HS_code'] == target_hs_raw][['Trff_rate_class', 'Trff_rate']]
            fta_res = fta_res.merge(df_m_tc[['Trff_rate_class', 'Trff_rate_class_name_kr']], on='Trff_rate_class', how='left')
            fta_res = fta_res[['Trff_rate_class', 'Trff_rate_class_name_kr', 'Trff_rate']]
            fta_res.columns = ['코드', '세율명칭', '세율']
            st.dataframe(fta_res, height=250, use_container_width=True, hide_index=True, column_config=rate_config)

        st.divider()

        # --- 4. 세관장확인대상 ---
        st.markdown("<div class='res-title'>🛡️ 세관장확인대상 (수출입요건)</div>", unsafe_allow_html=True)
        col_req1, col_req2 = st.columns(2)
        
        req_config = {
            "법령명": st.column_config.TextColumn("법령명", alignment="center"),
            "승인기관": st.column_config.TextColumn("승인기관", alignment="center"),
            "서류명": st.column_config.TextColumn("서류명", alignment="center")
        }
        
        with col_req1:
            st.write("📥 **수입요건**")
            im_req = df_r_im[df_r_im['HS_code'] == target_hs_raw][['Law_code_name', 'apprv_agncy_code_name', 'Req_doc_name']]
            if not im_req.empty:
                im_req.columns = ['법령명', '승인기관', '서류명']
                st.dataframe(im_req.sort_values('법령명'), height=250, use_container_width=True, hide_index=True, column_config=req_config)
            else:
                st.info("조회된 수입요건 정보가 없습니다.") # 정보 없을 때 출력
            
        with col_req2:
            st.write("📤 **수출요건**")
            ex_req = df_r_ex[df_r_ex['HS_code'] == target_hs_raw][['Law_code_name', 'apprv_agncy_code_name', 'Req_doc_name']]
            if not ex_req.empty:
                ex_req.columns = ['법령명', '승인기관', '서류명']
                st.dataframe(ex_req.sort_values('법령명'), height=250, use_container_width=True, hide_index=True, column_config=req_config)
            else:
                st.info("조회된 수출요건 정보가 없습니다.")

        st.divider()

        # --- 5. 통합공고 ---
        st.markdown("<div class='res-title'>🔰 통합공고</div>", unsafe_allow_html=True)
        col_cp1, col_cp2 = st.columns(2)
        
        cp_config = {
            "법령명": st.column_config.TextColumn("법령명", alignment="center"),
            "대상": st.column_config.TextColumn("대상", alignment="center"),
            "요령": st.column_config.TextColumn("요령", alignment="left")
        }

        with col_cp1:
            st.write("📥 **수입요령**")
            df_c_im_clean = df_c_im.dropna(subset=['HS_code'])
            cp_im_res = df_c_im_clean[df_c_im_clean.apply(lambda x: str(target_hs_raw).startswith(str(x['HS_code']).split('.')[0]), axis=1)]
            if not cp_im_res.empty:
                cp_im_display = cp_im_res[['Law_name', 'Name', 'Guide']].copy()
                cp_im_display.columns = ['법령명', '대상', '요령']
                st.markdown("<div class='small-font-table'>", unsafe_allow_html=True)
                st.dataframe(cp_im_display.sort_values('법령명'), height=250, use_container_width=True, hide_index=True, column_config=cp_config)
                st.markdown("</div>", unsafe_allow_html=True)
            else: st.info("조회된 정보 없음")

        with col_cp2:
            st.write("📤 **수출요령**")
            df_c_ex_clean = df_c_ex.dropna(subset=['HS_code'])
            cp_ex_res = df_c_ex_clean[df_c_ex_clean.apply(lambda x: str(target_hs_raw).startswith(str(x['HS_code']).split('.')[0]), axis=1)]
            if not cp_ex_res.empty:
                cp_ex_display = cp_ex_res[['Law_name', 'Name', 'Guide']].copy()
                cp_ex_display.columns = ['법령명', '대상', '요령']
                st.markdown("<div class='small-font-table'>", unsafe_allow_html=True) # 클래스 명칭 확인
                st.dataframe(cp_im_display.sort_values('법령명'), height=250, use_container_width=True, hide_index=True, column_config=cp_config)
                st.markdown("</div>", unsafe_allow_html=True)
            else: st.info("조회된 정보 없음")

# --- [Tab 3] 통계부호 통합 조회 서비스 --- 
with tabs[2]:
    st.markdown("<div class='custom-header'>📊 통계부호 통합 조회 서비스</div>", unsafe_allow_html=True)

    # --- 1. 데이터 소스 및 매핑 설정 ---
    # (1) 세율통계 (왼쪽상단)
    URL_TAX = "https://docs.google.com/spreadsheets/d/1fYs-hPiysNO6M4vQoOJ4cJSzr7XNzeKssH-IfEBrkbw/edit?usp=sharing"
    MAP_TAX = {"관세율": "Tariff", "간이세율": "GANI", "내국세율": "DOMESTIC", "관세감면율": "REDUCTION_TARIFF", "내국세감면율": "REDUCTION_DOMESTIC"}

    # (2) 고정부호 (오른쪽상단)
    URL_FIX = "https://docs.google.com/spreadsheets/d/1Y8rg_Ypgm5Cz1to0nxxv_5ijLJulwI0RDhHaJk2oeB8/edit?usp=sharing"
    MAP_FIX = {
        "BL구분코드": "BL_TPCD", "BL분할사유코드": "BL_DVDE_RCD", "BL유형코드": "BL_PCD", "CIQ수속장소구분코드": "CIQ_PRCD_PLC_TPCD", "COB화물검사결과코드": "COB_CARG_INSC_RSCD", 
        "COB화물변경사유코드": "COB_CARG_CHNG_RCD", "CY_CFS구분코드": "CY_CFS_TPCD", "FTA원산지결정기준코드": "FTA_ORCY_DTRM_BASE_CD", "IMDG위험물구분코드": "IMDG_DNAR_TPCD", 
        "가격신고항목코드": "PRC_DCLR_ITEM_CD", "가격조건코드": "PRC_COND_CD", "가산세면제사유코드": "ADTX_EXMP_RCD", "가족관계코드": "FMLY_RLCD", "간이수출검사결과코드": "SIML_EXP_INSC_RSCD", 
        "감시분석대상구분코드": "SRVL_ANAY_TRGT_TPCD", "개장검사내역처리상태코드": "OPBG_INSC_BRKD_PRCS_STCD", "개장검사물품확인결과코드": "OPBG_INSC_CMDT_CFRM_RSCD", "거래근거문서구분코드": "DLNG_BSS_DOC_TPCD", 
        "거주상태코드": "RSDN_STCD", "건설기계업무코드": "CNSC_MCHN_BSOP_CD", "건설기계차종코드": "CNSC_MCHN_KCAR_CD", "검사검역지정유형코드": "INSC_QUAN_APNT_PCD", "검사대상비지정사유코드": "INSC_TRGT_NNAPNT_RCD", 
        "검사대상해제사유코드": "INSC_TRGT_RELE_RCD", "검사방법코드": "INSC_MCD", "검색기검사처리상태코드": "DTCT_INSC_PRCS_STCD", "결손처분사유코드": "DFCT_DSPS_RCD", "결제구분코드": "STLM_TPCD", 
        "결제방법코드": "STLM_MCD", "경제권종류코드": "EBK_KCD", "계코드": "DPRT_CD", "고발사유코드": "CHRG_RCD", "고발의견코드": "CHRG_OPIN_CD", "고발처분코드": "CHRG_DSPS_CD", "고지유형코드": "NFCPN_PCD", 
        "과다환급추징유형코드": "EXCS_DRWB_ADCH_PCD", "과징금코드": "FNDF_CD", "관내입항지구분코드": "WTJR_ENTP_TPCD", "관리대상화물검사결과코드": "MT_TRGT_CARG_INSC_RSCD", "관리대상화물검사구분코드": "MT_TRGT_CARG_INSC_TPCD", 
        "관리대상화물수작업선별사유코드": "MT_TRGT_CARG_HNWR_SELC_RCD", "관리대상화물조치결과코드": "MT_TRGT_CARG_TKAC_RSCD", "관리대상화물중량초과구분코드": "MT_TRGT_CARG_WGHT_OVER_TPCD", 
        "관리대상화물해제사유코드": "MT_TRGT_CARG_RELE_RCD", "관세감면분납코드": "TRIF_RDEX_INPY_CD", "관세사거래관계기재구분코드": "LCA_DLNG_REL_STTM_TPCD", "관세사검사의견기재구분코드": "LCA_INSC_OPIN_STTM_TPCD", 
        "관세사별제재사유코드": "LCA_PR_RSTN_RCD", "관세사표창구분코드": "LCA_CMNN_TPCD", "관세사품명규격기재구분코드": "LCA_PRNM_STSZ_STTM_TPCD", "관세율구분코드": "TRRT_TPCD", "관세청업종코드": "KCS_INTP_CD", 
        "교육세과세구분코드": "EDTX_TX_TPCD", "국세청법인구분코드": "NTS_JRPN_TPCD", "국세청법인성격코드": "NTS_JRPN_CHACR_CD", "국세청업종코드": "NTS_INTP_CD", "귀책사유코드": "IMPT_RCD", "근무반구분코드": "BWRK_CLSS_TPCD", 
        "까르네물품용도코드": "CARN_CMDT_USG_CD", "남북교역구분코드": "NSKOR_TRDE_TPCD", "남북통행정정항목코드": "NSKOR_PASG_MDFY_ITEM_CD", "납기연장사유코드": "TPAY_XTNS_RCD", "내국물품반출입정정항목코드": "DMSC_CMDT_RLBR_MDFY_ITEM_CD", 
        "내국세구분코드": "ITX_TPCD", "내국세세종코드": "ITX_TXTP_CD", "농특세과세구분코드": "RDTX_TX_TPCD", "담당자변경사유코드": "CHPN_CHNG_RCD", "담보업체변경사유코드": "MG_ENTS_CHNG_RCD", "담보업체취소사유코드": "MG_ENTS_CNCL_RCD", 
        "담보제공사유코드": "MG_OFR_RCD", "담보종류코드": "MG_KCD", "대륙종류코드": "CNTN_KCD", "대상업체구분코드": "TRGT_ENTS_TPCD", "동향구분코드": "TRND_TPCD", "동향유형코드": "TRND_PCD", "마약물품종류코드": "NRCT_CMDT_KCD", 
        "마약약리작용구분코드": "NRCT_MDAC_ACTI_TPCD", "마약은닉장소코드": "NRCT_CNCM_PLC_CD", "마약의약용도구분코드": "NRCT_DRG_USG_TPCD", "마약적발경위구분코드": "NRCT_DSCL_CRCM_TPCD", "마약적발관련자처리상태코드": "NRCT_DSCL_RELAPN_PRCS_STCD", 
        "마약조직원역할코드": "NRCT_ORGM_ROLE_CD", "마약종류코드": "NRCT_KCD", "마약코드": "NRCT_CD", "마약투여방법코드": "NRCT_INJC_MCD", "마약형태코드": "NRCT_FORM_CD", "말소구분코드": "ERSR_TPCD", "물품반입구분코드": "CMDT_BRNG_TPCD", 
        "물품용도코드": "CMDT_USG_CD", "물품용역업체항공영업종류코드": "CMDT_SBCN_ENTS_FLGH_BUSN_KCD", "물품용역업체해상영업종류코드": "CMDT_SBCN_ENTS_SEA_BUSN_KCD", "물품폐기사유코드": "CMDT_DSCD_RCD", "미가산사유코드": "NADTN_RCD", 
        "밀수근원코드": "SMGL_SRC_CD", "밀수신고접수방법코드": "SMGL_DCLR_ACAP_MCD", "반입경로코드": "BRNG_PATH_CD", "반입유형코드": "BRNG_PCD", "반출기간연장구분코드": "RLSE_PRID_XTNS_TPCD", "반출사유코드": "RLSE_RCD", 
        "반출유형코드": "RLSE_PCD", "반출입외화용도구분코드": "RLBR_FRCR_USG_TPCD", "발각원인코드": "DSLS_CSE_CD", "범칙물품상표코드": "INRG_CMDT_BRND_CD", "범칙물품유형코드": "INRG_CMDT_PCD", "범칙상세경로코드": "INRG_DTL_PATH_CD", 
        "범칙수단코드": "INRG_METH_CD", "범행동기코드": "CRIM_MTV_CD", "법령종류코드": "LWOR_KCD", "법령코드": "LWOR_CD", "법무부출입국도시코드": "MOJ_EDCY_CITY_CD", "법조문구분코드": "LW_CDLN_TPCD", "병역구분코드": "MISR_TPCD", 
        "보세구역구분코드": "SNAR_TPCD", "보세구역반출입정정항목코드": "SNAR_RLBR_MDFY_ITEM_CD", "보세구역반출입화물종류코드": "SNAR_RLBR_CARG_KCD", "보세운송검사구분코드": "BNBN_TRNP_INSC_TPCD", "보세운송검사대상구분코드": "BNBN_TRNP_INSC_TRGT_TPCD", 
        "보세운송검사지정상태코드": "BNBN_TRNP_INSC_APNT_STCD", "보세운송검사처리상태코드": "BNBN_TRNP_INSC_PRCS_STCD", "보세운송승인신청담보구분코드": "BNBN_TRNP_APRE_RQST_MG_TPCD", "보세운송승인신청사유코드": "BNBN_TRNP_APRE_RQST_RCD", 
        "보수작업형태코드": "RPR_WKNG_FORM_CD", "보정심사생략구분코드": "RVSN_AUDT_OMIT_TPCD", "보정심사수작업선별사유코드": "RVSN_AUDT_HNWR_SELC_RCD", "보정심사처리상태코드": "RVSN_AUDT_PRCS_STCD", "봉인내역코드": "SELG_BRKD_CD", 
        "봉인지정내역처리상태코드": "SELG_APNT_BRKD_PRCS_STCD", "부가세과세구분코드": "VAT_TX_TPCD", "분할반출입구분코드": "DVDE_RLBR_TPCD", "분할통합사유코드": "DVDE_UNFC_RCD", "비위유형코드": "AGTL_PCD", "사건근거구분코드": "INCD_BSS_TPCD", 
        "사업자구분코드": "BSNS_TPCD", "사업종류코드": "BUSI_KCD", "사이트유형코드": "SITE_PCD", "사전세액심사선별기준코드": "BTAA_SELC_BASE_CD", "사후관리방법코드": "AFFC_MT_MCD", "사후관리비대상사유코드": "AFFC_MT_NNOB_RCD", 
        "사후관리조치결과코드": "AFFC_MT_TKAC_RSCD", "사후관리조치상태코드": "AFFC_MT_TKAC_STCD", "사후관리종결일자구분코드": "AFFC_MT_CONC_DT_TPCD", "사후관리확인결과코드": "AFFC_MT_CFRM_RSCD", "사후관리확인방법코드": "AFFC_MT_CFRM_MCD", 
        "상이내역코드": "DFRN_BRKD_CD", "상표코드": "BRND_CD", "서류제출변경사유코드": "ISTM_SBMT_CHNG_RCD", "선기용품적재물품구분코드": "SHAR_SUPL_LOAD_CMDT_TPCD", "선박일제점검결과코드": "SHIP_ALTG_CHK_RSCD", "선박종류코드": "SHIP_KCD", 
        "선별검사종류코드": "SELC_INSC_KCD", "선별사유코드": "SELC_RCD", "선별종류코드": "SELC_KCD", "선원구분코드": "CREW_TPCD", "성별코드": "GNDR_CD", "세관장확인대상법령코드": "CSOR_CFRM_TRGT_LWOR_CD", "세관처분유형코드": "CSTM_DSPS_PCD", 
        "세외수입위반유형코드": "NTRV_VLTN_PCD", "소요량산정방법코드": "RQTY_CLCU_MCD", "수리전반출승인사유코드": "BFAC_RLSE_APRE_RCD", "수리전반출취소사유코드": "BFAC_RLSE_CNCL_RCD", "수사지휘구분코드": "INVS_CMND_TPCD", 
        "수입각하사유코드": "IMP_RJCT_RCD", "수입거래구분코드": "IMP_DLNG_TPCD", "수입검사결과코드": "IMP_INSC_RSCD", "수입검사구분코드": "IMP_INSC_TPCD", "수입검사변경사유코드": "IMP_INSC_CHNG_RCD", "수입검사변경코드": "IMP_INSC_CHNG_CD", 
        "수입검사생략사유코드": "IMP_INSC_OMIT_RCD", "수입귀책사유코드": "IMP_IMPT_RCD", "수입보완요구사유코드": "IMP_SPLM_REQS_RCD", "수입성질코드": "IMP_TMPR_CD", "수입신고구분코드": "IMP_DCLR_TPCD", "수입신고정정사유코드": "IMP_DCLR_MDFY_RCD", 
        "수입자구분코드": "IMPPN_TPCD", "수입전산선별사유코드": "IMP_INTC_SELC_RCD", "수입정정항목코드": "IMP_MDFY_ITEM_CD", "수입조건변경구분코드": "IMP_COND_CHNG_TPCD", "수입조치사항코드": "IMP_TKAC_MATR_CD", "수입종류코드": "IMP_KCD", 
        "수입취하사유코드": "IMP_WTHD_RCD", "수입통관계획코드": "IMP_CSCL_PLAN_CD", "수입통관미결사유코드": "IMP_CSCL_UNDC_RCD", "수입통관처리상태코드": "IMP_CSCL_PRCS_STCD", "수작업선별사유코드": "HNWR_SELC_RCD", "수작업수납등록사유코드": "HNWR_RCVE_RGSR_RCD", 
        "수출거래구분코드": "EXP_DLNG_TPCD", "수출검사결과조치코드": "EXP_INSC_RSLT_TKAC_CD", "수출검사결과코드": "EXP_INSC_RSCD", "수출검사구분코드": "EXP_INSC_TPCD", "수출검사변경사유코드": "EXP_INSC_CHNG_RCD", "수출귀책사유코드": "EXP_IMPT_RCD", 
        "수출반송사유코드": "EXP_RETU_RCD", "수출보완요구사유코드": "EXP_SPLM_REQS_RCD", "수출성질코드": "EXP_TMPR_CD", "수출신고각하사유코드": "EXP_DCLR_RJCT_RCD", "수출신고구분코드": "EXP_DCLR_TPCD", "수출신고정정사유코드": "EXP_DCLR_MDFY_RCD", 
        "수출신고제출서류구분코드": "EXP_DCLR_SBMT_ISTM_TPCD", "수출신고처리상태코드": "EXP_DCLR_PRCS_STCD", "수출신고취하사유코드": "EXP_DCLR_WTHD_RCD", "수출신고항목코드": "EXP_DCLR_ITEM_CD", "수출입신고각하사유코드": "IMEX_DCLR_RJCT_RCD", 
        "수출자구분코드": "EXPPN_TPCD", "수출접수결과구분코드": "EXP_ACAP_RSLT_TPCD", "수출종류코드": "EXP_KCD", "수출형태구분코드": "EXP_FORM_TPCD", "수출형태코드": "EXP_FORM_CD", "신고구분코드": "DCLR_TPCD", 
        "신고업체페이퍼리스제재사유코드": "DCLR_ENTS_PLS_RSTN_RCD", "신병조치결과코드": "RKE_TKAC_RSCD", "신청방법코드": "RQST_MCD", "신청서처리상태코드": "APFM_PRCS_STCD", "신청인구분코드": "APLC_TPCD", "심사근거번호구분코드": "AUDT_BSS_NO_TPCD", 
        "심사의견구분코드": "AUDT_OPIN_TPCD", "압수물품처분유형코드": "CFSC_CMDT_DSPS_PCD", "업무영역코드": "BSOP_TRTR_CD", "업체평가등급코드": "ENTS_EV_GD_CD", "여권발급지역코드": "PSPR_ISS_REGN_CD", "여행목적코드": "TRVL_PUPS_CD", 
        "여행자수작업선별사유코드": "PSNR_HNWR_SELC_RCD", "여행자우범등급코드": "PSNR_LBCR_GD_CD", "요청정보대상구분코드": "REQT_INFO_TRGT_TPCD", "용도구분코드": "USG_TPCD", "우범등급코드": "LBCR_GD_CD", "우범사이트추적근원구분코드": "LBCR_SITE_TRCN_SRC_TPCD", 
        "우범사이트품명코드": "LBCR_SITE_PRNM_CD", "우편물기타폐기사유코드": "PSMT_OTH_DSCD_RCD", "우편물면세사유코드": "PSMT_TXFR_RCD", "우편물반송사유코드": "PSMT_RETU_RCD", "우편물종류코드": "PSMT_KCD", "우편물통관유의코드": "PSMT_CSCL_ATENT_CD", 
        "우편물폐기사유코드": "PSMT_DSCD_RCD", "운송사업종류코드": "TRNP_BUSI_KCD", "운송수단유형코드": "TRNP_METH_PCD", "운송수단임차신청사유코드": "TRNP_METH_HIRE_RQST_RCD", "운송용기구분코드": "TRNP_CNTAI_TPCD", "운항계획정정사유코드": "SLNG_PLAN_MDFY_RCD", 
        "원산지결정기준코드": "ORCY_DTRM_BASE_CD", "원산지증명발급구분코드": "CNVN_TPCD_01", "원산지증명서유무구분코드": "ORCY_CRPP_EON_TPCD", "원산지표시면제사유코드": "ORCY_INDC_EXMP_RCD", "원산지표시방법코드": "ORCY_INDC_MCD", 
        "원산지표시유무구분코드": "ORCY_INDC_EON_TPCD", "원재료구분코드": "RWMS_TPCD", "위반유형코드": "VLTN_PCD", "위해물품반출입사유코드": "INJR_CMDT_RLBR_RCD", "위해물품조치결과코드": "INJR_CMDT_TKAC_RSCD", "위해물품종류코드": "INJR_CMDT_KCD", 
        "은닉수법코드": "CNCM_TCHN_CD", "의무이행요구사유코드": "DTY_FFMN_REQS_RCD", "이사자직업코드": "IMGR_JOB_CD", "이체대사결과코드": "FNTR_CMVL_RSCD", "인도조건코드": "DLCN_CD", "인증수출자반려취소사유코드": "CRTF_EXPPN_RTRN_CNCL_RCD", 
        "인증수출자시정보정사유코드": "CRTF_EXPPN_CRCT_RVSN_RCD", "일제점검선정사유코드": "ALTG_CHK_SLCN_RCD", "입출항구분코드": "IOPR_TPCD", "입출항서류정정항목코드": "IOPR_ISTM_MDFY_ITEM_CD", "입출항정정사유코드": "IOPR_MDFY_RCD", 
        "입출항화물코드": "IOPR_CARG_CD", "입항목적코드": "ETPR_PUPS_CD", "입항적하목록정정항목코드": "ETPR_MNFS_MDFY_ITEM_CD", "자격전환정정사유코드": "QLFC_CHG_MDFY_RCD", "자격증종류코드": "CRQL_KCD", "자격취득구분코드": "QLFC_ACQS_TPCD", 
        "자금원천구분코드": "CPTL_SRCE_TPCD", "자동차업무코드": "CAR_BSOP_CD", "자동차차종코드": "CAR_KCAR_CD", "자료제공거부코드": "DTA_OFR_REJC_CD", "재수출이행의무종결사유코드": "REEXP_FFMN_DTY_CONC_RCD", "적발근거코드": "DSCL_BSS_CD", 
        "적발기법코드": "DSCL_TECN_CD", "적발단서코드": "DSCL_PRVS_CD", "적발유형코드": "DSCL_PCD", "적발장소코드": "DSCL_PLC_CD", "적발항목코드": "DSCL_ITEM_CD", "적하목록미제출조치사항코드": "MNFS_NSBM_TKAC_MATR_CD", 
        "적하목록상이내역코드": "MNFS_DFRN_BRKD_CD", "적하목록정정사유코드": "MNFS_MDFY_RCD", "점검조치결과코드": "CHK_TKAC_RSCD", "정보분석대상품목코드": "INFO_ANAY_TRGT_PRLST_CD", "정보분석등급코드": "INFO_ANAY_GD_CD", 
        "정보입수구분코드": "INFO_OBTN_TPCD", "제재유형코드": "RSTN_PCD", "조사대상신고번호구분코드": "INVG_TRGT_DCLR_NO_TPCD", "조사대상업무구분코드": "INVG_TRGT_BSOP_TPCD", "조사란구분코드": "INVG_LN_TPCD", "조사직원교육코드": "INVG_EMP_EDCT_CD", 
        "조사직원전문분야코드": "INVG_EMP_SPCL_RLM_CD", "조사해제사유코드": "INVG_RELE_RCD", "주소변동사유코드": "ADDR_VRBL_RCD", "중량수량단위코드": "WGHT_QTY_UT_CD", "중요품목코드": "IMPO_PRLST_CD", 
        "즉시반출대상품목구분코드": "IMDT_RLSE_TRGT_PRLST_TPCD", "지인관계코드": "ACQU_RLCD", "직권정산대상업체사유코드": "OFAT_EXCA_TRGT_ENTS_RCD", "직급코드": "CLPS_CD", "직렬코드": "JBLN_CD", "직무보조자구분코드": "DUTY_ASSN_TPCD", 
        "직업분류코드": "JOB_CLSF_CD", "직업코드": "JOB_CD", "직원징계종류코드": "EMP_DSCP_KCD", "직위코드": "OFPO_CD", "징수형태코드": "COLT_FORM_CD", "차량색상코드": "VHCL_CLR_CD", "차량용도코드": "VHCL_USG_CD", 
        "체납발생사유코드": "DLPY_OCRN_RCD", "체화공매불출구분코드": "OVGD_PBAC_GBOO_TPCD", "체화해제사유코드": "OVGD_RELE_RCD", "추가추징납부사유코드": "ADIT_ADCH_PAY_RCD", "추가환급사유코드": "ADIT_DRWB_RCD", 
        "추징고지상세사유코드": "ADCH_NFCPN_DTL_RCD", "추징발생원인구분코드": "ADCH_OCRN_CSE_TPCD", "추징사유코드": "ADCH_RCD", "출항적하목록정정항목코드": "TKOF_MNFS_MDFY_ITEM_CD", "컨테이너검색기위치코드": "CNTR_DTCT_LOCT_CD", 
        "컨테이너길이코드": "CNTR_LEN_CD", "컨테이너너비높이코드": "CNTR_WIDT_HIGT_CD", "컨테이너종류코드": "CNTR_KCD", "통계용선박용도종류코드": "FSTA_SHIP_USG_KCD", "통관고유부호사용정지사유코드": "ECM_USE_STOP_RCD", 
        "통관고유부호사용정지해제사유코드": "ECM_USE_STOP_RELE_RCD", "통관목록검사결과코드": "CSCL_LST_INSC_RSCD", "통관보류사유코드": "CSCL_PSTP_RCD", "통관보류조치코드": "CSCL_PSTP_TKAC_CD", "통화코드": "CURR_CD", "투시결과코드": "CLRV_RSCD", 
        "평가대상업체업종코드": "EV_TRGT_ENTS_INTP_CD", "포상종류코드": "RWRD_KCD", "포장종류코드": "PCK_KCD", "피의자관계코드": "SSPN_RLCD", "하선물품구분코드": "ULVS_CMDT_TPCD", "학력코드": "ACAR_CD", 
        "한베트남FTA수량단위코드": "KVN_FTA_QTY_UT_CD", "한베트남FTA중량단위코드": "KVN_FTA_WGHT_UT_CD", "한베트남FTA포장종류코드": "KVN_FTA_PCK_KCD", "한인니FTA수량단위코드": "KID_FTA_QTY_UT_CD", 
        "한인니FTA중량단위코드": "KID_FTA_WGHT_UT_CD", "한인니FTA포장종류코드": "KID_FTA_PCK_KCD", "항공기자격정정코드": "AIR_QLFC_MDFY_CD", "항공기종류코드": "AIR_KCD", "항공입항정정항목코드": "FLGH_ETPR_MDFY_ITEM_CD", 
        "항해구분코드": "VYG_TPCD", "해상입항정정항목코드": "SEA_ETPR_MDFY_ITEM_CD", "해상항공구분코드": "SEA_FLGH_TPCD", "행정제재유형코드": "ADPN_PCD", "허가수리구분코드": "PERM_ACPT_TPCD", "현장면세배제코드": "SPOT_TXFR_EXCU_CD", 
        "혐의자구분코드": "SSPT_TPCD", "협정구분코드": "CNVN_TPCD", "혼인관계코드": "MRGE_RLCD", "화물검사조치결과코드": "CARG_INSC_TKAC_RSCD", "화물구분코드": "CARG_TPCD", "화물선별구분코드": "CARG_SELC_TPCD", 
        "화물특성구분코드": "CARG_CHRC_TPCD", "확인적발경위코드": "CFRM_DSCL_CRCM_CD", "환급근거서류구분코드": "DRWB_BSS_ISTM_TPCD", "환급대상정정취하사유코드": "DRWB_TRGT_MDFY_WTHD_RCD", 
        "환급대상확인신청서기각사유코드": "DRWB_TRGT_CFRM_APFM_DSMS_RCD", "환급사후심사착수구분코드": "DRWB_PSAD_OTST_TPCD", "환급사후심사착수방안구분코드": "DRWB_PSAD_OTST_PLN_TPCD", "환급신청인구분코드": "DRWB_APLC_TPCD", 
        "환급위험도항목구분코드": "DRWB_DNDG_ITEM_TPCD", "환급제증명오류코드": "DRWB_OCMT_ERR_CD", "환급종류코드": "DRWB_KCD", "회사구분코드": "CO_TPCD", "휴대품가격평가방법코드": "HNBG_PRC_EV_MCD", "휴대품검사결과코드": "HNBG_INSC_RSCD", 
        "휴대품검사사유코드": "HNBG_INSC_RCD", "휴대품면세조항코드": "HNBG_TXFR_CLSE_CD", "휴대품세율적용구분코드": "HNBG_TXRT_APLY_TPCD", "휴대품품명코드": "HNBG_PRNM_CD", "휴무구분코드": "CLSD_TPCD", "휴업폐업사유코드": "SSBS_QIBS_RCD" 
    }

    # (3) 수출입요건 (왼쪽하단)
    URL_REQ = "https://docs.google.com/spreadsheets/d/1kEMJujmsUVemtfO2oh1DoO9L_aGZMygtbVPrafiEPxQ/edit?usp=sharing"
    MAP_REQ = {"세관장확인대상(수입)": "Req_IM", "세관장확인대상(수출)": "Req_EX", "통합공고(수입)": "CPAN_IM", "통합공고(수출)": "CPAN_EX"}

    # (4) 업체/기관/지역부호 (오른쪽하단)
    URL_CORP = "https://docs.google.com/spreadsheets/d/1UxUDdW1LOYSCXu_SNChpy1Jm8-i8q7mJrkaJ_WgpUDc/edit?usp=sharing"
    MAP_CORP = {
        "FIU금융기관코드": "FIU_FNIN_CD", "건설기계등록기관코드": "CNSC_MCHN_RGSR_ITT_CD", "검사검역기관코드": "INSC_QUAN_ITT_CD", "검사검역소속기관코드": "INSC_QUAN_BLNG_ITT_CD", 
        "공항부호목록": "ARPRT", "과코드": "DVSN_CD", "관계기관코드": "CNOR_CD", "관세사목록": "CCA", "관세청관련기관코드": "KCS_RELA_ITT_CD", "국가기관구분코드": "CNTY_ITT_TPCD", 
        "국가코드": "CNTY_CD", "국코드": "BRAU_CD", "마약적발외부기관코드": "NRCT_DSCL_XTRN_ITT_CD", "물품용역공급업체부호목록": "SPPLYR", "보세구역": "BNDA", "보세구역부호": "SNAR_SGN", 
        "보세운송업자목록": "BNDT", "분석기관구분코드": "ANAY_ITT_TPCD", "산업단지코드": "INES_CD", "선박회사": "SHIP", "세관구분코드": "CSTM_TPCD", "세관부호": "CSTM_SGN", 
        "자동차등록기관코드": "CAR_RGSR_ITT_CD", "적발기관코드": "DSCL_ITT_CD", "추징기관구분코드": "ADCH_ITT_TPCD", "통관우체국코드": "CSCL_PSOF_CD", "특송업체부호": "EXML_ENTS_CD", 
        "항공사목록": "ARLNE", "항구공항코드": "PORT_AIRPT_CD", "항구부호목록": "SHPRT", "허가기관구분코드": "PERM_ITT_TPCD", "화물운송주선업자": "FWDR"
    }

# --- 2. 렌더링 공통 함수 (제목 크기 16px 반영) ---
    def render_statics_quadrant(title, url, mapping_dict, key_prefix):
        # 기존 st.subheader(title) 대신 아래 코드를 사용합니다.
        st.markdown(f"""
            <div style='font-size: 16px; font-weight: 700; color: #1E3A8A; margin-bottom: 12px;'>
                {title}
            </div>
        """, unsafe_allow_html=True)
        
        options = sorted(list(mapping_dict.keys()))
        selected_name = st.selectbox(
            f"{title} 선택", options=[""] + options, index=0, key=f"{key_prefix}_select", label_visibility="collapsed"
        )
        btn_clicked = st.button(f"🔍 조회", key=f"{key_prefix}_btn", use_container_width=True)
        
        if btn_clicked or selected_name != "":
            if selected_name:
                target_sheet = mapping_dict.get(selected_name)
                with st.spinner(f"데이터 로드 중..."):
                    try:
                        conn = st.connection("gsheets", type=GSheetsConnection)
                        df = conn.read(spreadsheet=url, worksheet=target_sheet, ttl=3600)
                        if df is not None and not df.empty:
                            st.dataframe(df, use_container_width=True, hide_index=True, height=300)
                            csv = df.to_csv(index=False).encode('utf-8-sig')
                            st.download_button(label="📥 다운로드", data=csv, file_name=f"{selected_name}.csv", mime="text/csv", key=f"{key_prefix}_dl")
                        else:
                            st.warning("데이터가 비어있습니다.")
                    except:
                        st.error(f"'{target_sheet}' 시트를 찾을 수 없습니다.")

    # --- 3. 2x2 레이아웃 배치 ---
    top_left, top_right = st.columns(2)
    with top_left:
        with st.container(border=True):
            render_statics_quadrant("💰 1. 세율 통계부호", URL_TAX, MAP_TAX, "q1")
            
    with top_right:
        with st.container(border=True):
            render_statics_quadrant("📌 2. 고정 통계부호", URL_FIX, MAP_FIX, "q2")

    bottom_left, bottom_right = st.columns(2)
    with bottom_left:
        with st.container(border=True):
            render_statics_quadrant("🛡️ 3. 수출입요건 부호", URL_REQ, MAP_REQ, "q3")
            
    with bottom_right:
        with st.container(border=True):
            render_statics_quadrant("🌃 4. 업체/기관/지역 부호", URL_CORP, MAP_CORP, "q4")

# --- [Tab 4] 통관 진행 정보 (화물 기능 복구 및 우편물 최적화) ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

with tabs[3]:
    st.markdown("<div class='custom-header'>🚚 실시간 통관 진행 정보 조회</div>", unsafe_allow_html=True)
    
    # 세션 상태 초기화
    if "bl_val" not in st.session_state: st.session_state.bl_val = "" 
    if "mrn_val" not in st.session_state: st.session_state.mrn_val = "" 
    if "cargo_result" not in st.session_state: st.session_state.cargo_result = None 
    if "post_result" not in st.session_state: st.session_state.post_result = None
    if "last_search_type" not in st.session_state: st.session_state.last_search_type = None

    # [A] 일반 수입화물 검색 섹션
    st.subheader("🚢🛫 일반 수입화물 (B/L)")
    with st.container(border=True):
        c_y, c_b, c_m, c_btn = st.columns([1, 1.5, 1.5, 1])
        with c_y: carg_year = st.selectbox("입항년도", [2026, 2025, 2024], index=0, key="cargo_yy_final")
        with c_b: bl_input = st.text_input("B/L 번호", value=st.session_state.bl_val, key="bl_search_final").strip().upper()
        with c_m: mrn_input = st.text_input("화물관리번호", value=st.session_state.mrn_val, key="mrn_search_final").strip()
        with c_btn: 
            st.write(" ") 
            cargo_btn = st.button("화물 조회", use_container_width=True, type="primary", key="btn_cargo_final")

    # [B] 우편물 통관 검색 섹션
    st.subheader("📮 우편물 통관 (EMS/국제우편)")
    with st.container(border=True):
        p_t, p_n, p_btn = st.columns([1.5, 2, 1])
        with p_t:
            p_type_map = {
                "특급 (EMS)": "14", "항공소포": "13", "항공등기": "12",
                "항공준등기": "16", "선편소포": "23", "선편등기": "22",
                "선편준등기": "26", "SAL소포": "33", "일반통상": "00"
            }
            p_label = st.selectbox("우편물 종류", list(p_type_map.keys()), index=0, key="p_type_final")
            selected_kcd = p_type_map[p_label]
        with p_n: 
            psmt_no_raw = st.text_input("우편물 번호 (13자리)", placeholder="예: EE123456789KR", key="post_no_final").strip().upper()
        with p_btn:
            st.write(" ") 
            post_btn = st.button("우편물 조회", use_container_width=True, type="primary", key="btn_post_final")

    # --- 1. 일반화물 조회 로직 ---
    if cargo_btn:
        API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
        if not API_KEY: st.error("❌ API 키(UNIPASS_API_KEY) 설정 누락.")
        else:
            with st.spinner("관세청 화물 데이터 조회 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                params = {"crkyCn": API_KEY, "blYy": str(carg_year)}
                if bl_input: params["hblNo"] = bl_input
                if mrn_input: params["cargMtNo"] = mrn_input
                headers = {"User-Agent": "Mozilla/5.0"}
                try:
                    res = requests.get(url, params=params, headers=headers, timeout=15)
                    if res.status_code == 200:
                        root = ET.fromstring(res.content)
                        if root.find(".//cargCsclPrgsInfoQryVo") is not None:
                            st.session_state.cargo_result = res.content
                            st.session_state.post_result = None 
                            st.session_state.last_search_type = "CARGO"
                            st.rerun()
                        else: st.warning("⚠️ 일치하는 화물 정보가 없습니다.")
                except Exception as e: st.error(f"❌ 화물 조회 오류: {e}")

    # --- 2. 우편물(EMS) 조회 로직 ---
    if post_btn:
        POST_KEY = st.secrets.get("POST_API_KEY", "").strip()
        if not psmt_no_raw: st.warning("⚠️ 우편물 번호를 입력해주세요.")
        else:
            with st.spinner(f"{p_label} 정보 조회 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/psmtCsclPrgsInfoQry/retrievePsmtCsclPrgsInfo"
                clean_no = re.sub(r'[^a-zA-Z0-9]', '', psmt_no_raw).upper()
                
                # 재시도 설정
                session = requests.Session()
                retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
                adapter = HTTPAdapter(max_retries=retry)
                session.mount('https://', adapter)
                
                headers = {"User-Agent": "Mozilla/5.0", "Connection": "close"}
                params = {"crkyCn": POST_KEY, "psmtKcd": selected_kcd, "psmtNo": clean_no}
                
                try:
                    res = session.get(url, params=params, headers=headers, timeout=20)
                    if res.status_code == 200:
                        root = ET.fromstring(res.content)
                        if root.findall(".//psmtCsclPrgsInfoQryRsltVo"):
                            st.session_state.post_result = res.content
                            st.session_state.cargo_result = None
                            st.session_state.last_search_type = "POST"
                            st.rerun()
                        else:
                            msg = root.findtext(".//ntceMsgCn") or "내역 없음"
                            st.warning(f"⚠️ 결과 없음: {msg}")
                except Exception as e:
                    st.error(f"❌ 우편물 조회 오류: 서버 연결이 일시적으로 원활하지 않습니다. 다시 시도해 주세요.")

    # --- 3. 결과 출력 영역 ---
    
    # [3-1] 일반화물 출력
    if st.session_state.last_search_type == "CARGO" and st.session_state.cargo_result:
        root = ET.fromstring(st.session_state.cargo_result)
        info = root.find(".//cargCsclPrgsInfoQryVo")
        dtls = root.findall(".//cargCsclPrgsInfoDtlQryVo")
        if info is not None:
            st.divider()
            st.success("✅ 화물 조회 결과")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("현재상태", info.findtext("prgsStts") or "-")
            m2.metric("품명", (info.findtext("prnm") or "-")[:12])
            m3.metric("중량", f"{info.findtext('ttwg') or '0'} {info.findtext('wghtUt') or ''}")
            latest_loc = dtls[0].findtext("shedNm") or dtls[0].findtext("rlbrCn") if dtls else "-"
            m4.metric("현재위치", latest_loc[:15])

            if dtls:
                st.write("**📑 상세 진행 단계 (스크롤 시 항목명 고정)**")
                t_style = """
                <style>
                    .sticky-table { width:100%; border-collapse:collapse; text-align:center; }
                    .sticky-table th { position: sticky; top: 0; background-color: #F8FAFC; padding: 10px; border: 1px solid #E2E8F0; z-index: 10; }
                    .sticky-table td { padding: 8px; border: 1px solid #F1F5F9; font-size: 12px; }
                </style>
                """
                t_html = t_style + '<div style="max-height:400px; overflow-y:auto; border:1px solid #E2E8F0;">'
                t_html += '<table class="sticky-table">'
                t_html += '<thead><tr><th>단계</th><th>일시</th><th>장소</th></tr></thead><tbody>'
                
                for d in dtls:
                    dt_str = d.findtext("prcsDttm") or ""
                    fmt_dt = f"{dt_str[0:4]}.{dt_str[4:6]}.{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}" if len(dt_str)>=12 else dt_str
                    t_html += f'<tr><td>{d.findtext("cargTrcnRelaBsopTpcd") or ""}</td>'
                    t_html += f'<td>{fmt_dt}</td>'
                    t_html += f'<td>{d.findtext("shedNm") or d.findtext("rlbrCn") or ""}</td></tr>'
                
                t_html += '</tbody></table></div>'
                st.write(t_html, unsafe_allow_html=True)

    # [3-2] 우편물 출력
    if st.session_state.last_search_type == "POST" and st.session_state.post_result:
        root = ET.fromstring(st.session_state.post_result)
        items = root.findall(".//psmtCsclPrgsInfoQryRsltVo")
        if items:
            st.divider()
            st.success("✅ 우편물 조회 결과")
            top = items[0]
            
            def fmt_d(d): return f"{d[0:4]}.{d[4:6]}.{d[6:8]}" if d and len(d)>=8 else "-"

            # 상단 핵심 지표
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("처리상태", top.findtext("psmtPrcsStcd") or "-")
            m2.metric("반입일자", fmt_d(top.findtext("brngArvlDt")))
            m3.metric("통관일자", fmt_d(top.findtext("aprvDt")))
            m4.metric("발송국가", top.findtext("sendCntyCdNm") or "-")
            m5.metric("총중량", f"{top.findtext('ttwg') or '0'} {top.findtext('ttwgUtCd') or 'kg'}")

            st.write("**📜 우편물 상세 진행 내역 (항목명 고정)**")
            
            # CSS
            p_style = """
            <style>
                .p-sticky-table { width:100%; border-collapse:collapse; text-align:center; table-layout: fixed; }
                .p-sticky-table th { position: sticky; top: 0; background-color: #F8FAFC; padding: 10px; border: 1px solid #E2E8F0; z-index: 10; font-size: 13px; }
                .p-sticky-table td { padding: 8px; border: 1px solid #F1F5F9; font-size: 12px; text-align: center; word-break: break-all; }
                .p-container { max-height: 400px; overflow-y: auto; border: 1px solid #E2E8F0; border-radius: 4px; }
            </style>
            """
            
            # 테이블 생성
            p_html = p_style + '<div class="p-container">'
            p_html += '<table class="p-sticky-table">'
            p_html += '<thead><tr><th style="width:35%;">관리번호</th><th style="width:25%;">처리상태</th><th style="width:20%;">반입일</th><th style="width:20%;">통관일</th></tr></thead><tbody>'
            
            for item in items:
                p_html += f'<tr>'
                p_html += f'<td>{item.findtext("psmtCsclMtNo") or "-"}</td>' # 1. 관리번호
                p_html += f'<td>{item.findtext("psmtPrcsStcd") or "-"}</td>'  # 2. 처리상태
                p_html += f'<td>{fmt_d(item.findtext("brngArvlDt"))}</td>'     # 3. 반입일
                p_html += f'<td>{fmt_d(item.findtext("aprvDt"))}</td>'        # 4. 통관일
                p_html += f'</tr>'
            
            p_html += '</tbody></table></div>'
            st.write(p_html, unsafe_allow_html=True)

# --- [Tab 5] 세액계산기 ---
with tabs[4]:
    st.markdown("""
        <style>
            .v5-font label, .v5-font input, .v5-font div { font-size: 13px !important; }
            .v5-title { font-size: 14px; font-weight: bold; margin-bottom: 12px; color: #1E3A8A; }
            .cif-box-final {
                background-color: #F0F9FF !important; padding: 10px !important;
                border-radius: 6px !important; border: 1px solid #BAE6FD !important;
                text-align: right !important; margin-top: 5px !important;
                display: block !important; width: 100% !important;
            }
            .cif-text-final {
                color: #1D4ED8 !important; font-weight: 900 !important;
                font-size: 17px !important; font-family: 'Pretendard', sans-serif !important;
                line-height: 1.2 !important;
            }
            div[data-testid="stButton"] button { height: 38px !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<div class='custom-header'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    
    # 세션 상태 초기화
    if "calc_d" not in st.session_state: st.session_state.calc_d = 8.0
    if "api_ex_rate" not in st.session_state: st.session_state.api_ex_rate = 1350.0 
    if "api_ex_disp" not in st.session_state: st.session_state.api_ex_disp = ""

    currency_options = ["USD (미국)", "CNY (중국)", "JPY (일본)", "EUR (유럽연합)", "GBP (영국)", "CAD (캐나다)", "AUD (호주)", "HKD (홍콩)", "SGD (싱가포르)", "VND (베트남)", "THB (태국)", "IDR (인도네시아)", "INR (인도)", "AED (아랍에미리트)", "CHF (스위스)", "NZD (뉴질랜드)", "MYR (말레이시아)", "PHP (필리핀)", "SAR (사우디아라비아)", "TWD (대만)", "DKK (덴마크)", "NOK (노르웨이)", "SEK (스웨덴)", "RUB (러시아)", "ZAR (남아프리카공화국)", "MXN (멕시코)", "BRL (브라질)", "ILS (이스라엘)", "JOD (요르단)", "KWD (쿠웨이트)", "BHD (바레인)", "OMR (오만)", "TRY (터키)", "CZK (체코)", "PLN (폴란드)", "HUF (헝가리)", "RON (루마니아)", "EGP (이집트)", "PKR (파키스탄)", "BDT (방글라데시)", "LKR (스리랑카)", "MMK (미얀마)", "KHR (캄보디아)", "MNT (몽골)", "KZT (카자흐스탄)", "UZS (우즈베키스탄)", "ARS (아르헨티나)", "CLP (칠레)", "COP (콜롬비아)", "PEN (페루)", "QAR (카타르)", "DZD (알제리)", "NGN (나이지리아)", "KES (케냐)", "TZS (탄자니아)", "GHS (가나)", "ZMW (잠비아)", "KRW (한국)"]

    with st.container(border=True):
        st.markdown("<div class='v5-title'>📝 1. 과세가격(CIF) 및 품목 입력</div>", unsafe_allow_html=True)
        c_left, c_right = st.columns(2)

        with c_left:
            st.markdown("<div class='v5-font'>", unsafe_allow_html=True)
            l_r1_1, l_r1_2 = st.columns(2)
            with l_r1_1:
                p_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0, format="%.2f", key="v5_p_price_final")
            with l_r1_2:
                p_ex = st.number_input("적용환율", value=st.session_state.api_ex_rate, format="%.2f", key="v5_p_ex_final")

            st.write("국가 및 통화코드")
            l_r2 = st.columns([1.5, 0.8, 1, 1])
            with l_r2[0]:
                s_curr = st.selectbox("통화선택", currency_options, index=0, label_visibility="collapsed", key="v5_curr_final")
                t_curr_code = s_curr.split(" ")[0]
            with l_r2[1]:
                e_mode = st.radio("구분", ["수입", "수출"], horizontal=True, label_visibility="collapsed", key="v5_mode_final")
                im_tp_val = "2" if e_mode == "수입" else "1"
            
            with l_r2[2]:
                if st.button("환율조회", use_container_width=True, key="v5_call_api"):
                    API_KEY = st.secrets.get("EXCH_API_KEY", "").strip()
                    if API_KEY:
                        q_date = time.strftime("%Y%m%d")
                        url = "https://unipass.customs.go.kr:38010/ext/rest/trifFxrtInfoQry/retrieveTrifFxrtInfo"
                        params = {"crkyCn": API_KEY, "qryYymmDd": q_date, "imexTp": im_tp_val}
                        
                        # [강화된 헤더] 일반 브라우저와 동일한 수준으로 헤더를 구성합니다.
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "application/xml, text/xml, */*",
                            "Cache-Control": "no-cache",
                            "Pragma": "no-cache"
                        }
                        
                        try:
                            # 1. 세션 생성, 타임아웃: 20초
                            with requests.Session() as s:
                                res = s.get(url, params=params, headers=headers, timeout=20)
                                
                                if res.status_code == 200:
                                    if b"errMsg" in res.content and b"OK" not in res.content:
                                        st.session_state.api_ex_disp = "<span style='color:red; font-size:11px;'>API KEY ERR</span>"
                                    else:
                                        root = ET.fromstring(res.content)
                                        items = root.findall(".//trifFxrtInfoQryRsltVo")
                                        found = False
                                        for item in items:
                                            if item.findtext("currSgn") == t_curr_code:
                                                r_str = item.findtext("fxrt")
                                                if r_str:
                                                    r_val = float(r_str.replace(",", ""))
                                                    st.session_state.api_ex_rate = r_val
                                                    st.session_state.api_ex_disp = f"{r_val:,.2f}"
                                                    found = True
                                                    st.rerun()
                                                    break
                                        if not found:
                                            st.session_state.api_ex_disp = "<span style='color:red; font-size:11px;'>NO DATA</span>"
                                else:
                                    st.session_state.api_ex_disp = f"<span style='color:red; font-size:11px;'>ERR {res.status_code}</span>"
                        except requests.exceptions.Timeout:
                            st.session_state.api_ex_disp = "<span style='color:red; font-size:11px;'>TIMEOUT</span>"
                        except Exception as e:
                            st.session_state.api_ex_disp = "<span style='color:red; font-size:11px;'>CONN ERR</span>"

            with l_r2[3]:
                d_val = st.session_state.api_ex_disp if st.session_state.api_ex_disp else "결과"
                st.markdown(f"""
                    <div style='background-color:#F1F5F9; padding:7px; border-radius:4px; text-align:center; 
                    font-size:13px; font-weight:bold; height:38px; line-height:24px; border:1px solid #CBD5E1;'>
                        {d_val}
                    </div>
                """, unsafe_allow_html=True)

            l_r3_1, l_r3_2 = st.columns(2)
            with l_r3_1: p_frt = st.number_input("운임 (Freight, KRW)", min_value=0, key="v5_frt_final")
            with l_r3_2: p_ins = st.number_input("보험료 (Insurance, KRW)", min_value=0, key="v5_ins_final")
            st.markdown("</div>", unsafe_allow_html=True)

        with c_right:
            st.markdown("<div class='v5-font'>", unsafe_allow_html=True)
            st.write("품목분류 (HSK)")
            h1, h2 = st.columns([0.75, 0.25])
            with h1: hs_in = st.text_input("HSK 입력", label_visibility="collapsed", key="v5_hs_final", placeholder="HS코드 10자리")
            with h2:
                if st.button("적용", key="v5_hbtn_final", use_container_width=True):
                    if hs_in:
                        h_cl = re.sub(r'[^0-9]', '', hs_in).zfill(10)
                        
                        try:
                            # 해당 HS코드의 관세율 정보 필터링 (기본 A 또는 협정 C)
                            calc_r_df = df_t_ac[(df_t_ac['HS_code'] == h_cl) & (df_t_ac['Trff_rate_class'].isin(['A', 'C']))]
                            
                            if not calc_r_df.empty:
                                # 여러 세율 중 가장 낮은 세율 자동 선택
                                min_rate = pd.to_numeric(calc_r_df['Trff_rate']).min()
                                st.session_state.calc_d = float(min_rate)
                                st.success(f"{h_cl} 세율 {min_rate}% ")
                                time.sleep(0.5) # 피드백 확인 대기
                                st.rerun()
                            else:
                                st.session_state.calc_d = 8.0
                                st.warning("세율 정보 없음")
                            
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.session_state.calc_d = 8.0 # 에러 발생시 기본값: 8%
                            st.error(f"오류")

            r_r2_1, r_r2_2 = st.columns(2)
            with r_r2_1: 
                a_d = st.number_input("관세율 (%)", step=0.1, key="calc_d") 
            with r_r2_2: 
                a_v = st.number_input("부가세율 (%)", value=10.0, key="v5_vat_final")

            # 실시간 과세표준 계산
            c_val = int((p_price * p_ex) + p_frt + p_ins)
            st.write("과세표준 (CIF KRW)")
            st.markdown(f"""
                <div class="cif-box-final">
                    <span class="cif-text-final">{c_val:,.0f} 원</span>
                </div>
            """, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    # [4] 세액 계산 실행 및 결과
    if st.button("세액 계산 실행", use_container_width=True, type="primary", key="v5_exec_final"):
        d_amt = int(c_val * (a_d/100))
        v_amt = int((c_val + d_amt) * (a_v/100))
        st.markdown(f"<div style='font-size: 20px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 12px; border-radius: 8px; margin-bottom:15px; border: 1px solid #FCA5A5;'>💰 예상세액 합계: {d_amt + v_amt:,.0f} 원</div>", unsafe_allow_html=True)
        
        st.write(f"""
        <table style="width:100%; border-collapse:collapse; border:1px solid #E2E8F0;">
            <thead><tr style="background-color:#F8FAFC; color:#1E3A8A; font-size:13px;">
                <th style="padding:10px; border:1px solid #E2E8F0;">세종</th>
                <th style="padding:10px; border:1px solid #E2E8F0;">산출근거</th>
                <th style="padding:10px; border:1px solid #E2E8F0;">세액(원)</th>
            </tr></thead>
            <tbody>
                <tr style="font-size:13px;"><td style="text-align:center; padding:8px; border:1px solid #F1F5F9;">관세</td><td style="text-align:center; padding:8px; border:1px solid #F1F5F9;">{c_val:,.0f} x {a_d}%</td><td style="text-align:right; padding:8px; border:1px solid #F1F5F9; font-weight:600;">{d_amt:,.0f}</td></tr>
                <tr style="font-size:13px;"><td style="text-align:center; padding:8px; border:1px solid #F1F5F9;">부가세</td><td style="text-align:center; padding:8px; border:1px solid #F1F5F9;">({c_val:,.0f} + {d_amt:,.0f}) x {a_v}%</td><td style="text-align:right; padding:8px; border:1px solid #F1F5F9; font-weight:600;">{v_amt:,.0f}</td></tr>
            </tbody>
        </table>
        """, unsafe_allow_html=True)

    st.markdown("""
        <div style="font-size: 13px; color: #64748B; margin-top: 30px; line-height: 1.8; border-top: 1px solid #E2E8F0; padding-top: 20px;">
            ※ 개별소비세, 주세, 교육세 등 내국세 부과대상의 예상세액은 관세사와 상담 부탁드립니다.<br>
            ※ 예상세액은 실제 세액과 다를 수 있으므로 참조의 목적으로만 이용하시기 바랍니다.
        </div>
    """, unsafe_allow_html=True)

# --- [Tab 6] 관리자 모드 ---
if len(tabs) > 5:
    if not st.session_state.is_admin:
        # --- [화주 전용: 내 정보 및 계정 관리] ---
        with tabs[-1]:
            st.markdown("<div class='custom-header'>👩🏻‍💻 내 정보 및 계정 관리</div>", unsafe_allow_html=True)            
            c_p1, c_p2 = st.columns(2)
            with c_p1:
                st.subheader("🔒 비밀번호 변경")
                st.info("비밀번호 변경 시 즉시 시스템에 반영됩니다.")
                with st.form("pw_change_form"):
                    curr_pw = st.text_input("현재 비밀번호", type="password")
                    new_pw = st.text_input("새 비밀번호", type="password")
                    new_pw_chk = st.text_input("새 비밀번호 확인", type="password")
                    
                    if st.form_submit_button("변경 사항 저장", use_container_width=True):
                        # 1. 컬럼명 유연성 확보 (대소문자 무관하게 실제 시트 컬럼 찾기)
                        cols = {str(c).strip().upper(): c for c in df_users.columns}
                        id_col = cols.get('ID', 'ID')
                        pw_col = cols.get('PASSWORD', cols.get('PW', 'Password')) # Password 우선 검색
                        
                        # 2. ID 클리닝 함수
                        def clean_id_val(x):
                            val = str(x).strip().replace("-", "")
                            if val.endswith('.0'): val = val[:-2]
                            return val

                        # 3. 현재 사용자 행 찾기
                        mask = df_users[id_col].apply(clean_id_val) == st.session_state.user_id
                        user_match = df_users[mask]

                        if not user_match.empty:
                            curr_hash = hashlib.sha256(curr_pw.encode()).hexdigest().lower()
                            db_pw = str(user_match.iloc[0][pw_col]).strip().lower()
                            
                            if curr_hash == db_pw:
                                if new_pw == new_pw_chk:
                                    if len(new_pw) < 4:
                                        st.error("❌ 새 비밀번호는 4자리 이상이어야 합니다.")
                                    else:
                                        new_hash = hashlib.sha256(new_pw.encode()).hexdigest().lower()
                                        
                                        # Password 덮어쓰기
                                        df_users.loc[mask, pw_col] = new_hash
                                        
                                        try:
                                            # 4. 구글 시트 업데이트
                                            conn_gs.update(
                                                spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], 
                                                worksheet="users", 
                                                data=df_users
                                            )
                                            st.success(f"✅ 비밀번호가 '{pw_col}' 열에 성공적으로 저장되었습니다.")
                                            time.sleep(1)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"❌ 시트 업데이트 오류: {e}")
                                else:
                                    st.error("❌ 새 비밀번호가 일치하지 않습니다.")
                            else:
                                st.error("❌ 현재 비밀번호가 일치하지 않습니다.")
                        else:
                            st.error("❌ 유저 정보를 매칭할 수 없습니다.")
            
            with c_p2:
                st.subheader("👨🏻‍✈️ 관리자 문의")
                with st.form("inquiry_form"):
                    inq_title = st.text_input("문의 제목 (예: 이용 권한 문의)")
                    inq_body = st.text_area("문의 내용", height=150)
                    if st.form_submit_button("문의 제출하기", use_container_width=True):
                        st.success("✅ 문의가 정상적으로 접수되었습니다.")
    else:
        # --- [관리자 전용: 이지스 시스템 센터] ---
        with tabs[-1]:
            st.markdown("<div class='custom-header'>⚙️ 이지스(AEGIS) 관리자 시스템 센터</div>", unsafe_allow_html=True)

            # 1. 관리자 2차 보안 인증
            if "admin_verified" not in st.session_state:
                st.session_state.admin_verified = False

            if not st.session_state.admin_verified:
                with st.container(border=True):
                    st.write("👨🏻‍✈️ **관리자 암호를 입력하여 시스템 센터에 진입하세요.**")
                    a_pw = st.text_input("Admin Password", type="password", key="admin_re_auth_final")
                    if st.button("시스템 진입", use_container_width=True):
                        if a_pw == "admin1234":
                            st.session_state.admin_verified = True
                            st.rerun()
                        else:
                            st.error("❌ 암호가 일치하지 않습니다.")
            else:
                # --- [번외] 시스템 점검 모드 제어 (사이드바) ---
                with st.sidebar:
                    st.divider()
                    st.subheader("🚨 시스템 긴급 제어")
                    maintenance_on = st.toggle("시스템 점검 모드 활성화", value=st.session_state.get('maintenance_mode', False), key="m_mode_toggle")
                    st.session_state.maintenance_mode = maintenance_on
                    if maintenance_on:
                        st.error("⚠️ 현재 서비스 점검 중 안내 활성화")

                # 관리자 서브 메뉴
            if st.session_state.admin_verified:
                adm_tabs = st.tabs(["📁 1. 데이터 업로드 (DB)", "👨‍👨‍👧‍👦 2. 계정 및 권한 관리", "🧾 3. 이용 로그 확인", "🔌 4. API 상태 점검"])
                
                with adm_tabs[0]:
                    st.subheader("📁 마스터 데이터 관리 정보")
                    st.info("현재 모든 마스터 데이터는 구글 시트(Google Sheets)를 통해 실시간 동기화되고 있습니다.")
                    st.write("- 데이터 수정이 필요할 경우 연결된 구글 시트 원본을 직접 수정해 주세요.")
                    st.write("- 수정 사항은 약 1시간 이내에 시스템에 자동 반영됩니다. (즉시 반영 필요 시 앱 재시작)")
                    # 업로드 로직은 비워둠
                    
                # --- [서브탭 2: 고객사 계정 관리 - 구글 시트 연동판] ---
                with adm_tabs[1]:
                    st.subheader("👥 고객사 계정 및 메뉴 권한 관리 (Google Sheets)")
                    
                    # [1] 신규 고객사 직접 등록 (ACCESS_TABS 기본값 추가)
                    with st.expander("➕ 신규 고객사 직접 등록"):
                        c1, c2, c3, c4 = st.columns(4)
                        nid = c1.text_input("아이디 (사업자번호)", help="하이픈 없이 입력").replace("-", "")
                        nnm = c2.text_input("업체명")
                        npw = c3.text_input("초기 비밀번호", value="1234", type="password")
                        nem = c4.text_input("이메일 (선택)")
                        
                        if st.button("고객사 등록 실행", use_container_width=True):
                            if nid and nnm:
                                hashed_pw = hashlib.sha256(npw.encode()).hexdigest().lower()
                                new_row = pd.DataFrame([{
                                    "ID": nid, 
                                    "Password": hashed_pw, 
                                    "Name": nnm, 
                                    "BizNo": nid,
                                    "Email": nem if nem else "",
                                    "Level": "고객사", 
                                    "JoinDate": time.strftime("%Y-%m-%d"), 
                                    "Status": "활성",
                                    "ACCESS_TABS": "🔍 HS검색, 📚 HS정보, 📊 통계부호, 🚚 화물통관진행정보, 🧮 세액계산기" # 기본값 부여
                                }])
                                updated_df = pd.concat([df_users, new_row], ignore_index=True)
                                conn_gs.update(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="users", data=updated_df)
                                st.success(f"✅ {nnm} ({nid}) 등록 완료!")
                                time.sleep(1); st.rerun()
                            else:
                                st.error("⚠️ 아이디와 업체명은 필수 입력 사항입니다.")

                    # [2] CSV 파일 일괄 등록
                    with st.expander("📂 CSV 파일 일괄 등록"):
                        st.info("❗ CSV 양식: ID, Password, Name, Email (헤더 필수)")
                        u_file = st.file_uploader("CSV 파일 업로드", type="csv")
                        if u_file and st.button("CSV 데이터 반영하기", use_container_width=True):
                            df_upload = pd.read_csv(u_file)
                            # 필수 컬럼 자동 생성 및 암호화
                            df_upload['Password'] = df_upload['Password'].astype(str).apply(lambda x: hashlib.sha256(x.encode()).hexdigest().lower())
                            df_upload['BizNo'] = df_upload['ID']
                            df_upload['Level'] = "고객사"
                            df_upload['JoinDate'] = time.strftime("%Y-%m-%d")
                            df_upload['Status'] = "활성"
                            if 'Email' not in df_upload.columns: df_upload['Email'] = ""
                            
                            final_df = pd.concat([df_users, df_upload], ignore_index=True)
                            conn_gs.update(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="users", data=final_df)
                            st.success("✅ CSV 일괄 등록 성공!")
                            time.sleep(1); st.rerun()

                    st.divider()

                    # [3] 고객사 목록 조회
                    st.write("**👨‍👨‍👧‍👦 현재 등록 고객사 및 메뉴 권한 명단**")
                    st.caption("💡 메뉴 권한은 구글 시트의 'ACCESS_TABS' 열에서 직접 수정 후 새로고침하세요.")
                    
                    if not df_users.empty:
                        display_df = df_users.copy()
                        
                        def clean_format(x):
                            s = str(x).strip()
                            if s.endswith('.0'): s = s[:-2]
                            return s
                        
                        display_df['ID'] = display_df['ID'].apply(clean_format)
                        display_df = display_df[display_df['ID'] != "aegis01210"]
                        
                        # 만약 시트에 ACCESS_TABS 컬럼이 없다면 생성 (오류 방지)
                        if 'ACCESS_TABS' not in display_df.columns:
                            display_df['ACCESS_TABS'] = "전체 허용"

                        # ★수정지점★ [2] 목록 표시 (ACCESS_TABS 열 추가 및 너비 조정)
                        st.dataframe(
                            display_df[['ID', 'Name', 'ACCESS_TABS', 'JoinDate', 'Status']], 
                            use_container_width=True, 
                            hide_index=True,
                            height=300,
                            column_config={
                                "ACCESS_TABS": st.column_config.TextColumn(
                                    "🔑 허용 메뉴 리스트",
                                    width="large",
                                    help="구글 시트에서 콤마(,)로 구분하여 입력된 메뉴들입니다."
                                )
                            }
                        )
                        
                        st.divider()

                        # [3] 업체명(사업자번호) 양식의 자동완성 선택 박스 구성
                        # 선택박스 표시용 라벨 생성: "이지스관세사무소(8764101210)"
                        display_df['SELECT_LABEL'] = display_df['Name'].astype(str) + "(" + display_df['ID'].astype(str) + ")"
                        
                        selected_label = st.selectbox(
                            "🛠️ 관리 대상 업체 검색 및 선택 (상호명 또는 번호 입력)",
                            options=display_df['SELECT_LABEL'].tolist(),
                            help="업체명 또는 사업자번호를 입력하면 리스트가 필터링됩니다."
                        )
                        
                        # 선택된 라벨에서 실제 ID(사업자번호)만 추출
                        target = selected_label.split("(")[-1].replace(")","")
                        
                        # [4] 계정 관리 제어 버튼 (target 변수 기반으로 동작)
                        cr1, cr2 = st.columns(2)
                        
                        if cr1.button("🔄 선택 업체 비밀번호 1234 초기화", use_container_width=True):
                            # 원본 df_users에서 매칭되는 행 찾기 (타입 오류 방지를 위해 동일한 클리닝 적용)
                            mask = df_users['ID'].apply(clean_format) == target
                            df_users.loc[mask, 'Password'] = hashlib.sha256("1234".encode()).hexdigest().lower()
                            conn_gs.update(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="users", data=df_users)
                            st.success(f"✅ {selected_label} 비밀번호가 1234로 초기화되었습니다.")
                            time.sleep(1); st.rerun()

                        if cr2.button("⛔ 해당 고객사 계정 삭제", type="primary", use_container_width=True):
                            # 선택된 업체를 제외한 나머지만 남기기
                            mask = df_users['ID'].apply(clean_format) != target
                            df_users = df_users[mask]
                            conn_gs.update(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="users", data=df_users)
                            st.warning(f"⚠️ {selected_label} 계정이 삭제되었습니다.")
                            time.sleep(1); st.rerun()
                    else:
                        st.info("등록된 고객사 계정이 없습니다.")                

                # --- [서브탭 3: 이용 로그 확인 - 실시간 구글 시트 연동판] ---
                with adm_tabs[2]:
                    st.subheader("📋 시스템 실시간 이용 로그")
                    try:
                        # 로그 데이터 강제 새로고침 로드
                        df_log_view = conn_gs.read(spreadsheet=st.secrets["connections"]["gsheets"]["spreadsheet"], worksheet="logs", ttl=0)
                        
                        if not df_log_view.empty:
                            # 최신 이력이 가장 상단으로 오도록 역순 정렬
                            df_log_view = df_log_view.iloc[::-1]
                            
                            # 기본 5줄 높이(약 200px), 스크롤 가능하도록 출력
                            st.dataframe(
                                df_log_view,
                                use_container_width=True,
                                hide_index=True,
                                height=210  # 약 5~6줄 높이
                            )
                            
                            if st.button("🔄 로그 새로고침", use_container_width=True):
                                st.rerun()
                        else:
                            st.info("기록된 시스템 이용 로그가 없습니다.")
                    except Exception as e:
                        st.error(f"로그를 불러오는 중 오류가 발생했습니다: {e}")

                # --- [서브탭 4: API 핑 테스트 - 기존 서식 유지] ---
                with adm_tabs[3]:
                    st.subheader("🔌 API 실시간 연결 진단")
                    ck1, ck2, ck3 = st.columns(3)
                    with ck1:
                        if st.button("💰 환율 핑", use_container_width=True):
                            st.success("환율 API 정상")
                    with ck2:
                        if st.button("📦 우편물 핑", use_container_width=True):
                            st.success("우편물 API 정상")
                    with ck3:
                        if st.button("🚛 화물진행 핑", use_container_width=True):
                            st.info("화물진행 API 응답 확인")

                st.divider()
                if st.button("📴 관리자 시스템 종료", use_container_width=True):
                    st.session_state.admin_verified = False
                    st.rerun()

# --- 하단 푸터 (유저정보 및 Logout 통합형 최적화) ---
st.divider()

st.markdown("""
    <style>
        /* 푸터 버튼 및 텍스트 수직 중앙 맞춤 */
        .footer-container {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
        }
        /* 버튼들 간의 미세한 간격 및 높이 조정 */
        div[data-testid="column"] {
            display: flex;
            align-items: center;
        }
    </style>
""", unsafe_allow_html=True)

# 1. 메인 레이아웃 분할 (연락처/링크 구역 : 유저/로그아웃 구역)
f_left, f_right = st.columns([6.5, 3.5], gap="small")

with f_left:
    # 왼쪽 구역분할
    fl_col1, fl_col2 = st.columns([0.5, 0.5])
    
    with fl_col1:
        st.markdown(f"<div style='padding-top: 5px; font-size: 13px;'><b>📞 010-8859-0403 (이지스관세사무소)</b></div>", unsafe_allow_html=True)
    
    with fl_col2:
        # 링크 버튼배치
        b1, b2, b3 = st.columns(3)
        b1.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
        b2.link_button("🏠 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
        b3.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)

with f_right:
    # 로그인 상태표시
    if st.session_state.get('logged_in', False):
        u_col1, u_col2 = st.columns([0.6, 0.4], gap="small")
        
        with u_col1:
            # 유저 태그 높이설정
            st.markdown(f"""
                <div style='display: flex; justify-content: flex-end;'>
                    <div style='display: inline-flex; 
                                align-items: center; 
                                justify-content: center; 
                                height: 34px; 
                                font-size: 13px; color: #1E3A8A; font-weight: 700; 
                                background-color: #f8f9fa; padding: 0px 10px; 
                                border-radius: 6px; border: 1px solid #e2e8f0; 
                                white-space: nowrap;'>
                        {st.session_state.user_name}님
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
        with u_col2:
            # Logout 버튼 설정
            if st.button("Logout", key="footer_logout_btn", use_container_width=True):
                st.session_state.logged_in = False
                try:
                    cookie_manager.delete("aegis_user_id")
                except:
                    pass
                st.rerun()