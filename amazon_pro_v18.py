import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os, gc
from openai import OpenAI
from datetime import datetime, timedelta

# --- 1. 核心工具 ---
def clean_copy_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    # 確保輸出始終為字串，防止類型錯誤
    text_str = str(text)
    text_str = text_str.replace('["', '').replace('"]', '').replace('"', '"').strip()
    return "".join(c for c in text_str if ord(c) >= 32 or c in '\n\r\t')

def deduplicate_title(title):
    # 增加類型防禦
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
st.set_page_config(page_title="亞馬遜專家 V50", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V50")
st.success("✅ 專項優化：解決分析階段的『expected string, got int』類型錯誤。")

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
        if st.button("➕ 增加尺寸"): st.session_state.size_count += 1; st.rerun()
    with c2:
        if st.button("➖ 刪除尺寸") and st.session_state.size_count > 1: st.session_state.size_count -= 1; st.rerun()

# --- 4. 款式管理 ---
if 'v50_rows' not in st.session_state: st.session_state.v50_rows = 1
sku_items = []
st.subheader("📦 待上架款式列表")
for i in range(st.session_state.v50_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        col_a, col_b, col_c = st.columns([1.2, 1, 1.5])
        with col_a:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}", placeholder="LMX-SDS-082")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with col_b: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with col_c: o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})
if st.button("➕ 增加一個款式"): st.session_state.v50_rows += 1; st.rerun()

st.divider()
tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行填充 ---
if st.button("🚀 啟動 V50 批量填充", type="primary") and tpl_file and api_key:
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        status_text.text("正在加載 Amazon 模板...")
        wb = openpyxl.load_workbook(tpl_file, keep_vba=True, data_only=False)
        sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
        progress_bar.progress(10)
        
        status_text.text("正在建立列名索引...")
        h = {}
        for r in range(1, 6):
            for cell in sheet[r]:
                if cell.value and isinstance(cell.value, (str, float, int)):
                    clean_n = re.sub(r'[^a-z0-9]', '', str(cell.value).lower())
                    if clean_n: h[clean_n] = cell.column
        
        fixed_values = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column + 1) if sheet.cell(row=4, column=col).value}
        valid_items = [item for item in sku_items if item["pfx"] and item["img"]]
        if not valid_items: st.error("❌ 請填寫完整信息！"); st.stop()
        
        # 提取 SKU 序號時增加字符串保護
        indices = [re.search(r'\d+$', str(item["pfx"])).group() for item in valid_items if re.search(r'\d+$', str(item["pfx"]))]
        if indices:
            min_i, max_i = min(indices), max(indices)
            base_pfx = re.sub(r'-?\d+$', '', str(valid_items[0]["pfx"]))
            global_parent_sku = f"{base_pfx}-{min_i}-{max_i}-P"
        else:
            global_parent_sku = f"{str(valid_items[0]['pfx'])}-Global-P"

        start_date, end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"), (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        client = OpenAI(api_key=api_key)
        row_cursor = 4
        
        def fill(r, k_list, v):
            for k in k_list:
                target_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
                c_idx = h.get(target_k)
                if c_idx: sheet.cell(row=r, column=c_idx, value=clean_copy_text(v)); break

        def fill_fixed(r):
            for col_idx, val in fixed_values.items():
                if not sheet.cell(row=r, column=col_idx).value: sheet.cell(row=r, column=col_idx, value=val)

        # 寫入父類
        fill(row_cursor, ["sellersku"], global_parent_sku)
        fill(row_cursor, ["productname"], f"{brand} Collection {global_parent_sku.replace('-P','')}")
        fill_fixed(row_cursor); row_cursor += 1
        progress_bar.progress(20)

        # 寫入款式
        total_steps = len(valid_items)
        for step, item in enumerate(valid_items):
            status_text.text(f"正在分析款式 #{step+1}: {str(item['pfx'])}...")
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
                # 關鍵修復：組合 SKU 時強制轉為字串
                fill(row_cursor, ["sellersku"], f"{str(item['pfx'])}-{str(sz_cfg['size'])}")
                fill(row_cursor, ["parentsku"], global_parent_sku)
                title = deduplicate_title(f"{brand} {ai.get('title','')} {ai.get('element_word','')}")
                fill(row_cursor, ["productname"], f"{title} - {str(sz_cfg['size'])}")
                fill(row_cursor, ["color", "colour", "colormap"], ai.get('element_word',''))
                fill(row_cursor, ["size", "itemsize", "sizemap"], str(sz_cfg['size']))
                fill(row_cursor, ["standardprice", "saleprice"], str(sz_cfg['price']))
                fill(row_cursor, ["salestartdate"], start_date); fill(row_cursor, ["saleenddate"], end_date)
                fill(row_cursor, ["mainimageurl"], str(item["main"]))
                for idx, o_url in enumerate(str(item["others"]).split('\n')[:8]):
                    fill(row_cursor, [f"otherimageurl{idx+1}"], o_url.strip())
                for bi, b_text in enumerate(ai.get('bp', [])):
                    clean_bp = re.sub(r'^(Bullet\s?\d?[:.]?\s*|^\d[:.]?\s*)', '', str(b_text), flags=re.IGNORECASE).strip()
                    fill(row_cursor, [f"keyproductfeatures{bi+1}", f"bulletpoint{bi+1}"], clean_bp)
                fill(row_cursor, ["productdescription"], ai.get('desc', ''))
                fill(row_cursor, ["generickeywords"], format_amazon_kw(ai.get('element_word',''), global_kws))
                row_cursor += 1
            
            progress_bar.progress(20 + int((step + 1) / total_steps * 70))

        status_text.text("正在保存最終文件...")
        out = io.BytesIO()
        wb.save(out)
        wb.close()
        del wb
        gc.collect() 
        
        progress_bar.progress(100)
        status_text.text("✅ 生成完成！")
        st.download_button("💾 下載修復版文件", out.getvalue(), "Amazon_V50_Final.xlsm")
    except Exception as e:
        st.error(f"❌ 錯誤: {e}")
        gc.collect()
