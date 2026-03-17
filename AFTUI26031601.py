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
import time

# --- [AFTUI26031111] 전역 디자인 설정 (테이블 강제 서식 삭제본) --- #변경내역★★
st.set_page_config(page_title="AEGIS - 전문 관세 행정 서비스", layout="wide") #변경내역★★

TITLE_FONT_SIZE = "16px" #변경내역★★
CONTENT_FONT_SIZE = "13px" #변경내역★★

st.markdown(f"""
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        * {{ font-family: 'Pretendard', sans-serif; }}
        .stApp {{ background-color: #FFFFFF; }}
        
        /* 탭 내비게이션 디자인 */
        .stTabs [data-baseweb="tab-list"] {{ gap: 24px; background-color: #FFFFFF; border-bottom: 1px solid #E2E8F0; }}
        .stTabs [data-baseweb="tab"] {{ height: 50px; color: #64748B; font-size: 15px; font-weight: 500; }}
        .stTabs [aria-selected="true"] {{ color: #1E3A8A !important; border-bottom: 2px solid #1E3A8A !important; }}

        /* 섹션 헤더 디자인 */
        .custom-header {{ 
            font-size: {TITLE_FONT_SIZE} !important; 
            font-weight: 700; 
            color: #1E3A8A; 
            border-left: 4px solid #1E3A8A; 
            padding-left: 12px; 
            margin: 15px 0; 
        }}

        /* 버튼 디자인 */
        .stButton > button {{
            background-color: #1E3A8A !important;
            color: white !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
            width: 100% !important;
        }}

        /* 참고: 테이블 관련 클래스(.full-width-table 등)는 개별 탭에서 개별 정의하여 사용 예정 */
    </style>
""", unsafe_allow_html=True) #변경내역★★

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
    # [1] 마스터 지식 DB 설정 (customs_master.db)
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    
    # 마스터 및 요건 정보
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rate_names (code TEXT, h_name TEXT)") # 세율명칭 매핑용
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_export (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    
    # 통계부호 (2026 규격)
    c.execute("CREATE TABLE IF NOT EXISTS stat_gani (gani_hs TEXT, gani_name TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_reduction (code TEXT, content TEXT, rate TEXT, after_target TEXT, installment_months TEXT, installment_count TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_vat_exemption (name TEXT, type_name TEXT, code TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_internal_tax (item_name TEXT, tax_rate TEXT, type_code TEXT, type_name TEXT, tax_kind_code TEXT, unit TEXT, tax_base_price TEXT, agri_tax_yn TEXT)")
    
    conn.commit()
    conn.close()

    # [2] 사용자 인증 DB 설정 (users.db) #변경내역★★
    conn_auth = sqlite3.connect("users.db")
    ca = conn_auth.cursor()
    ca.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, 
                pw TEXT, 
                name TEXT, 
                is_approved INTEGER DEFAULT 0, 
                is_admin INTEGER DEFAULT 0)""")
    
    # 관리자 계정 초기 생성 (dlwltm2025@)
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    ca.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 (원본 로직) ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top:100px;'><h1 style='color:#1E3A8A; font-size:42px; font-weight:800;'>AEGIS</h1></div>", unsafe_allow_html=True) #변경내역★★
    cl1, cl2, cl3 = st.columns([1, 1.4, 1])
    with cl2:
        with st.form("login_form"):
            l_id = st.text_input("아이디"); l_pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인"):
                conn = sqlite3.connect("users.db")
                res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
                conn.close()
                if res and res[0] == 1:
                    st.session_state.logged_in = True; st.session_state.user_id = l_id; st.session_state.is_admin = bool(res[1]); st.rerun()
    st.stop()

st.sidebar.markdown(f"### 👤 {st.session_state.user_id}") #변경내역★★
if st.sidebar.button("로그아웃"): st.session_state.logged_in = False; st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (전문 리포트 양식 복원 및 이미지 메일 첨부) --- #변경내역★★
with tabs[0]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A; margin-bottom: 10px;'>🔍 AI 기반 HS Code 분석 리포트</div>", unsafe_allow_html=True)
    
    # 세션 상태 초기화 (리포트 결과 및 이미지 데이터 유지)
    if "ai_report_done" not in st.session_state: st.session_state.ai_report_done = False
    if "last_report_text" not in st.session_state: st.session_state.last_report_text = ""
    if "last_input_summary" not in st.session_state: st.session_state.last_input_summary = ""
    if "img_analysis_text" not in st.session_state: st.session_state.img_analysis_text = ""
    if "last_img_bytes" not in st.session_state: st.session_state.last_img_bytes = None

    # [1] 입력창 세분화 레이아웃
    with st.container(border=True):
        st.markdown("**📋 물품 상세 정보 입력 (하나의 항목만 입력해도 조회가 가능합니다)**")
        
        c1, c2 = st.columns([0.4, 0.6])
        with c1:
            uploaded_file = st.file_uploader("📸 물품 이미지 업로드", type=["jpg", "jpeg", "png"], key="hs_img_v2")
            if uploaded_file:
                st.image(uploaded_file, caption="업로드된 이미지", use_container_width=True)
                st.session_state.last_img_bytes = uploaded_file.getvalue() # 메일 첨부용 저장
        
        with c2:
            p_name = st.text_input("1. 품명 (기본)", key="p_name")
            p_material = st.text_input("2. 재질", key="p_material")
            p_usage = st.text_input("3. 용도", key="p_usage")

        c3, c4, c5 = st.columns(3)
        with c3: p_function = st.text_input("4. 기능 및 작동원리", key="p_function")
        with c4: p_component = st.text_input("5. 성분 및 함량", key="p_component")
        with c5: p_spec = st.text_input("6. 규격 및 사양", key="p_spec")
        
        p_composition = st.text_input("7. 구성요소 (Set 여부)", key="p_composition")

    # [2] 분석 실행 로직
    if st.button("AI 분석 리포트 생성", use_container_width=True, type="primary"):
        # 입력 정보 정리 (리포트 1번 항목 출력용)
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
            st.warning("⚠️ 분석을 위해 정보를 입력해주세요.")
        else:
            with st.spinner("AI 전문 관세사가 상세 분석 중입니다..."):
                try:
                    model = genai.GenerativeModel('gemini-2.0-flash')
                    
                    # [복원] 관세사 실무 중심 고도화 프롬프트 및 양식 지정
                    prompt = f"""당신은 30년 경력의 베테랑 관세사입니다. 제공된 정보를 바탕으로 다음 '제미나이 리포트 양식'에 맞춰 분석 리포트를 작성하세요.

