import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI
from datetime import datetime, timedelta

# --- 1. 核心工具 ---
def clean_copy_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    text = str(text).replace('["', '').replace('"]', '').replace('"', '"').strip()
    return "".join(c for c in text if ord(c) >= 32 or c in '\n\r\t')

def deduplicate_title(title):
    words = title.split()
    seen, res = set(), []
    for w in words:
        clean_w = re.sub(r'[^a-zA-Z0-9]', '', w).lower()
        if clean_w not in seen:
            res.append(w); seen.add(clean_w)
    return " ".join(res)

def format_amazon_kw(elements, global_kws):
    raw_str = f"{elements} {global_kws}".replace(",", " ").replace(";", " ")
    words = raw_str.split()
    seen, res, curr_len = set(), [], 0
    for w in words:
        w_clean = re.sub(r'[^a-zA-Z0-9]', '', w).lower()
        if w_clean and w_clean not in seen:
            new_len = curr_len + (1 if res else 0) + len(w_clean)
            if new_len <= 250:
                res.append(w_clean); seen.add(w_clean); curr_len = new_len
            else: break
    return " ".join(res)

# --- 2. 頁面配置 ---
st.set_page_config(page_title="亞馬遜專家 V48", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V48")
st.success("✅ 專項修復：已解決 'got int' 列名讀取報錯，確保 1.3MB 模板穩定加載。")

# --- 3. 側邊欄：動態尺寸與全局配置 ---
if 'size_count' not in st.session_state: st.session_state.size_count = 3

with st.sidebar:
    st.header("📢 運營中心")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    global_kws = st.text_area("✨ 全局關鍵詞單詞庫", "canvas wall art decor")
    
    st.divider()
    st.subheader("📌 尺寸變體矩陣")
    size_matrix = []
    for i in range(st.session_state.size_count):
        col_s, col_p = st.columns([2, 1])
        with col_s: s_val = st.text_input(f"尺寸 {i+1}", key=f"size_val_{i}", value="16x24\"")
        with col_p: p_val = st.text_input(f"價格 {i+1}", key=f"price_val_{i}", value="12.99")
        size_matrix.append({"size": s_val, "price": p_val})
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("➕ 增加尺寸"):
            st.session_state.size_count += 1
            st.rerun()
    with c2:
        if st.button("➖ 刪除尺寸") and st.session_state.size_count > 1:
            st.session_state.size_count -= 1
            st.rerun()

# --- 4. 款式管理 ---
if 'v48_rows' not in st.session_state: st.session_state.v48_rows = 1
sku_items = []
st.subheader("📦 待上架款式列表")
for i in range(st.session_state.v48_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        col_a, col_b, col_c = st.columns([1.2, 1, 1.5])
        with col_a:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}", placeholder="LMX-SDS-082")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with col_b: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with col_c: o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v48_rows += 1
    st.rerun()

st.divider()
tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行填充 ---
if st.button("🚀 啟動 V48 批量填充", type="primary") and tpl_file and api_key:
    with st.spinner('正在分析圖片並進行安全性校驗...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            
            # --- 關鍵修復區：加入文字類型判斷，避免 'int' 報錯 ---
            h = {}
            for r in range(1, 6):
                for cell in sheet[r]:
                    # 只有當單元格內容為字串時才進行正則替換
                    if cell.value and isinstance(cell.value, str):
                        clean_n = re.sub(r'[^a-z0-9]', '', cell.value.lower())
                        if clean_n: h[clean_n] = cell.column
            # -----------------------------------------------------------
            
            fixed_values = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column + 1) if sheet.cell(row=4, column=col).value}
            valid_items = [item for item in sku_items if item["pfx"] and item["img"]]
            if not valid_items: st.error("❌ 請填寫完整信息！"); st.stop()
            
            indices = [re.search(r'\d+$', item["pfx"]).group() for item in valid_items if re.search(r'\d+$', item["pfx"])]
            if indices:
                min_i, max_i = min(indices), max(indices)
                base_pfx = re.sub(r'-?\d+$', '', valid_items[0]["pfx"])
                global_parent_sku = f"{base_pfx}-{min_i}-{max_i}-P"
            else:
                global_parent_sku = f"{valid_items[0]['pfx']}-Global-P"

            start_date, end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"), (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            client = OpenAI(api_key=api_key)
            row_cursor = 4
            
            def fill(r, k_list, v):
                for k in k_list:
                    # 修復調用處也進行類型安全檢測
                    target_k = re.sub(r'[^a-z0-9]', '', k.lower()) if isinstance(k, str) else ""
                    c_idx = h.get(target_k)
                    if c_idx: sheet.cell(row=r, column=c_idx, value=clean_copy_text(v)); break

            def fill_fixed(r):
                for col_idx, val in fixed_values.items():
                    if not sheet.cell(row=r, column=col_idx).value: sheet.cell(row=r, column=col_idx, value=val)

            fill(row_cursor, ["sellersku"], global_parent_sku)
            fill(row_cursor, ["productname"], f"{brand} Collection {global_parent_sku.replace('-P','')}")
            fill_fixed(row_cursor); row_cursor += 1

            for item in valid_items:
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {title, element_word, bp:[5], desc}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                for sz_cfg in size_matrix:
                    fill_fixed(row_cursor)
                    fill(row_cursor, ["sellersku"], f"{item['pfx']}-{sz_cfg['size']}")
                    fill(row_cursor, ["parentsku"], global_parent_sku)
                    
                    title = deduplicate_title(f"{brand} {ai['title']} {ai['element_word']}")
                    fill(row_cursor, ["productname"], f"{title} - {sz_cfg['size']}")
                    fill(row_cursor, ["color", "colour", "colormap"], ai['element_word'])
                    fill(row_cursor, ["size", "itemsize", "sizemap"], sz_cfg['size'])
                    fill(row_cursor, ["standardprice", "saleprice"], sz_cfg['price'])
                    fill(row_cursor, ["salestartdate"], start_date); fill(row_cursor, ["saleenddate"], end_date)
                    fill(row_cursor, ["mainimageurl"], item["main"])
                    for idx, o_url in enumerate(item["others"].split('\n')[:8]):
                        fill(row_cursor, [f"otherimageurl{idx+1}"], o_url.strip())
                    
                    for bi, b_text in enumerate(ai.get('bp', [])):
                        clean_bp = re.sub(r'^(Bullet\s?\d?[:.]?\s*|^\d[:.]?\s*)', '', b_text, flags=re.IGNORECASE).strip()
                        fill(row_cursor, [f"keyproductfeatures{bi+1}", f"bulletpoint{bi+1}"], clean_bp)
                    
                    fill(row_cursor, ["productdescription"], ai.get('desc', ''))
                    fill(row_cursor, ["generickeywords"], format_amazon_kw(ai.get('element_word', ''), global_kws))
                    row_cursor += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ V48 生成完成！錯誤已修正。")
            st.download_button("💾 下載修復版文件", out.getvalue(), "Amazon_V48_Fixed.xlsm")
        except Exception as e: st.error(f"❌ 錯誤詳情: {e}")
