import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import re
from datetime import datetime, timedelta
from openai import OpenAI
import openpyxl
from openpyxl.styles import Font, Alignment
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 規格鎖定版 V6.9", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心工具函數 ---
def clean_text(text):
    if not text: return ""
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

def safe_keyword_cut(raw_text, limit=245):
    """嚴格執行 245 字符截斷，不截斷單詞"""
    clean_words = re.findall(r'\b[a-z0-9]{2,}\b', raw_text.lower())
    unique_words = []
    seen = set()
    current_length = 0
    for w in clean_words:
        if w not in seen:
            new_len = current_length + len(w) + (1 if current_length > 0 else 0)
            if new_len <= limit:
                unique_words.append(w)
                seen.add(w)
                current_length = new_len
            else:
                break
    return " ".join(unique_words)

def reset_cell(cell, bold=False):
    cell.font = Font(name='Arial', size=10, bold=bold)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    img = Image.open(file)
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=65)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_parallel(img_file, sku_prefix, user_kw):
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img_fast(img_file)
        prompt = f"Amazon Listing Expert. Analyze art pattern. Return JSON: {{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}. Pool: {user_kw}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=30
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except Exception as e:
        return {"prefix": sku_prefix, "data": {}}

# --- 3. 主界面 ---
st.title("⚡ 亞馬遜 AI 精細化填充 V6.9")

with st.sidebar:
    brand_name = st.text_input("Brand Name", value="AMAZING WALL")
    st.divider()
    st.subheader("規格與定價")
    default_df = pd.DataFrame([
        {"Size": '16x24"', "Price": "12.99", "No": "001"},
        {"Size": '24x36"', "Price": "19.99", "No": "002"},
        {"Size": '32x48"', "Price": "29.99", "No": "003"}
    ])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批量圖片 (檔名為前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 關鍵詞庫", height=150)
uploaded_tpl = st.file_uploader("📂 上傳亞馬遜模板 (XLSX)", type=['xlsx', 'xlsm'])

# --- 4. 執行處理 ---
if st.button("🚀 啟動優化填充", use_container_width=True):
    if not uploaded_imgs or not uploaded_tpl:
        st.error("❌ 請上傳圖片及模板")
    else:
        try:
            with st.status("🚄 AI 視覺分析中...") as status:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    results = list(executor.map(lambda img: call_ai_parallel(img, os.path.splitext(img.name)[0], user_all_kw), uploaded_imgs))

                wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
                sheet = wb.active
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]

                curr_row = 5 # 子類起始行
                parent_row = 4 # 表格第一行數據（父體行）
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=365)).strftime('%Y-%m-%d')
                
                for idx, res in enumerate(results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue

                    pattern = data.get('color', 'Modern')
                    final_st = safe_keyword_cut(f"{pattern} {data.get('keywords','')} {user_all_kw}")
                    bt = f"{brand_name} {data.get('title','')}"
                    full_color = f"{pattern} {data.get('keywords','')}"

                    # 規則：Parent SKU 範圍命名
                    p_sku = f"{prefix}-{size_price_data.iloc[0]['No']}-{size_price_data.iloc[-1]['No']}"

                    def fill_cell(r_idx, k, v, bold=False):
                        target = k.lower().replace(" ", "")
                        if target in h:
                            reset_cell(sheet.cell(row=r_idx, column=h[target], value=clean_text(v)), bold=bold)

                    # --- 填充第一行 (Row 4 - 父體) ---
                    if idx == 0:
                        fill_cell(parent_row, "sellersku", p_sku)
                        fill_cell(parent_row, "parentsku", p_sku)
                        fill_cell(parent_row, "parentage", "parent")
                        fill_cell(parent_row, "productname", bt[:199])
                        fill_cell(parent_row, "generickeyword", final_st)
                        fill_cell(parent_row, "productdescription", data.get('desc',''))
                        # 父體顏色同步
                        fill_cell(parent_row, "color", full_color)
                        fill_cell(parent_row, "colormap", full_color)
                        for b_i, c_idx in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                reset_cell(sheet.cell(row=parent_row, column=c_idx, value=clean_text(data['bp'][b_i])))

                    # --- 填充子體 (Row 5+) ---
                    for _, s_row in size_price_data.iterrows():
                        sz, pr, no = str(s_row["Size"]), str(s_row["Price"]), str(s_row["No"])
                        # 規則修正：SKU 後綴加上尺碼
                        # 清理尺寸中的引號和空格：16x24" -> 16x24
                        sz_tag = sz.replace('"', '').replace(' ', '')
                        c_sku = f"{prefix}-{no}-{sz_tag}"
                        
                        fill_cell(curr_row, "sellersku", c_sku)
                        fill_cell(curr_row, "parentsku", p_sku)
                        fill_cell(curr_row, "parentage", "child")
                        fill_cell(curr_row, "productname", f"{bt} - {sz}"[:199])
                        fill_cell(curr_row, "size", sz)
                        fill_cell(curr_row, "sizemap", sz)
                        fill_cell(curr_row, "color", full_color)
                        fill_cell(curr_row, "colormap", full_color)
                        fill_cell(curr_row, "standardprice", pr)
                        fill_cell(curr_row, "saleprice", pr)
                        fill_cell(curr_row, "salestartdate", s_start)
                        fill_cell(curr_row, "saleenddate", s_end)
                        fill_cell(curr_row, "generickeyword", final_st)
                        fill_cell(curr_row, "productdescription", data.get('desc',''))
                        
                        for b_i, c_idx in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                reset_cell(sheet.cell(row=curr_row, column=c_idx, value=clean_text(data['bp'][b_i])))
                        curr_row += 1

                status.update(label="✅ 優化填充完成！第一行已填充，SKU 已修正。", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載修正版表格", output.getvalue(), "Amazon_V6.9_Fixed.xlsm", use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ 嚴重錯誤: {e}")
