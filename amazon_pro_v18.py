import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：格式清洗與 HTML 保護 ---
def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    # 保留 HTML 標籤，僅移除 AI 可能產生的 JSON 引號
    text = re.sub(r"[\[\]'\"']", "", str(text))
    return text.strip()

# --- 2. 頁面配置 ---
st.set_page_config(page_title="亞馬遜運營專家 V34", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V34")
st.markdown("### 🎯 目標：全局關鍵詞共享 + Slot Plan 佈局 + Rufus NLP 優化")

# --- 3. 全局埋詞配置子功能 (所有 SKU 共享) ---
st.sidebar.header("📢 全局埋詞配置")
with st.sidebar.expander("✨ 關鍵詞數據庫 (所有款式共享)", expanded=True):
    # 這裡輸入一次，所有 SKU 都會引用
    global_kws = st.text_area("核心關鍵詞清單", 
                             placeholder="類目詞, 主題詞, 功能詞, 同義詞...", 
                             help="AI 會將這些詞分配到各個款式的標題、五點和描述中。")
    st.info("💡 提示：此處詞庫將自動分發給下方所有款式，實現『一處輸入，全局埋詞』。")

with st.sidebar:
    st.divider()
    st.header("⚙️ 全局規格與品牌")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 批量款式上傳區 ---
if 'v34_rows' not in st.session_state: st.session_state.v34_rows = 1

sku_items = []
st.subheader("📦 待上架款式列表")
for i in range(st.session_state.v34_rows):
    with st.expander(f"款式 #{i+1}：圖片與 URL 配置", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}", placeholder="LMX-SDS-01")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2:
            m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with c3:
            o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v34_rows += 1
    st.rerun()

st.divider()
tpl_file = st.file_uploader("📂 上傳 Amazon 美國站 Template 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行填充 (Slot Plan 深度集成 Prompt) ---
if st.button("🚀 啟動 AI 批量運營上架", type="primary") and tpl_file and api_key:
    if not global_kws:
        st.error("⚠️ 請先在左側『全局埋詞配置』中輸入關鍵詞！")
        st.stop()
        
    with st.spinner('AI 正在根據共享詞庫執行 Slot Plan 策略...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            h = {str(c.value).lower().replace(" ", "").replace("_", ""): c.column for r in range(1, 6) for c in range(1, sheet.max_column+1) if sheet.cell(row=r, column=c).value}
            
            client = OpenAI(api_key=api_key)
            current_row = 4

            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                # 引用全局關鍵詞的 Prompt
                prompt_v34 = f"""
                You are an Amazon SEO Expert. 
                CORE KEYWORDS TO EMBED (Shared for all SKUs): [{global_kws}]
                
                TASK: Analyze the SKU-specific image and embed the shared keywords using Slot Plan:
                1. TITLE: [Brand] + Category Keyword + 1 Theme + 1 Feature. Main keyword in first 80 chars.
                2. BULLET 1-5: Performance, Structure, Material, Scene, Spec. Distribute shared keywords across these.
                3. DESCRIPTION: HTML (<p>, <b>). Narrative: Problem -> Solution -> Experience. Use synonyms of shared keywords.
                4. SEARCH TERMS: Space-separated words from the shared list NOT used in Title/BP.
                
                Avoid IP words. Output JSON: {{ "title": "", "bp": ["", "", "", "", ""], "description": "", "search_terms": "" }}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt_v34},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                # 填充邏輯 (1父 3子)
                p_sku = f"{item['pfx']}-P"
                rows_config = [{"t":"P","s":p_sku,"sz":""},{"t":"C","s":f"{item['pfx']}-01","sz":s1},{"t":"C","s":f"{item['pfx']}-02","sz":s2},{"t":"C","s":f"{item['pfx']}-03","sz":s3}]
                
                for r_info in rows_config:
                    def fill(k, v):
                        c_idx = h.get(k.lower().replace(" ", "").replace("_", ""))
                        if c_idx: sheet.cell(row=current_row, column=c_idx, value=clean_text(v))
                    
                    fill("sellersku", r_info["s"]); fill("parentsku", p_sku)
                    fill("productname", f"{brand} {ai['title']}")
                    fill("productdescription", ai['description'])
                    fill("generickeywords", ai['search_terms'])
                    for bi, b_text in enumerate(ai['bp']):
                        fill(f"keyproductfeatures{bi+1}", b_text)
                    
                    if r_info["t"] == "C":
                        fill("mainimageurl", item["main"])
                        for i, o_url in enumerate(item["others"].split('\n')[:8]):
                            fill(f"otherimageurl{i+1}", o_url.strip())
                        fill("size", r_info["sz"])
                    current_row += 1

            out = io.BytesIO()
            wb.save(out)
            st.success(f"✅ 批量生成完成！已根據全局詞庫優化 {st.session_state.v34_rows} 個款式。")
            st.download_button("💾 下載美國站上架文件", out.getvalue(), "Amazon_V34_GlobalKW.xlsm")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
