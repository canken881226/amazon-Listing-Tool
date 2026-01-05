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
st.set_page_config(page_title="亞馬遜 AI 規格鎖定 V7.0", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心工具函數 ---
def clean_text(text):
    if not text: return ""
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

def safe_keyword_cut(raw_text, limit=245):
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
st.title("⚡ 亞馬遜 AI 精細化填充 V7.0")

with st.sidebar:
    brand_name = st.text_input("Brand Name", value="AMAZING WALL")
    st.divider()
    st.subheader("變體尺寸與定價")
    default_df = pd.DataFrame([
        {"Size": '16x24"', "Price": "12.99"},
        {"Size": '24x36"', "Price": "19.99"},
        {"Size": '32x48"', "Price": "29.99"}
    ])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批量圖片 (檔名為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 關鍵詞庫 (Search Terms Pool)", height=150)
uploaded_tpl = st.file_uploader("📂 上傳模板 Excel", type=['xlsx', 'xlsm'])

# --- 4. 執行處理 ---
if st.button("🚀 啟動優化填充", use_container_width=True):
    if not uploaded_imgs or not uploaded_tpl:
        st.error("❌ 請上傳圖片及模板")
    else:
        try:
            with st.status("🚄 AI 視覺分析與規格對位中...") as status:
                # 併發分析所有款式
                with ThreadPoolExecutor(max_workers=5) as executor:
                    results = list(executor.map(lambda img: call_ai_parallel(img, os.path.splitext(img.name)[0], user_all_kw), uploaded_imgs))

                wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
                sheet = wb.active
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]

                curr_row = 5 # 子類起始行
                parent_row = 4 # 表格第一行 (父體)
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=365)).strftime('%Y-%m-%d')
                
                # 计算总父类 SKU 范围 (基于所有上传图片的前缀)
                all_pfxs = [res["prefix"] for res in results if res["data"]]
                if len(all_pfxs) > 1:
                    # 提取前缀末尾的数字逻辑
                    nums = [int(re.findall(r'\d+', p)[-1]) for p in all_pfxs if re.findall(r'\d+', p)]
                    base_part = all_pfxs[0].rsplit('-', 1)[0] if '-' in all_pfxs[0] else all_pfxs[0]
                    p_sku_total = f"{base_part}-{min(nums):02d}-{max(nums):02d}" if nums else all_pfxs[0]
                else:
                    p_sku_total = all_pfxs[0] if all_pfxs else "PARENT-SKU"

                # 填充第一行 (父體數據)
                first_res = results[0]
                if first_res["data"]:
                    def fill_p(k, v):
                        target = k.lower().replace(" ", "")
                        if target in h: reset_cell(sheet.cell(row=parent_row, column=h[target], value=clean_text(v)))
                    
                    fill_p("sellersku", p_sku_total)
                    fill_p("parentage", "parent")
                    fill_p("productname", f"{brand_name} {first_res['data'].get('title','')}"[:199])
                    fill_p("generickeyword", safe_keyword_cut(f"{first_res['data'].get('color','')} {first_res['data'].get('keywords','')} {user_all_kw}"))
                    fill_p("productdescription", first_res['data'].get('desc',''))
                    # 規則：父體行 Parent SKU, Color, Color Map 不填
                    fill_p("parentsku", "")
                    fill_p("color", "")
                    fill_p("colormap", "")
                    for b_i, c_idx in enumerate(bp_cols[:5]):
                        if b_i < len(first_res['data'].get('bp', [])):
                            reset_cell(sheet.cell(row=parent_row, column=c_idx, value=clean_text(first_res['data']['bp'][b_i])))

                # 循環填充子體
                for res in results:
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    
                    pattern = data.get('color', 'Modern')
                    final_st = safe_keyword_cut(f"{pattern} {data.get('keywords','')} {user_all_kw}")
                    bt = f"{brand_name} {data.get('title','')}"
                    full_color = f"{pattern} {data.get('keywords','')}"

                    for _, s_row in size_price_data.iterrows():
                        sz, pr = str(s_row["Size"]), str(s_row["Price"])
                        sz_tag = sz.replace('"', '').replace(' ', '')
                        # 子類 SKU 邏輯：前綴-尺寸
                        c_sku = f"{prefix}-{sz_tag}"
                        
                        def fill_c(k, v):
                            target = k.lower().replace(" ", "")
                            if target in h: reset_cell(sheet.cell(row=curr_row, column=h[target], value=clean_text(v)))

                        fill_c("sellersku", c_sku)
                        fill_c("parentsku", p_sku_total) # 子類需要填寫父類 SKU 關聯
                        fill_c("parentage", "child")
                        fill_c("productname", f"{bt} - {sz}"[:199])
                        fill_c("size", sz)
                        fill_c("sizemap", sz)
                        fill_c("color", full_color)
                        fill_c("colormap", full_color)
                        fill_c("standardprice", pr)
                        fill_c("saleprice", pr)
                        fill_c("salestartdate", s_start)
                        fill_c("saleenddate", s_end)
                        fill_c("generickeyword", final_st)
                        fill_c("productdescription", data.get('desc',''))
                        
                        for b_i, c_idx in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                reset_cell(sheet.cell(row=curr_row, column=c_idx, value=clean_text(data['bp'][b_i])))
                        curr_row += 1

                status.update(label="✅ 優化填充完成！父類範圍 SKU 已計算，第一行已處理。", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載 V7.0 鎖定版表格", output.getvalue(), "Amazon_V7.0_Fixed.xlsm", use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ 嚴重錯誤: {e}")
