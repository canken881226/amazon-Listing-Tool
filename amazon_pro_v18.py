import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：數據清洗與 HTML 保護 ---
def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    # 保留 HTML 標籤（如 <p>, <b>），僅移除 AI 可能產生的 JSON 引號
    text = re.sub(r"[\[\]'\"']", "", str(text))
    return text.strip()

# --- 2. 頁面配置 (適配 Codespaces) ---
st.set_page_config(page_title="亞馬遜運營專家 V36", layout="wide")
# 優先讀取環境變量，解決 Secrets 報錯問題
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V36")
st.markdown("### 🎯 已固化規則：Slot Plan 佈局 + Rufus 自然語言 + 全局埋詞共享")

# --- 3. 全局配置區 (側邊欄：所有 SKU 共享) ---
st.sidebar.header("📢 運營配置中心")
with st.sidebar.expander("✨ 全局埋詞庫 (所有款式共享)", expanded=True):
    # 這裡輸入一次，所有 SKU 會自動調用並埋詞
    global_kws = st.text_area("核心關鍵詞清單", 
                             placeholder="類目詞, 主題詞, 功能詞, 同義詞...", 
                             help="AI 會根據 Slot Plan 策略將這些詞分散埋入標題、五點和描述。")

with st.sidebar:
    st.divider()
    st.header("⚙️ 全局規格與品牌")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. SKU 款式上傳區 ---
if 'v36_rows' not in st.session_state: st.session_state.v36_rows = 1

sku_items = []
st.subheader("📦 批量款式列表")
for i in range(st.session_state.v36_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 1.5])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2:
            m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with c3:
            o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v36_rows += 1
    st.rerun()

st.divider()
tpl_file = st.file_uploader("📂 上傳 Amazon Template 模板 (1.3MB OK)", type=['xlsx', 'xlsm'])

# --- 5. 執行填充 (深度集成 Slot Plan 指令) ---
if st.button("🚀 啟動 AI 運營級批量上架", type="primary") and tpl_file and api_key:
    if not global_kws:
        st.error("⚠️ 請先在側邊欄輸入『全局埋詞庫』！")
        st.stop()
        
    with st.spinner('AI 正在分析圖片並執行 Slot Plan 埋詞規則...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            
            # 健壯的列名掃描，解決圖 5c06 的 int 類型報錯
            h = {}
            for r_idx in range(1, 6):
                for cell in sheet[r_idx]:
                    if cell.value and isinstance(cell.value, str):
                        clean_n = str(cell.value).lower().replace(" ", "").replace("_", "")
                        if clean_n: h[clean_n] = cell.column
            
            client = OpenAI(api_key=api_key)
            current_row = 4

            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                # 固化運營規則的終極 Prompt
                prompt_v36 = f"""
                You are a Senior Amazon SEO. Keywords: [{global_kws}]
                
                SLOT PLAN RULES:
                1. TITLE: [Brand] + Category KW + Theme + Feature. Main KW in first 80 chars.
                2. BULLET 1 (Perf): Functional KW + Feeling.
                3. BULLET 2 (Fit): Structural KW.
                4. BULLET 3 (Mat): Material KW.
                5. BULLET 4 (Scene): Scene & Target Audience.
                6. BULLET 5 (Spec): Spec/Pack/Maintenance.
                7. DESCRIPTION: Use HTML (<p>, <b>). "Problem -> Solution -> Scene" narrative. Supplement synonyms.
                8. SEARCH TERMS: Keywords NOT in Title/BP. Max 245 chars.
                
                Output JSON: {{ "title": "", "bp": ["", "", "", "", ""], "description": "", "search_terms": "" }}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o", 
                    messages=[{"role":"user","content":[{"type":"text","text":prompt_v36},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                # 數據寫入 (1父 3子)
                p_sku = f"{item['pfx']}-P"
                rows_cfg = [{"t":"P","s":p_sku,"sz":""},{"t":"C","s":f"{item['pfx']}-01","sz":s1},{"t":"C","s":f"{item['pfx']}-02","sz":s2},{"t":"C","s":f"{item['pfx']}-03","sz":s3}]
                
                for r_info in rows_cfg:
                    def fill(k, v):
                        c_idx = h.get(k.lower().replace(" ", "").replace("_", ""))
                        if c_idx: sheet.cell(row=current_row, column=c_idx, value=clean_text(v))
                    
                    fill("sellersku", r_info["s"]); fill("parentsku", p_sku)
                    fill("productname", f"{brand} {ai['title']}")
                    fill("productdescription", ai['description']) # 寫入帶 HTML 的描述
                    fill("generickeywords", ai['search_terms'])
                    for bi, b_text in enumerate(ai['bp']):
                        fill(f"keyproductfeatures{bi+1}", b_text)
                    
                    if r_info["t"] == "C":
                        fill("mainimageurl", item["main"])
                        for idx, o_url in enumerate(item["others"].split('\n')[:8]):
                            fill(f"otherimageurl{idx+1}", o_url.strip())
                        fill("size", r_info["sz"]); fill("standardprice", p1 if r_info["s"].endswith("-01") else (p2 if r_info["s"].endswith("-02") else p3))
                    current_row += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ 集成上架生成成功！規則已全部應用。")
            st.download_button("💾 下載最終版本文件", out.getvalue(), "Amazon_V36_Final.xlsm")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
