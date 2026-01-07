import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI
from datetime import datetime, timedelta

# --- 1. 核心工具 ---
def clean_copy_text(text):
    """精確清洗：僅移除 JSON 包裝，絕對保留標點符號"""
    if pd.isna(text) or str(text).strip() == "": return ""
    # 不使用 re.sub 以免誤傷標點，只處理 JSON 殘留
    return str(text).replace('["', '').replace('"]', '').replace('"', '"').strip()

def format_amazon_kw(elements, global_kws):
    """保持原有關鍵詞邏輯：單詞化、去重、空格間隔"""
    raw_str = f"{elements} {global_kws}".replace(",", " ").replace(";", " ")
    words = raw_str.split()
    seen = set()
    res = []
    for w in words:
        w_clean = re.sub(r'[^a-zA-Z0-9]', '', w).lower()
        if w_clean and w_clean not in seen:
            res.append(w_clean)
            seen.add(w_clean)
    return " ".join(res)[:245]

# --- 2. 頁面配置 ---
st.set_page_config(page_title="亞馬遜專家 V42", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V42")
st.success("✅ 規則鎖定：保留標點(如 16x24\")、顏色精簡(如 Beach)、五點直接輸出正文。")

# --- 3. 全局運營配置 ---
with st.sidebar:
    st.header("📢 配置中心")
    global_kws = st.text_area("✨ 通用關鍵詞單詞庫", "canvas wall art decor")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 款式管理 ---
if 'v42_rows' not in st.session_state: st.session_state.v42_rows = 1
sku_items = []
for i in range(st.session_state.v42_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 1.5])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with c3: o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v42_rows += 1
    st.rerun()

tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行生成 ---
if st.button("🚀 啟動 V42 生成", type="primary") and tpl_file and api_key:
    with st.spinner('AI 正在精準生成文案...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            h = {}
            for r_idx in range(1, 6):
                for cell in sheet[r_idx]:
                    if cell.value:
                        clean_n = re.sub(r'[^a-z0-9]', '', str(cell.value).lower())
                        if clean_n: h[clean_n] = cell.column
            
            start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            end_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            client = OpenAI(api_key=api_key)
            row_cursor = 4

            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                # 強化指令：嚴禁序號，精簡顏色
                prompt = f"""Act as Amazon SEO expert. 
                Task: Analyze image. 
                Output JSON: {{ 
                    "title": "short descriptive title", 
                    "color_word": "ONLY one single core element word, e.g., 'Beach' or 'Forest'", 
                    "bp": ["Direct content only. NO 'Bullet 1:' or numbering."], 
                    "desc": "HTML formatted description" 
                }}
                Bullets must cover: Pain points, Features, Scenes, Installation, Specs."""
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                p_sku = f"{item['pfx']}-P"
                rows_cfg = [
                    {"t":"P","s":p_sku,"sz":"","pr":""},
                    {"t":"C","s":f"{item['pfx']}-{s1}","sz":s1,"pr":p1},
                    {"t":"C","s":f"{item['pfx']}-{s2}","sz":s2,"pr":p2},
                    {"t":"C","s":f"{item['pfx']}-{s3}","sz":s3,"pr":p3}
                ]
                
                for r in rows_cfg:
                    def fill(k_list, v):
                        for k in k_list:
                            c_idx = h.get(re.sub(r'[^a-z0-9]', '', k.lower()))
                            if c_idx: 
                                sheet.cell(row=row_cursor, column=c_idx, value=clean_copy_text(v))
                                break

                    fill(["sellersku"], r["s"])
                    fill(["mainimageurl"], item["main"])
                    for idx, o_url in enumerate(item["others"].split('\n')[:8]):
                        fill([f"otherimageurl{idx+1}"], o_url.strip())

                    if r["t"] == "C":
                        fill(["parentsku"], p_sku)
                        # 標題及尺寸：完整保留標點符號
                        fill(["productname"], f"{brand} {ai['title']} {ai['color_word']} - {r['sz']}")
                        fill(["color", "colour", "colormap"], ai['color_word']) # 顏色精簡
                        fill(["size", "itemsize", "sizemap"], r['sz']) # 尺寸保留引號
                        fill(["standardprice", "saleprice"], r['pr'])
                        fill(["salestartdate"], start_date)
                        fill(["saleenddate"], end_date)
                    else:
                        fill(["productname"], f"{brand} {ai['title']} {ai['color_word']}")

                    # 五點描述：清除 AI 可能生成的序號前綴
                    for bi, b_text in enumerate(ai.get('bp', [])):
                        clean_bp = re.sub(r'^(Bullet\s?\d?[:.]?\s*|^\d[:.]?\s*)', '', b_text, flags=re.IGNORECASE).strip()
                        fill([f"keyproductfeatures{bi+1}", f"bulletpoint{bi+1}"], clean_bp)
                    
                    fill(["productdescription"], ai.get('desc', ''))
                    fill(["generickeywords"], format_amazon_kw(ai.get('color_word', ''), global_kws))
                    row_cursor += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ V42 修正版生成完成！")
            st.download_button("💾 下載文件", out.getvalue(), "Amazon_V42.xlsm")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
