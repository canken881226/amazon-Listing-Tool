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
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 權重埋詞版 V6.4", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 深度優化的 AI 權重指令 ---
SYSTEM_LOGIC = """
You are an Amazon Listing Expert. Follow the weight-based placement plan (Left to Right weight):
1. Title: Priority 1 (High Weight). Start with [Brand]. Use Main Category Phrases (Group I) + 1-2 Theme Phrases (Group III). Length: 130-150 chars.
2. Bullets: Priority 2. Use Expand Phrases (Group II) and Function words (Group V). Focus on quality, 3D effect, and scenarios.
3. Description: Priority 3. Use natural language with HTML tags. Include synonyms and long-tail phrases.
4. Search Terms: ONLY individual words. Blend [Generic Words] + [Pattern Elements] + [Function words]. No repetition.
5. Color: Identify the MAIN PATTERN (e.g., Autumn Forest, Blue Ocean).
"""

# --- 3. 核心清洗與權重融合函數 ---
def clean_st_words(ai_keywords, user_words, pattern_element):
    """將單詞庫與圖案元素深度融合，權重從左往右，限長 245 字符"""
    # 融合順序：圖案元素 > AI 提取詞 > 通用單詞庫
    combined = f"{pattern_element} {ai_keywords} {user_words}".lower().replace(',', ' ').replace('.', ' ')
    words = re.findall(r'\b[a-z0-9]{2,}\b', combined)
    
    unique_words = []
    seen = set()
    for w in words:
        if w not in seen:
            unique_words.append(w)
            seen.add(w)
    
    res = " ".join(unique_words)
    return res[:245].strip()

def process_img(file):
    img = Image.open(file)
    img.thumbnail((800, 800))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_task(img_file, sku_prefix, all_kw_input):
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img(img_file)
        prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\nKeyword Pool:\n{all_kw_input}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=45
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except:
        return {"prefix": sku_prefix, "data": {}}

# --- 4. 主界面 ---
st.title("🤖 亞馬遜 AI 權重埋詞填充系統 V6.4")

st.subheader("⚙️ 基礎配置")
col_brand, col_price = st.columns([1, 2])
with col_brand:
    brand_input = st.text_input("Brand (品牌名)", value="YourBrand")
with col_price:
    default_sp = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_sp, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 上傳圖片 (SKU前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_keywords = st.text_area("📝 填入完整關鍵詞方案 (詞組 + 單詞)", placeholder="請粘貼您的 Ⅰ-Ⅴ 類詞組以及通用單詞庫...", height=250)

# --- 5. 執行填充 ---
if st.button("🚀 啟動權重埋詞處理", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 未發現圖片")
    else:
        try:
            with st.status("⚡ 正在分析圖案並執行權重埋詞...") as status:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(call_ai_task, img, os.path.splitext(img.name)[0], user_all_keywords) for img in uploaded_imgs]
                    all_results = [f.result() for f in futures]
                
                # 自動抓取 templates 文件夾下的第一個 xlsx/xlsm
                tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl_list[0]), keep_vba=True)
                sheet = wb.active
                
                headers = {str(cell.value).strip().lower(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if "key product features" in str(cell.value).lower()]

                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                current_row = 5
                
                for idx, res in enumerate(all_results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    
                    pattern_element = data.get('color', 'Modern')
                    # Search Terms 融合：圖案元素 + AI 關鍵詞 + 用戶單詞庫
                    final_st = clean_st_words(data.get('keywords', ''), user_all_keywords, pattern_element)
                    brand_title = f"{brand_input} {data.get('title', '')}"

                    # --- 填充父體 (Row 4) ---
                    if idx == 0:
                        row_p = 4
                        def fill_p(name, val):
                            if name in headers: sheet.cell(row=row_p, column=headers[name], value=str(val).strip())
                        
                        fill_p("seller sku", f"{prefix}-P")
                        fill_p("parentage", "parent")
                        fill_p("product name", brand_title)
                        fill_p("product description", data.get('desc', ''))
                        fill_p("generic keyword", final_st)
                        fill_p("color", "") # 父類 Color 放空
                        fill_p("color map", "")
                        for b_i, c_i in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                sheet.cell(row=row_p, column=c_i, value=data['bp'][b_i])

                    # --- 填充子體 ---
                    for _, r_data in size_price_data.iterrows():
                        sz, pr = str(r_data["Size"]), str(r_data["Price"])
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        
                        def fill_c(name, val):
                            if name in headers: sheet.cell(row=current_row, column=headers[name], value=str(val).strip())
                        
                        fill_c("seller sku", c_sku)
                        fill_c("parent sku", f"{all_results[0]['prefix']}-P")
                        fill_c("parentage", "child")
                        fill_c("product name", f"{brand_title} - {sz}"[:150])
                        fill_c("sale price", pr)
                        fill_c("size", sz)
                        fill_c("size map", sz)
                        fill_c("sale start date", s_start)
                        fill_c("sale end date", s_end)
                        fill_c("product description", data.get('desc', ''))
                        fill_c("generic keyword", final_st)
                        fill_c("color", pattern_element)
                        fill_c("color map", pattern_element)
                        
                        for b_i, c_i in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                sheet.cell(row=current_row, column=c_i, value=data['bp'][b_i])
                        current_row += 1
                
                status.update(label="✅ 權重埋詞完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載填充好的表格", output.getvalue(), f"Amazon_Listing_V6.4.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 嚴重錯誤: {e}")
