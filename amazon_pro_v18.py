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
    """標題單詞去重邏輯"""
    words = title.split()
    seen = set()
    res = []
    for w in words:
        clean_w = re.sub(r'[^a-zA-Z0-9]', '', w).lower()
        if clean_w not in seen:
            res.append(w)
            seen.add(clean_w)
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
st.set_page_config(page_title="亞馬遜專家 V45", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V45")
st.success("✅ V45 優化點：標題單詞物理去重、Color 字段禁用顏色詞、其餘功能保持穩定。")

with st.sidebar:
    st.header("📢 配置中心")
    global_kws = st.text_area("✨ 通用關鍵詞單詞庫", "canvas wall art decor")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

if 'v45_rows' not in st.session_state: st.session_state.v45_rows = 1
sku_items = []
for i in range(st.session_state.v45_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 1.5])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with c3: o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v45_rows += 1; st.rerun()

tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行生成 ---
if st.button("🚀 啟動 V45 生成", type="primary") and tpl_file and api_key:
    with st.spinner('正在分析圖片並執行去重邏輯...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            h = {re.sub(r'[^a-z0-9]', '', str(cell.value).lower()): cell.column 
                 for r in range(1, 6) for cell in sheet[r] if cell.value}
            
            start_date, end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"), (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            client = OpenAI(api_key=api_key)
            row_cursor = 4

            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                # 強化指令：禁止重複單詞，禁止顏色詞
                prompt = f"""Act as Amazon SEO expert. JSON Output: {{ 
                    "title": "Extended title 150-200 chars. Use unique words ONLY.", 
                    "element_word": "ONLY one element word like Beach or Forest. NO color words like Blue/Red.", 
                    "bp": ["Bullet1", "Bullet2", "Bullet3", "Bullet4", "Bullet5"],
                    "desc": "HTML formatted description"
                }}"""
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                p_sku = f"{item['pfx']}-P"
                rows_cfg = [{"t":"P","s":p_sku,"sz":"","pr":""},
                            {"t":"C","s":f"{item['pfx']}-{s1}","sz":s1,"pr":p1},
                            {"t":"C","s":f"{item['pfx']}-{s2}","sz":s2,"pr":p2},
                            {"t":"C","s":f"{item['pfx']}-{s3}","sz":s3,"pr":p3}]
                
                for r in rows_cfg:
                    def fill(k_list, v):
                        for k in k_list:
                            c_idx = h.get(re.sub(r'[^a-z0-9]', '', k.lower()))
                            if c_idx: sheet.cell(row=row_cursor, column=c_idx, value=clean_copy_text(v))

                    fill(["sellersku"], r["s"])
                    fill(["mainimageurl"], item["main"])
                    for idx, o_url in enumerate(item["others"].split('\n')[:8]):
                        fill([f"otherimageurl{idx+1}"], o_url.strip())

                    # 標題去重處理
                    raw_title = f"{brand} {ai['title']} {ai['element_word']}"
                    clean_title = deduplicate_title(raw_title)

                    if r["t"] == "C":
                        fill(["parentsku"], p_sku)
                        fill(["productname"], f"{clean_title} - {r['sz']}")
                        fill(["color", "colour", "colormap", "colourmap"], ai['element_word'])
                        fill(["size", "itemsize", "sizemap"], r['sz'])
                        fill(["standardprice", "saleprice"], r['pr'])
                        fill(["salestartdate"], start_date); fill(["saleenddate"], end_date)
                    else:
                        fill(["productname"], clean_title)

                    for bi, b_text in enumerate(ai.get('bp', [])):
                        clean_bp = re.sub(r'^(Bullet\s?\d?[:.]?\s*|^\d[:.]?\s*)', '', b_text, flags=re.IGNORECASE).strip()
                        fill([f"keyproductfeatures{bi+1}", f"bulletpoint{bi+1}"], clean_bp)
                    
                    fill(["productdescription"], ai.get('desc', ''))
                    fill(["generickeywords", "searchterms"], format_amazon_kw(ai.get('element_word', ''), global_kws))
                    row_cursor += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ V45 生成完成！")
            st.download_button("💾 下載文件", out.getvalue(), "Amazon_V45.xlsm")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