[분류 원칙 및 참고사항]
- 4단위 호의 용어(Heading)를 우선 확정할 것.
- 관련 부/류의 주(Note) 규정과 관세율표 해설서 총설 및 호해설 내용을 반드시 검토할 것.
- 통칙 제1호(호의 용어 및 주 규정)를 최우선 적용하고, 제2호부터 제6호까지 논리적으로 순차 적용할 것.
- 만약 예상되는 4단위 호가 경합될 경우, 본질적인 특성을 부여하는 성분/재질/용도/기능/구성요소에 따라 확정할 것.

[리포트 출력 양식]
AI 분석 리포트
1. 입력정보
   1) 이미지 해석: (이미지가 있다면 시각적 특징과 식별 포인트 간략히 서술, 없으면 '정보 없음')
{input_summary}

2. 추천 HS Code (10자리): XXXX.XX-XXXX (예상 확률 %) 
   - 4단위 HS Code: XXXX [호의 용어 한글(영문)]
   - 6단위 HS Code: XXXX.XX [소호의 용어]
   - 10단위 HS Code: XXXX.XX-XXXX [최종 품목명]

3. 분류 근거 (다음 3개 문단 구조를 반드시 지킬 것)
   - 물품이 속하는 부/류의 분류 규정(주 규정) 및 해설서 총설의 핵심 내용 서술
   - 확정된 4단위 호의 용어 설명 및 호해설서에서 해당 물품을 분류할 수 있는 구체적 근거 예시 인용
   - 물품의 특징(재질/기능 등)을 요약하고 통칙 제1호 및 제6호를 적용하여 최종 번호가 산출되는 논리 결론

4. 예상 경합세번 (추천 번호의 확률이 100%가 아닌 경우만 표시하고, 좌측부터 상위 3순위까지 추천하되 3순위가 낮으면 2순위까지만)
   - 6단위 경합세번: XXXX.XX(00%), XXXX.XX(00%)
   - 10단위 경합세번: XXXX.XX-XXXX(00%), XXXX.XX-XXXX(00%)

※ 주의사항 ※ 
- 본 리포트는 제공된 정보에 기초하여 작성되었으며, 실제 물품의 상세 스펙에 따라 HS Code가 변경될 수 있습니다.
- 본 리포트는 참고 자료이며 법적 책임을 지지 않습니다. 정확한 분류는 반드시 관세사에게 문의하십시오.
- 상세 상담이 필요하신 경우 하단 "관세사 검토의뢰"를 누르시면 본 리포트가 전문 관세사에게 전달됩니다.
"""
                    content = [prompt]
                    if uploaded_file:
                        img = Image.open(uploaded_file)
                        content.append(img)
                    
                    response = model.generate_content(content)
                    
                    # 결과 및 상태 세션 저장
                    st.session_state.ai_report_done = True
                    st.session_state.last_report_text = response.text
                    st.session_state.last_input_summary = input_summary
                    
                    # 이미지 해석 텍스트 추출 (메일 본문용)
                    if "1) 이미지 해석:" in response.text:
                        img_part = response.text.split("1) 이미지 해석:")[1].split("2) 품명:")[0]
                        st.session_state.img_analysis_text = img_part.strip()

                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 분석 중 오류 발생: {e}")

    # [3] 결과 출력 및 검토의뢰 (결과 유지 로직)
    if st.session_state.ai_report_done:
        st.markdown(st.session_state.last_report_text)
        
        st.divider()
        st.markdown("#### 📧 분석 내용이 만족스럽지 않으신가요? 관세사에게 직접 검토를 의뢰하세요.")
        col_req1, col_req2 = st.columns([0.7, 0.3])
        user_org = col_req1.text_input("상호명 (또는 성함)", key="user_org_v2")
        
        if col_req2.button("관세사 검토의뢰", use_container_width=True):
            if not user_org:
                st.error("⚠️ 의뢰를 위해 상호명 또는 성함을 입력해주세요.")
            else:
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                from email.mime.application import MIMEApplication

                SENDER_EMAIL = "jhlee@aegiscustoms.com"
                SENDER_PASSWORD = st.secrets.get("EMAIL_PASSWORD", "") 

                if not SENDER_PASSWORD:
                    st.error("❌ 비밀번호 설정 오류 (Secrets 확인 필요)")
                else:
                    msg = MIMEMultipart()
                    msg['From'] = SENDER_EMAIL
                    msg['To'] = SENDER_EMAIL 
                    msg['Subject'] = f"품목분류 검토의뢰_{user_org}"

                    email_body = f"""품목분류 검토의뢰서 (의뢰인: {user_org})

