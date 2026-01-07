import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：數據清洗 (解決圖 d7cb 佔位符) ---
def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = {'word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

def format_kw(raw_text):
    if not raw_text: return ""
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(raw_text).lower())
    seen, res = set(), []
    for w in clean.split():
        if w not in seen and len(w) > 1:
            res.append(w); seen.add(w)
    return " ".join(res)[:245]

# --- 2. 頁面配置與環境變量讀取 (解決圖 96b9 報錯) ---
st.set_page_config(page_title="亞馬遜批量上架系統 V30", layout="wide")

# 優先讀取 Codespaces 終端注入的環境變量
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🎨 亞馬遜 AI 批量上架系統 (多 SKU 模式)")

# --- 3. 側邊欄：全局規格鎖定 ---
with st.sidebar:
    st.header("⚙️ 規格鎖定")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    st.subheader("尺寸與價格對應")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 多 SKU 款式管理 ---
if 'v30_rows' not in st.session_state:
    st.session_state.v30_rows = 1

sku_items = []
st.subheader("📦 款式列表")
for i in range(st.session_state.v30_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            item_pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}", placeholder="例如: LMX-SDS-01")
            item_img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with col2:
            item_main_url = st.text_input(f"主圖 URL (可選)", key=f"main_url_{i}")
            item_other_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"other_urls_{i}")
        sku_items.append({"pfx": item_pfx, "img": item_img, "main": item_main_url, "others": item_other_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v30_rows += 1
    st.rerun()

st.divider()
tpl_file = st.file_uploader("📂 上傳 Amazon 美國站模板", type=['xlsx', 'xlsm'])

# --- 5. 執行填充邏輯 ---
if st.button("🚀 啟動批量 AI 填充", type="primary"):
    if not tpl_file or not api_key:
        st.error("❌ 請確保已上傳模板文件並配置 API Key。")
    else:
        with st.spinner('正在分析圖片並寫入 Template 子表...'):
            try:
                # 準備 Excel
                wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
                sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
                
                # 掃描表頭
                h = {}
                for r in range(1, 6):
                    for c in range(1, sheet.max_column + 1):
                        v = str(sheet.cell(row=r, column=c).value).lower().replace(" ", "").replace("_", "")
                        if v and v != "none": h[v] = c

                client = OpenAI(api_key=api_key)
                current_write_row = 4 # 從第 4 行開始

                for item in sku_items:
                    if not item["pfx"] or not item["img"]:
                        continue # 跳過未填寫完整的款式
                    
                    # AI 分析
                    item["img"].seek(0)
                    b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)
                    
                    # 1父 3子數據邏輯
                    parent_sku = f"{item['pfx']}-001-003"
                    rows_logic = [
                        {"t":"P", "s":parent_sku, "sz":"", "pr":""},
                        {"t":"C", "s":f"{item['pfx']}-001", "sz":s1, "pr":p1},
                        {"t":"C", "s":f"{item['pfx']}-002", "sz":s2, "pr":p2},
                        {"t":"C", "s":f"{item['pfx']}-003", "sz":s3, "pr":p3}
                    ]

                    for r_idx, r_info in enumerate(rows_logic):
                        def fill(key, value):
                            col_idx = h.get(key.lower().replace(" ", "").replace("_", ""))
                            if col_idx: sheet.cell(row=current_write_row, column=col_idx, value=clean_text(value))

                        fill("sellersku", r_info["s"])
                        fill("parentsku", parent_sku)
                        
                        if r_info["t"] == "C":
                            fill("size", r_info["sz"])
                            fill("standardprice", r_info["pr"])
                            color_val = f"{ai.get('color','')} {ai.get('elements','')}"
                            fill("color", color_val)
                            fill("colormap", color_val)
                        
                        fill("productname", f"{brand} {ai.get('title','')} {ai.get('elements','')}"[:199])
                        fill("generickeyword", format_kw(ai.get('elements','')))
                        for bi in range(5):
                            fill(f"keyproductfeatures{bi+1}", ai['bp'][bi] if bi < len(ai['bp']) else "")
                        
                        # 圖片鏈接處理
                        if r_info["t"] == "C":
                            fill("mainimageurl", item["main"])
                            other_list = item["others"].split('\n')
                            for oi, o_url in enumerate(other_list):
                                if oi < 8: fill(f"otherimageurl{oi+1}", o_url.strip())

                        current_write_row += 1 # 下移一行

                out = io.BytesIO()
                wb.save(out)
                st.success(f"✅ 批量生成完成！共處理 {st.session_state.v30_rows} 個款式。")
                st.download_button("💾 下載美國站上架文件", out.getvalue(), "Amazon_Bulk_Upload.xlsm")
                
            except Exception as e:
                st.error(f"❌ 執行出錯：{str(e)}")
