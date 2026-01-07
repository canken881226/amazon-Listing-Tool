import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os, gc
from openai import OpenAI
from datetime import datetime, timedelta

# --- 1. 核心工具 (保留標點，處理亂碼) ---
def clean_copy_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    text_str = str(text).replace('["', '').replace('"]', '').strip()
    return "".join(c for c in text_str if ord(c) >= 32 or c in '\n\r\t')

def deduplicate_title(title):
    words = str(title).split()
    seen, res = set(), []
    for w in words:
        clean_w = re.sub(r'[^a-zA-Z0-9]', '', w).lower()
        if clean_w not in seen:
            res.append(w); seen.add(clean_w)
    return " ".join(res)

def format_amazon_kw(elements, global_kws):
    raw_str = f"{str(elements)} {str(global_kws)}".replace(",", " ").replace(";", " ")
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
st.set_page_config(page_title="亞馬遜專家 V51", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V51")
st.success("✅ 規則鎖定：200字長標題、父類帶圖、Map字段強制填充、售價必填、五點補完。")

# --- 3. 側邊欄 ---
if 'size_count' not in st.session_state: st.session_state.size_count = 3
with st.sidebar:
    st.header("📢 運營配置")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    global_kws = st.text_area("✨ 全局關鍵詞單詞庫", "canvas wall art decor")
    st.divider()
    size_matrix = []
    for i in range(st.session_state.size_count):
        col_s, col_p = st.columns([2, 1])
        with col_s: s_val = st.text_input(f"尺寸 {i+1}", key=f"size_val_{i}", value="16x24\"")
        with col_p: p_val = st.text_input(f"價格 {i+1}", key=f"price_val_{i}", value="12.99")
        size_matrix.append({"size": s_val, "price": p_val})
    if st.button("➕ 增加尺寸"): st.session_state.size_count += 1; st.rerun()
    if st.button("➖ 刪除尺寸") and st.session_state.size_count > 1: st.session_state.size_count -= 1; st.rerun()

# --- 4. 款式管理 ---
if 'v51_rows' not in st.session_state: st.session_state.v51_rows = 1
sku_items = []
for i in range(st.session_state.v51_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        col_a, col_b, col_c = st.columns([1.2, 1, 1.5])
        with col_a:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with col_b: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with col_c: o_urls = st.text_area(f"附圖 URLs", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})
if st.button("➕ 增加一個款式"): st.session_state.v51_rows += 1; st.rerun()

tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 核心執行 ---
if st.button("🚀 啟動 V51 全規則填充", type="primary") and tpl_file and api_key:
    progress_bar = st.progress(0)
    try:
        wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
        sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
        h = {re.sub(r'[^a-z0-9]', '', str(cell.value).lower()): cell.column for r in range(1, 6) for cell in sheet[r] if cell.value}
        fixed_values = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column + 1) if sheet.cell(row=4, column=col).value}
        valid_items = [item for item in sku_items if item["pfx"] and item["img"]]
        
        indices = [re.search(r'\d+$', str(item["pfx"])).group() for item in valid_items if re.search(r'\d+$', str(item["pfx"]))]
        min_i, max_i = (min(indices), max(indices)) if indices else ("X", "Y")
        base_pfx = re.sub(r'-?\d+$', '', str(valid_items[0]["pfx"]))
        global_parent_sku = f"{base_pfx}-{min_i}-{max_i}-P"

        start_date, end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"), (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        client, row_cursor = OpenAI(api_key=api_key), 4
        
        def fill(r, k_list, v):
            for k in k_list:
                target_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
                c_idx = h.get(target_k)
                if c_idx: sheet.cell(row=r, column=c_idx, value=clean_copy_text(v)); break

        def fill_fixed(r):
            for col_idx, val in fixed_values.items():
                if not sheet.cell(row=r, column=col_idx).value: sheet.cell(row=r, column=col_idx, value=val)

        # 步驟 A: 寫入全局父類 (規則 2: 父類帶圖)
        fill(row_cursor, ["sellersku"], global_parent_sku)
        fill(row_cursor, ["productname"], f"{brand} Collection {global_parent_sku.replace('-P','')}")
        fill(row_cursor, ["mainimageurl"], valid_items[0]["main"]) # 父類帶圖
        fill_fixed(row_cursor); row_cursor += 1

        # 步驟 B: 寫入款式
        for step, item in enumerate(valid_items):
            item["img"].seek(0)
            b64 = base64.b64encode(item["img"].read()).decode('utf-8')
            # 規則 1: 標題豐富化指令
            prompt = f"""Act as Amazon SEO expert. JSON Output: {{ "title": "Rich title 150-200 chars, keywords heavy, NO repeat words.", "element": "One word only, NO color words.", "bp": ["Point1", "Point2", "Point3", "Point4", "Point5"], "desc": "HTML desc" }}"""
            res = client.chat.completions.create(
                model="gpt-4o", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}], response_format={"type":"json_object"}
            )
            ai = json.loads(res.choices[0].message.content)
            
            for sz_cfg in size_matrix:
                fill_fixed(row_cursor)
                fill(row_cursor, ["sellersku"], f"{str(item['pfx'])}-{str(sz_cfg['size'])}")
                fill(row_cursor, ["parentsku"], global_parent_sku)
                
                clean_title = deduplicate_title(f"{brand} {ai.get('title','')} {ai.get('element','')}")
                fill(row_cursor, ["productname"], f"{clean_title} - {str(sz_cfg['size'])}")
                
                # 規則 4, 5: Map 字段必填且一致
                fill(row_cursor, ["color", "colour"], ai.get('element',''))
                fill(row_cursor, ["colormap", "colourmap"], ai.get('element',''))
                fill(row_cursor, ["size", "itemsize"], str(sz_cfg['size']))
                fill(row_cursor, ["sizemap"], str(sz_cfg['size']))
                
                # 規則 6: Sales Price 必填
                fill(row_cursor, ["standardprice"], str(sz_cfg['price']))
                fill(row_cursor, ["saleprice"], str(sz_cfg['price']))
                fill(row_cursor, ["salestartdate"], start_date); fill(row_cursor, ["saleenddate"], end_date)
                
                fill(row_cursor, ["mainimageurl"], str(item["main"]))
                for idx, o_url in enumerate(str(item["others"]).split('\n')[:8]):
                    fill(row_cursor, [f"otherimageurl{idx+1}"], o_url.strip())
                
                # 規則 3: 五點描述物理寫入
                for bi, b_text in enumerate(ai.get('bp', [])):
                    clean_bp = re.sub(r'^(Bullet\s?\d?[:.]?\s*|^\d[:.]?\s*)', '', str(b_text), flags=re.IGNORECASE).strip()
                    fill(row_cursor, [f"keyproductfeatures{bi+1}", f"bulletpoint{bi+1}"], clean_bp)
                
                fill(row_cursor, ["productdescription"], ai.get('desc', ''))
                fill(row_cursor, ["generickeywords"], format_amazon_kw(ai.get('element',''), global_kws))
                row_cursor += 1
            progress_bar.progress(int((step + 1) / len(valid_items) * 100))

        out = io.BytesIO()
        wb.save(out); wb.close(); gc.collect()
        st.download_button("💾 下載 V51 終極版", out.getvalue(), "Amazon_V51.xlsm")
    except Exception as e: st.error(f"❌ 錯誤: {e}")