[1. 화주 입력 및 이미지 분석 정보]
1) 이미지 해석내용: {st.session_state.img_analysis_text if st.session_state.img_analysis_text else '정보 없음'}
{st.session_state.last_input_summary}

[2. AI 분석 리포트 결과]
{st.session_state.last_report_text}

--------------------------------------------------
본 의뢰는 AEGIS 시스템을 통해 자동 접수되었습니다.
"""
                    msg.attach(MIMEText(email_body, 'plain'))

                    # [핵심] 실제 이미지 파일 첨부 로직 통합
                    if st.session_state.last_img_bytes:
                        try:
                            img_attachment = MIMEApplication(st.session_state.last_img_bytes)
                            img_attachment.add_header('Content-Disposition', 'attachment', filename='requested_item_image.png')
                            msg.attach(img_attachment)
                        except Exception as img_err:
                            st.warning(f"이미지 파일 첨부 실패: {img_err}")

                    try:
                        server = smtplib.SMTP("smtp.gmail.com", 587)
                        server.starttls()
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        server.sendmail(SENDER_EMAIL, SENDER_EMAIL, msg.as_string())
                        server.quit()
                        st.success(f"✅ {user_org}님, 검토의뢰 메일(이미지 파일 포함)이 관세사에게 전송되었습니다.")
                    except Exception as e:
                        st.error(f"❌ 메일 발송 실패: {e}")

# --- [Tab 2] HS정보 (법령명 정렬 및 레이아웃 최적화 최종본) --- #변경내역★★
with tabs[1]:
    st.markdown("<div class='custom-header'>📘 HS 통합 정보 조회</div>", unsafe_allow_html=True) 
    target_hs = st.text_input("조회할 HSK 10자리를 입력하세요 (0 포함)", key="hs_info_v2", placeholder="예: 0101211000")
    
    if st.button("데이터 통합 조회", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs).zfill(10)
            try:
                conn = sqlite3.connect("customs_master.db")
                # 1) 기본정보 & 표준품명 조회
                m = pd.read_sql(f"SELECT name_kr, name_en FROM hs_master WHERE hs_code = '{hsk}'", conn)
                std = pd.read_sql(f"SELECT base_name FROM standard_names WHERE hs_code = '{hsk}'", conn)
                
                # 2) 관세율 (rate_names와 JOIN)
                r_q = f"""
                    SELECT r.type as '코드', n.h_name as '세율명칭', r.rate as '세율' 
                    FROM rates r 
                    LEFT JOIN rate_names n ON r.type = n.code 
                    WHERE r.hs_code = '{hsk}'
                """
                r_all = pd.read_sql(r_q, conn)
                
                # 3) 요건 (법령명 기준 오름차순 정렬 추가) #변경내역★★
                req_i = pd.read_sql(f"SELECT law as '법령명', agency as '승인기관', document as '서류명' FROM req_import WHERE hs_code = '{hsk}' ORDER BY law ASC", conn)
                req_e = pd.read_sql(f"SELECT law as '법령명', agency as '승인기관', document as '서류명' FROM req_export WHERE hs_code = '{hsk}' ORDER BY law ASC", conn)
                conn.close()

                if not m.empty or not std.empty:
                    st.markdown(f"<div class='custom-header'>📋 HS {hsk} 상세 리포트</div>", unsafe_allow_html=True)
                    cl, cr = st.columns(2)
                    with cl:
                        st.markdown("**표준품명**") 
                        st.success(std['base_name'].iloc[0] if not std.empty else "등록 정보 없음")
                    with cr:
                        st.markdown("**기본품명**")
                        name_kr_val = m['name_kr'].iloc[0] if not m.empty else "정보 없음"
                        name_en_val = m['name_en'].iloc[0] if not m.empty else "정보 없음"
                        st.info(f"한글품목명: {name_kr_val}\n\n영문품목명: {name_en_val}")
                    
                    st.divider()
                    st.markdown("**💰 관세율 정보**") 
                    
                    if not r_all.empty:
                        r_all['세율'] = r_all['세율'].astype(str) + "%"
                        
                        def styled_rate_table(df, is_scroll=False):
                            table_style = 'style="width:100%; border-collapse:collapse; table-layout:fixed; border:1px solid #E2E8F0; word-break:break-all;"'
                            th_style = 'style="background-color:#F8FAFC; color:#1E3A8A; text-align:center; padding:8px 2px; border:1px solid #E2E8F0; font-size:14px; position:sticky; top:0; z-index:10;"'
                            td_style = 'style="text-align:center; padding:8px 2px; border:1px solid #F1F5F9; font-size:13px; white-space:normal;"'
                            
                            html = f'<table {table_style}>'
                            html += '<colgroup><col style="width:80px;"><col style="width:auto;"><col style="width:80px;"></colgroup>'
                            html += '<thead><tr>'
                            for col in df.columns: html += f'<th {th_style}>{col}</th>'
                            html += '</tr></thead><tbody>'
                            for _, row in df.iterrows():
                                html += '<tr>'
                                for val in row: html += f'<td {td_style}>{val}</td>'
                                html += '</tr>'
                            html += '</tbody></table>'
                            
                            if is_scroll:
                                return f'<div style="max-height:350px; overflow-y:auto; border-radius:4px; border:1px solid #E2E8F0; width:100%;">{html}</div>'
                            return f'<div style="width:100%;">{html}</div>'

                        ra = r_all[r_all['코드'] == 'A']; rc = r_all[r_all['코드'] == 'C']
                        m1, m2 = st.columns(2)
                        m1.metric("기본세율 (A)", ra['세율'].iloc[0] if not ra.empty else "-")
                        m2.metric("WTO협정세율 (C)", rc['세율'].iloc[0] if not rc.empty else "-")
                        
                        re_etc = r_all[~r_all['코드'].isin(['A', 'C']) & ~r_all['코드'].str.startswith('F', na=False)]
                        rf = r_all[r_all['코드'].str.startswith('F', na=False)]
                        
                        rl, rr = st.columns(2)
                        with rl:
                            st.markdown("기타세율") 
                            st.write(styled_rate_table(re_etc), unsafe_allow_html=True)
                        with rr:
                            st.markdown("협정세율(FTA)") 
                            st.write(styled_rate_table(rf, is_scroll=True), unsafe_allow_html=True)
                    
                    st.divider()
                    st.markdown("**🛡️ 세관장확인대상**") 
                    
                    def styled_req_table(df):
                        table_style = 'style="width:100%; border-collapse:collapse; border:1px solid #E2E8F0; table-layout:fixed; word-break:break-all;"'
                        th_style = 'style="background-color:#F8FAFC; color:#1E3A8A; text-align:center; padding:8px 4px; border:1px solid #E2E8F0; font-size:14px;"'
                        td_style = 'style="text-align:center; padding:8px 4px; border:1px solid #F1F5F9; font-size:13px; white-space:normal;"'
                        
                        html = f'<table {table_style}><thead><tr>'
                        for col in df.columns: html += f'<th {th_style}>{col}</th>'
                        html += '</tr></thead><tbody>'
                        for _, row in df.iterrows():
                            html += '<tr>'
                            for val in row: html += f'<td {td_style}>{val}</td>'
                            html += '</tr>'
                        html += '</tbody></table>'
                        return f'<div style="width:100%;">{html}</div>'

                    ci, ce = st.columns(2)
                    with ci: 
                        st.markdown("[수입 요건]")
                        st.write(styled_req_table(req_i), unsafe_allow_html=True)
                    with ce: 
                        st.markdown("[수출 요건]")
                        st.write(styled_req_table(req_e), unsafe_allow_html=True)
                else: 
                    st.warning("HS코드 정보를 찾을 수 없습니다.")
            except Exception as e: 
                st.error(f"데이터 매핑 오류: {e}")

# --- [Tab 3] 통계부호 (정밀 매핑 및 출력 정렬 보정) --- #변경내역★★
with tabs[2]:
    st.markdown(f"<style>.tab3-title {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: bold; color: #1E3A8A; margin-bottom: 5px; }}</style>", unsafe_allow_html=True)
    st.markdown("<div class='tab3-title'>📊 2026 통계부호 통합 검색</div>", unsafe_allow_html=True)

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
            st.warning(f"⚠️ {sel_name} 데이터가 DB에 없습니다. [관리자] 탭에서 파일을 먼저 반영해 주세요.")
            conn.close()
        else:
            with col2:
                search_kw = st.text_input(f"🔍 {sel_name} 검색 키워드", placeholder="내용 또는 코드를 입력하세요", key="stat_kw_v2")
            
            if st.button("조회 실행", use_container_width=True):
                tbl = stat_tables[sel_name]
                
                # [공통] 통계부호 전용 가운데 정렬 스타일 테이블 함수 #변경내역★★
                def styled_stat_table(df):
                    table_style = 'style="width:100%; border-collapse:collapse; border:1px solid #E2E8F0;"'
                    th_style = 'style="background-color:#F8FAFC; color:#1E3A8A; text-align:center; padding:10px 4px; border:1px solid #E2E8F0; font-size:14px;"'
                    td_style = 'style="text-align:center; padding:10px 4px; border:1px solid #F1F5F9; font-size:13px;"'
                    
                    html = f'<table {table_style}><thead><tr>'
                    for col in df.columns: html += f'<th {th_style}>{col}</th>'
                    html += '</tr></thead><tbody>'
                    for _, row in df.iterrows():
                        html += '<tr>'
                        for val in row: html += f'<td {td_style}>{val if val is not None else ""}</td>'
                        html += '</tr>'
                    html += '</tbody></table>'
                    return f'<div style="width:100%; overflow-x:auto;">{html}</div>'

                # 1) 간이세율(2026)
                if sel_name == "간이세율(2026)":
                    df = pd.read_sql(f"SELECT gani_name as '간이품명', gani_hs as '간이HS부호', rate as '세율' FROM {tbl} WHERE gani_name LIKE '%{search_kw}%' OR gani_hs LIKE '%{search_kw}%'", conn)
                    if not df.empty: df['세율'] = df['세율'].astype(str) + "%"

                # 2) 관세감면부호(2026)
                elif sel_name == "관세감면부호(2026)":
                    df = pd.read_sql(f"""
                        SELECT content as '관세감면분납조항내용', code as '관세감면분납코드', rate as '관세감면율', 
                               after_target as '사후관리대상여부', installment_months as '분납개월수', installment_count as '분납횟수' 
                        FROM {tbl} WHERE content LIKE '%{search_kw}%' OR code LIKE '%{search_kw}%'
                    """, conn)
                    if not df.empty:
                        df['관세감면율'] = df['관세감면율'].astype(str) + "%"
                        for col in ['분납개월수', '분납횟수']:
                            df[col] = df[col].apply(lambda x: "" if str(x) in ['0', '0.0', 'None', 'nan', ''] else str(x))

                # 3) 내국세면세부호(2026)
                elif sel_name == "내국세면세부호(2026)":
                    df = pd.read_sql(f"SELECT name as '내국세부가세감면명', type_name as '구분명', code as '내국세부가세감면코드' FROM {tbl} WHERE name LIKE '%{search_kw}%' OR code LIKE '%{search_kw}%'", conn)

                # 4) 내국세율(2026)
                elif sel_name == "내국세율(2026)":
                    df = pd.read_sql(f"""
                        SELECT item_name as '신고품명', tax_rate as '내국세율', type_code as '내국세율구분코드', 
                               type_name as '내국세율구분코드명', tax_kind_code as '내국세세종코드', 
                               unit as '금액기준중수량단위', tax_base_price as '개소세과세기준가격', agri_tax_yn as '농특세과세여부' 
                        FROM {tbl} WHERE item_name LIKE '%{search_kw}%' OR type_name LIKE '%{search_kw}%'
                    """, conn)
                    if not df.empty: df['내국세율'] = df['내국세율'].astype(str) + "%"

                # -----------------------------------------------------------------
                # [신규통계부호] 삽입 영역 (향후 5, 6번 등 추가 시 이곳에 elif 조건문 추가)
                # -----------------------------------------------------------------
                
                conn.close()
                if not df.empty:
                    st.success(f"✅ {len(df)}건의 결과를 찾았습니다.")
                    # st.dataframe 대신 커스텀 스타일 함수 사용 (가운데 정렬 강제) #변경내역★★
                    st.write(styled_stat_table(df), unsafe_allow_html=True)
                else:
                    st.warning("일치하는 검색 결과가 없습니다.")
    else:
        st.info("조회하실 통계부호를 선택해 주세요.")

# --- [Tab 4] 화물통관 (통신 안정화 및 재시도 로직 보강) --- #변경내역★★
with tabs[3]:
    st.markdown("<div class='custom-header'>📦 화물통관 진행정보 실시간 조회</div>", unsafe_allow_html=True)
    
    if "bl_val" not in st.session_state: st.session_state.bl_val = "" 
    if "mrn_val" not in st.session_state: st.session_state.mrn_val = "" 
    if "search_result" not in st.session_state: st.session_state.search_result = None 

    c_y, c_b, c_m = st.columns([1, 2, 2])
    with c_y: carg_year = st.selectbox("입항년도", [2026, 2025, 2024], index=0)
    
    with c_b: bl_input = st.text_input("B/L 번호", value=st.session_state.bl_val, key="bl_search_v_final").strip().upper()
    with c_m: mrn_input = st.text_input("화물관리번호", value=st.session_state.mrn_val, key="mrn_search_v_final").strip()
    
    if st.button("실시간 조회 실행", use_container_width=True):
        API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
        if not API_KEY:
            st.error("❌ API 키가 설정되지 않았습니다.")
        elif not bl_input and not mrn_input:
            st.warning("⚠️ B/L 번호 또는 화물관리번호를 입력해주세요.")
        else:
            with st.spinner("관세청 유니패스 데이터 조회 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                clean_mrn = re.sub(r'[^a-zA-Z0-9]', '', mrn_input).upper() if mrn_input else ""
                params = {"crkyCn": API_KEY, "blYy": str(carg_year)}
                if bl_input: params["hblNo"] = bl_input
                if clean_mrn: params["cargMtNo"] = clean_mrn
                
                # [안정화 로직] 통신 실패 시 최대 3번 자동 재시도 #변경내역★★
                max_retries = 3
                success = False
                
                for i in range(max_retries):
                    try:
                        res = requests.get(url, params=params, timeout=15) # 타임아웃 15초 설정
                        if res.status_code == 200:
                            root = ET.fromstring(res.content)
                            info = root.find(".//cargCsclPrgsInfoQryVo")
                            
                            if info is not None and info.findtext("prgsStts"):
                                st.session_state.search_result = res.content 
                                found_bl = info.findtext("hblNo") or info.findtext("mblNo") or ""
                                found_mrn = info.findtext("cargMtNo") or ""
                                
                                if st.session_state.bl_val != found_bl or st.session_state.mrn_val != found_mrn:
                                    st.session_state.bl_val = found_bl
                                    st.session_state.mrn_val = found_mrn
                                    success = True
                                    st.rerun()
                                success = True
                                break # 조회 성공 시 루프 탈출
                            else:
                                st.session_state.search_result = None
                                st.warning("⚠️ 일치하는 정보가 없습니다.")
                                success = True
                                break
                    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                        if i < max_retries - 1:
                            time.sleep(1) # 1초 대기 후 재시도
                            continue
                        else:
                            st.error(f"❌ 관세청 서버 응답 지연 (잠시 후 다시 시도해주세요): {e}")
                    except Exception as e:
                        st.error(f"❌ 시스템 오류: {e}")
                        break

    # 2. 결과 출력 영역 (디자인 및 날짜 포맷 유지)
    if st.session_state.search_result:
        root = ET.fromstring(st.session_state.search_result)
        info = root.find(".//cargCsclPrgsInfoQryVo")
        dtls = root.findall(".//cargCsclPrgsInfoDtlQryVo")
        
        if info is not None:
            def get_safe_text(element, tag, length=None):
                val = element.findtext(tag)
                return (val[:length] if length else val) if val else ""

            def format_date(d_str):
                if d_str and len(d_str) >= 14:
                    return f"{d_str[0:4]}.{d_str[4:6]}.{d_str[6:8]}_{d_str[8:10]}:{d_str[10:12]}:{d_str[12:14]}"
                return d_str

            latest_loc = dtls[0].findtext("shedNm") or dtls[0].findtext("rlbrCn") or "정보없음" if dtls else "정보없음"

            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("현재상태", get_safe_text(info, "prgsStts"))
            m2.metric("품명", get_safe_text(info, "prnm", 12))
            m3.metric("중량", f"{get_safe_text(info, 'ttwg')} {get_safe_text(info, 'wghtUt')}")
            m4.metric("현재위치", latest_loc[:15])
            
            if dtls:
                st.write("**📑 상세 진행 단계**")
                t_style = 'style="width:100%; border-collapse:collapse; table-layout:fixed; border:1px solid #E2E8F0;"'
                th_style = 'style="background-color:#F8FAFC; color:#1E3A8A; text-align:center; padding:12px; border:1px solid #E2E8F0; font-size:14px; position:sticky; top:0; z-index:10;"'
                td_style = 'style="text-align:center; padding:10px; border:1px solid #F1F5F9; font-size:13px; word-break:break-all;"'
                
                html = f'<table {t_style}><colgroup><col style="width:25%;"><col style="width:35%;"><col style="width:40%;"></colgroup>'
                html += f'<thead><tr><th {th_style}>처리단계</th><th {th_style}>처리일시</th><th {th_style}>장치장/내용</th></tr></thead><tbody>'
                for item in dtls:
                    step = get_safe_text(item, "cargTrcnRelaBsopTpcd")
                    proc_dt = format_date(get_safe_text(item, "prcsDttm"))
                    loc = get_safe_text(item, "shedNm") or get_safe_text(item, "rlbrCn")
                    html += f'<tr><td {td_style}>{step}</td><td {td_style}>{proc_dt}</td><td {td_style}>{loc}</td></tr>'
                html += '</tbody></table>'
                st.write(f'<div style="max-height:450px; overflow-y:auto; border-radius:4px; border:1px solid #E2E8F0; width:100%;">{html}</div>', unsafe_allow_html=True)

# --- [Tab 5] 세액계산기 (결과 테이블 디자인 정밀 보정) --- #변경내역★★
with tabs[4]:
    st.markdown("<div class='custom-header'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    
    # 초기 세션 상태 설정
    if "calc_d" not in st.session_state: st.session_state.calc_d = 8.0
    if "calc_t" not in st.session_state: st.session_state.calc_t = "A"
    
    with st.container(border=True):
        st.write("**📍 1. 과세가격(CIF) 및 품목 입력**")
        cl, cr = st.columns(2)
        with cl:
            p_price = st.number_input("물품가격 (외화)", min_value=0.0, step=100.0)
            p_frt = st.number_input("운임 (Freight, KRW)", min_value=0)
            p_ins = st.number_input("보험료 (Insurance, KRW)", min_value=0)
        with cr:
            p_ex = st.number_input("환율", value=1350.0)
            st.write("품목분류(HSK)")
            h1, h2 = st.columns([0.7, 0.3])
            hs_in = h1.text_input("HSK 입력", label_visibility="collapsed", key="v5_hs", placeholder="예: 0101211000")
            
            if h2.button("적용", key="calc_apply_btn"):
                if hs_in:
                    hsk_clean = re.sub(r'[^0-9]', '', hs_in).zfill(10)
                    conn = sqlite3.connect("customs_master.db")
                    r_df = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{hsk_clean}' AND type IN ('A', 'C')", conn)
                    conn.close()
                    
                    if not r_df.empty:
                        r_df['rate_num'] = pd.to_numeric(r_df['rate'], errors='coerce')
                        min_row = r_df.loc[r_df['rate_num'].idxmin()]
                        st.session_state.calc_d = float(min_row['rate_num'])
                        st.session_state.calc_t = min_row['type']
                        st.success(f"HSK {hsk_clean} 적용 완료: {min_row['type']}세율 ({min_row['rate_num']}%) 선택됨")
                        st.rerun()
                    else:
                        st.warning("해당 HS코드의 기본(A) 또는 WTO(C) 세율 정보를 찾을 수 없습니다.")

            r1, r2 = st.columns(2)
            a_d = r1.number_input(f"관세율({st.session_state.calc_t}, %)", value=st.session_state.calc_d)
            a_v = r2.number_input("부가세율(%)", value=10.0)
        
        cif = int((p_price * p_ex) + p_frt + p_ins)
        st.info(f"**과세표준 (CIF KRW): {cif:,.0f} 원**")
        
    if st.button("세액 계산 실행", use_container_width=True, type="primary"):
        d = int(cif * (a_d/100))
        v = int((cif + d) * (a_v/100))
        
        st.markdown(f"<div style='font-size: 22px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 15px; border-radius: 8px;'>💰 예상세액: {d+v:,.0f} 원</div>", unsafe_allow_html=True)
        
        # [보정] 세액 산출 내역 테이블 커스텀 렌더링 #변경내역★★
        st.write("**📑 세액 산출 내역**")
        
        # 테이블 스타일 및 정렬 정의
        t_style = 'style="width:100%; border-collapse:collapse; table-layout:fixed; border:1px solid #E2E8F0;"'
        th_style = 'style="background-color:#F8FAFC; color:#1E3A8A; text-align:center; padding:12px; border:1px solid #E2E8F0; font-size:14px; position:sticky; top:0; z-index:10;"'
        td_center = 'style="text-align:center; padding:10px; border:1px solid #F1F5F9; font-size:13px;"'
        td_right = 'style="text-align:right; padding:10px; border:1px solid #F1F5F9; font-size:13px; font-weight:600;"'
        
        html = f"""
        <table {t_style}>
            <thead>
                <tr>
                    <th {th_style}>세종</th>
                    <th {th_style}>산출근거</th>
                    <th {th_style}>세액(원)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td {td_center}>관세</td>
                    <td {td_center}>{cif:,.0f} x {a_d}%</td>
                    <td {td_right}>{d:,.0f}</td>
                </tr>
                <tr>
                    <td {td_center}>부가세</td>
                    <td {td_center}>({cif:,.0f} + {d:,.0f}) x {a_v}%</td>
                    <td {td_right}>{v:,.0f}</td>
                </tr>
            </tbody>
        </table>
        """
        st.write(f'<div style="width: 100%;">{html}</div>', unsafe_allow_html=True)

    # 하단 안내 문구
    st.markdown("""
        <div style="font-size: 15px; color: #475569; margin-top: 30px; line-height: 1.8; border-top: 1px solid #E2E8F0; padding-top: 20px;">
            ※ 개별소비세, 주세, 교육세 등 내국세 부과대상의 예상세액은 관세사와 상담 부탁드립니다.<br>
            ※ 예상세액은 실제 세액과 다를 수 있으므로 참조의 목적으로만 이용하시기 바랍니다.
        </div>
    """, unsafe_allow_html=True)

## --- [Tab 6] 관리자 (반영 상태 표시등 및 정밀 매핑) --- #변경내역★★
if st.session_state.is_admin:
    with tabs[-1]:
        st.markdown("<div class='custom-header'>⚙️ 관리자 데이터 센터</div>", unsafe_allow_html=True)
        
        # 반영 상태 저장을 위한 세션 초기화
        if "upload_status" not in st.session_state:
            st.session_state.upload_status = {}

        # 📁 1. HS 마스터 및 요건 관리
        st.subheader("📁 1. HS 마스터 및 요건 관리")
        m_list = ["HS코드(마스터)", "표준품명", "관세율", "관세율구분", "세관장확인(수입)", "세관장확인(수출)"]
        cols = st.columns(3)
        
        for i, m_name in enumerate(m_list):
            with cols[i%3]:
                # 제목과 상태 표시등 출력 #변경내역★★
                status_led = "🟢 <span style='color:#10B981; font-size:12px; font-weight:bold;'>반영됨</span>" if st.session_state.upload_status.get(m_name) else "⚪ <span style='color:#94A3B8; font-size:12px;'>미반영</span>"
                st.markdown(f"**{m_name}** {status_led}", unsafe_allow_html=True)
                
                up = st.file_uploader(f"{m_name} 업로드", type="csv", key=f"ad_{m_name}", label_visibility="collapsed")
                
                if up and st.button(f"반영", key=f"btn_{m_name}", use_container_width=True):
                    df = safe_read_csv(up)
                    if df is not None:
                        conn = sqlite3.connect("customs_master.db")
                        try:
                            # [매핑 로직 시작]
                            if m_name == "HS코드(마스터)":
                                df_map = df.iloc[:, [0, 3, 4]].copy()
                                df_map.columns = ['hs_code', 'name_kr', 'name_en']
                            elif m_name == "표준품명":
                                df_map = df.iloc[:, [2, 1, 4, 5]].copy()
                                df_map.columns = ['hs_code', 'base_name', 'std_name_kr', 'std_name_en']
                            elif m_name == "관세율":
                                df_map = df.iloc[:, [0, 1, 2]].copy()
                                df_map.columns = ['hs_code', 'type', 'rate']
                            elif m_name == "관세율구분":
                                df_map = df.iloc[:, [1, 2]].copy()
                                df_map.columns = ['code', 'h_name']
                                df_map.to_sql('rate_names', conn, if_exists='replace', index=False)
                            elif "세관장확인" in m_name:
                                df_map = df.iloc[:, [0, 2, 4, 5]].copy()
                                df_map.columns = ['hs_code', 'law', 'agency', 'document']

                            # HS코드 공통 전처리
                            if 'hs_code' in df_map.columns:
                                df_map['hs_code'] = df_map['hs_code'].astype(str).str.replace(r'[^0-9]', '', regex=True).str.zfill(10)
                            
                            target_tbl_map = {
                                "HS코드(마스터)": "hs_master", "표준품명": "standard_names", 
                                "관세율": "rates", "세관장확인(수입)": "req_import", "세관장확인(수출)": "req_export"
                            }
                            
                            if m_name in target_tbl_map:
                                df_map.to_sql(target_tbl_map[m_name], conn, if_exists='replace', index=False)
                            
                            # [상태 업데이트] 반영 완료 시 세션에 기록 #변경내역★★
                            st.session_state.upload_status[m_name] = True
                            st.success(f"✅ {m_name} 반영 완료")
                            conn.close()
                            st.rerun() # 화면 즉시 갱신하여 녹색등 표시
                        except Exception as e:
                            st.error(f"❌ 오류: {e}")
                            if 'conn' in locals(): conn.close()

        st.divider()
        
        # 📊 2. 2026 통계부호 관리 (탭3 전용)
        st.subheader("📊 2. 2026 통계부호 관리")
        stat_list = ["간이세율(2026)", "관세감면부호(2026)", "내국세면세부호(2026)", "내국세율(2026)"]
        s_cols = st.columns(2)
        
        for i, s_name in enumerate(stat_list):
            with s_cols[i%2]:
                # 상태 표시등 출력 #변경내역★★
                s_status_led = "🟢 <span style='color:#10B981; font-size:12px; font-weight:bold;'>반영됨</span>" if st.session_state.upload_status.get(s_name) else "⚪ <span style='color:#94A3B8; font-size:12px;'>미반영</span>"
                st.markdown(f"**{s_name}** {s_status_led}", unsafe_allow_html=True)
                
                s_up = st.file_uploader(f"{s_name} 업로드", type="csv", key=f"sup_{s_name}", label_visibility="collapsed")
                
                if s_up and st.button(f"{s_name} 반영", key=f"sbtn_{s_name}", use_container_width=True):
                    sdf = safe_read_csv(s_up)
                    if sdf is not None:
                        conn = sqlite3.connect("customs_master.db")
                        try:
                            if s_name == "간이세율(2026)":
                                sdf_map = sdf.iloc[:, [0, 1, 2]].copy()
                                sdf_map.columns = ['gani_hs', 'gani_name', 'rate']
                                target_table = 'stat_gani'
                            elif s_name == "관세감면부호(2026)":
                                sdf_map = sdf.iloc[:, [0, 1, 2, 9, 6, 7]].copy()
                                sdf_map.columns = ['code', 'content', 'rate', 'after_target', 'installment_months', 'installment_count']
                                target_table = 'stat_reduction'
                            elif s_name == "내국세면세부호(2026)":
                                sdf_map = sdf.iloc[:, [1, 3, 0]].copy()
                                sdf_map.columns = ['name', 'type_name', 'code']
                                target_table = 'stat_vat_exemption'
                            elif s_name == "내국세율(2026)":
                                sdf_map = sdf.iloc[:, [3, 4, 0, 1, 2, 5, 6, 7]].copy()
                                sdf_map.columns = ['item_name', 'tax_rate', 'type_code', 'type_name', 'tax_kind_code', 'unit', 'tax_base_price', 'agri_tax_yn']
                                target_table = 'stat_internal_tax'
                            
                            sdf_map.to_sql(target_table, conn, if_exists='replace', index=False)
                            
                            # [상태 업데이트] #변경내역★★
                            st.session_state.upload_status[s_name] = True
                            st.success(f"✅ {s_name} 데이터 정밀 반영 완료")
                            conn.close()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 매핑 오류: {e}")
                            if 'conn' in locals(): conn.close()

# --- 하단 푸터 (완벽 복구) ---
st.divider()
f1, f2, f3, f4 = st.columns([2.5, 1, 1, 1])
f1.write("**📞 010-8859-0403 (이지스 관세사무소)**")
f2.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
f3.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
f4.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")