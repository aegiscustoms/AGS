import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import re
import io

# --- 1. 초기 환경 설정 및 DB 연결 ---
DB_FILE = "customs_master.db"

def get_db_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_db_connection()
    # 국내 마스터 정보
    conn.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    # 세율 정보
    conn.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    # 수입요건 정보
    conn.execute("CREATE TABLE IF NOT EXISTS requirements (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    # 감면/면세 정보
    conn.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, description TEXT, rate TEXT)")
    conn.commit()
    conn.close()

init_db()

# API 설정
try:
    GOOGLE_API_KEY = st.secrets["GEMINI_KEY"]
except:
    GOOGLE_API_KEY = "YOUR_API_KEY_HERE" # 로컬 테스트 시 여기에 입력

genai.configure(api_key=GOOGLE_API_KEY)
# 최신 2.0 모델 사용 (속도 및 추론 능력 최상)
model = genai.GenerativeModel('gemini-2.0-flash')

# 웹페이지 설정
st.set_page_config(page_title="HS 통합 AI 검색 포털", layout="wide", initial_sidebar_state="collapsed")

# --- 2. 공통 함수: 상세 정보 표시 ---
def display_hsk_details(hsk_code):
    hsk_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = get_db_connection()
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{hsk_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM requirements WHERE hs_code = '{hsk_clean}'", conn)
    conn.close()

    if not master.empty:
        st.success(f"### ✅ [{hsk_clean}] {master['name_kr'].values[0]}")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info("**기본 정보**")
            st.write(f"영문명: {master['name_en'].values[0]}")
        with col2:
            st.info("**적용 세율**")
            if not rates.empty: st.table(rates)
            else: st.write("확인된 세율 정보가 없습니다.")
        with col3:
            st.info("**수입 요건**")
            if not reqs.empty: st.table(reqs)
            else: st.write("세관장확인 대상이 아닙니다.")
        
        # AI 요약 버튼
        if st.button(f"🔍 AI 실무 가이드 생성 ({hsk_clean})"):
            context = f"HSK: {hsk_clean}, 품명: {master['name_kr'].values[0]}, 세율: {rates.to_dict()}, 요건: {reqs.to_dict()}"
            prompt = f"당신은 전문 관세사입니다. 다음 데이터를 바탕으로 실무자가 주의해야 할 점을 3줄로 요약해줘: {context}"
            response = model.generate_content(prompt)
            st.chat_message("assistant").write(response.text)
    else:
        st.warning(f"DB에 {hsk_clean}에 대한 상세 정보가 없습니다. (데이터 업데이트가 필요할 수 있습니다.)")

# --- 3. UI 메인 레이아웃 ---
st.title("🚢 HS 통합 AI 검색 포털")
st.markdown("이미지, HSK 코드, 또는 품명을 입력하세요. AI가 실시간으로 분석하고 DB 정보를 연결합니다.")

tab1, tab2, tab3, tab4 = st.tabs(["🔍 국내 통합 검색", "🌎 세계 HS/세율", "📊 통계/감면 부호", "⚙️ 관리자"])

# --- [Tab 1] 국내 통합 검색 (가장 중요한 유저 편의 모듈) ---
with tab1:
    col_in1, col_in2 = st.columns([2, 1])
    with col_in1:
        u_input = st.text_input("검색어 (HSK 10자리, 4자리, 또는 품명)", placeholder="예: 8703, 노트북, 화장품...")
    with col_in2:
        u_img = st.file_uploader("이미지 업로드 분석", type=["jpg", "png", "jpeg"])

    if st.button("분석 및 검색 시작", use_container_width=True):
        if u_img:
            st.subheader("📸 AI 이미지 분석 결과")
            with st.spinner("AI가 이미지를 판정 중입니다..."):
                img = Image.open(u_img)
                prompt = "당신은 관세사입니다. 이 물품의 용도, 재질, 기능을 분석하여 가장 적합한 HSK 10자리 코드를 제안하세요. 마지막에 '추천코드: [숫자10자리]' 형식을 포함하세요."
                response = model.generate_content([prompt, img])
                st.write(response.text)
                found = re.findall(r'\d{10}', response.text)
                if found:
                    st.divider()
                    display_hsk_details(found[0])
        elif u_input:
            if u_input.isdigit() and len(u_input) >= 4:
                display_hsk_details(u_input)
            else:
                conn = get_db_connection()
                search_res = pd.read_sql(f"SELECT hs_code, name_kr FROM hs_master WHERE name_kr LIKE '%{u_input}%' LIMIT 10", conn)
                conn.close()
                if not search_res.empty:
                    for i, r in search_res.iterrows():
                        with st.expander(f"[{r['hs_code']}] {r['name_kr']}"):
                            display_hsk_details(r['hs_code'])
                else:
                    st.info("DB 검색 결과가 없습니다. AI 추론을 시작합니다.")
                    res = model.generate_content(f"관세사로서 '{u_input}'의 예상 HS코드를 제안해줘.")
                    st.write(res.text)

# --- [Tab 2] 세계 HS/세율 (4번 모듈: 해외 사이트 정보 분석) ---
with tab2:
    st.header("🌎 세계 HS 및 실시간 세율 가이드")
    country = st.selectbox("조회 대상 국가", ["미국(USA)", "유럽연합(EU)", "베트남(VN)", "중국(CN)", "일본(JP)"])
    world_hs = st.text_input("해당국 HS코드", placeholder="예: 8517.13")
    
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        st.markdown(f"**1. 해외 세관 사이트에서 정보 복사**")
        raw_text = st.text_area("해외 사이트 결과 텍스트 붙여넣기", height=200)
    with col_w2:
        st.markdown(f"**2. 또는 화면 캡처본(이미지) 업로드**")
        world_img = st.file_uploader("해외 사이트 캡처 업로드", type=["jpg", "png"])

    if st.button("AI 해외 세율 정밀 분석", use_container_width=True):
        with st.spinner("다국어 세율표 분석 중..."):
            world_prompt = f"당신은 글로벌 관세사입니다. {country}의 HS코드 {world_hs} 정보를 분석하여 기본세율, WTO세율, FTA세율을 표로 정리하세요."
            inputs = [world_prompt]
            if raw_text: inputs.append(raw_text)
            if world_img: inputs.append(Image.open(world_img))
            response = model.generate_content(inputs)
            st.markdown(response.text)

# --- [Tab 3] 통계/감면 부호 (3번 모듈: 부가 검색) ---
with tab3:
    st.header("📊 무역/면세/감면 부호 조회")
    q = st.text_input("부호 또는 명칭 입력", placeholder="예: Y8101, 항공기, 부가세면세...")
    if q:
        conn = get_db_connection()
        res = pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{q}%' OR description LIKE '%{q}%' LIMIT 20", conn)
        conn.close()
        st.dataframe(res, use_container_width=True)

# --- [Tab 4] 관리자 (1인 사업자를 위한 DB 업데이트) ---
with tab4:
    st.header("⚙️ 데이터베이스 관리")
    if st.text_input("관리자 암호", type="password") == "1234":
        st.success("인증 완료")
        mode = st.selectbox("업로드 종류", ["HS마스터", "세율", "수입요건", "감면부호"])
        up_file = st.file_uploader(f"{mode} CSV 파일 선택", type="csv")
        
        if up_file and st.button("데이터 즉시 업데이트"):
            df = pd.read_csv(up_file)
            conn = get_db_connection()
            if mode == "HS마스터":
                df_map = df[['HS부호', '한글품목명', '영문품목명']].copy()
                df_map.columns = ['hs_code', 'name_kr', 'name_en']
                df_map.to_sql('hs_master', conn, if_exists='replace', index=False)
            elif mode == "세율":
                df_map = df[['품목번호', '관세율구분', '관세율']].copy()
                df_map.columns = ['hs_code', 'type', 'rate']
                df_map.to_sql('rates', conn, if_exists='replace', index=False)
            elif mode == "수입요건":
                df_map = df[['HS부호', '신고인확인법령코드명', '요건승인기관코드명', '요건확인서류명']].copy()
                df_map.columns = ['hs_code', 'law', 'agency', 'document']
                df_map.to_sql('requirements', conn, if_exists='replace', index=False)
            elif mode == "감면부호":
                df_map = df.iloc[:, [0, 1, 2]] # 첫 세 열 (코드, 내용, 율)
                df_map.columns = ['code', 'description', 'rate']
                df_map.to_sql('exemptions', conn, if_exists='replace', index=False)
            conn.close()
            st.balloons()
            st.success("데이터베이스가 최신화되었습니다!")

# --- 하단 안내 (마케팅 및 가격 정책) ---
st.divider()
st.caption("💰 연간 구독료: 55,000원 | 당사 통관 거래처는 전액 무료 배포")
st.caption("📢 본 시스템은 보조 도구입니다. 정확한 신고는 반드시 관세사와 상담하세요.")