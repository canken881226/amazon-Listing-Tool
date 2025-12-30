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

# --- 1. 页面配置 ---
st.set_page_config(page_title="亚马逊 AI 极速填充 V6.1", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 固化专业写作逻辑 (强制英文与单次关键词) ---
SYSTEM_LOGIC = """
You are an Amazon Listing Expert. All output must be in ENGLISH.
1. Title: Create a professional product title (around 120 chars). Do NOT include size.
2. Search Terms (Keywords): ONLY output individual words separated by spaces. No commas, no phrases, no repetition. Limit to 200 chars.
3. Bullets: 5 points. Start with bold headers.
4. Description: Use HTML tags (<b>, <br>). Focus on benefits and scenarios.
5. Color: Identify the main theme color/pattern as a single word.
"""

# --- 3. 辅助函数 ---
def clean_keywords(raw_kw):
    """确保关键词是单词、无重复、不超长"""
    words = re.findall(r'\b\w+\b', raw_kw.lower())
    unique_words = []
    for w in words:
        if w not in unique_words: unique_words.append(w)
    return " ".join(unique_words)[:240]

def process_img(file):
    img = Image.open(file)
    img.thumbnail((800, 800))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=65)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_task(img_file, sku_prefix, keywords):
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img(img_file)
        prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\nKeywords Pool:{keywords}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=30
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except:
        return {"prefix": sku_prefix, "data": {}}

# --- 4. 主界面 ---
st.title("⚡ 亚马逊 AI 极速填充系统 V6.1")

# 新增品牌名配置
st.subheader("⚙️ 品牌与尺寸配置")
col_brand, col_price = st.columns([1, 2])
with col_brand:
    brand_name = st.text_input("输入品牌名 (将置于标题开头)", value="YourBrand")
with col_price:
    default_sp = pd.DataFrame([{"Size": '16x24"', "Price": "9.99"},{"Size": '24x36"', "Price": "16.99"},{"Size": '32x48"', "Price": "18.99"}])
    size_price_data = st.data_editor(default_sp, num_rows="dynamic")

col_img, col_kw = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上传图片 (SKU前缀)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_kw:
    user_keywords = st.text_area("📝 关键词库 (作为AI编写素材)", height=150)

# --- 5. 执行逻辑 ---
if st.button("🚀 启动极速填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 请上传图片")
    else:
        try:
            with st.status("⚡ 正在处理任务...") as status:
                # 併發分析
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(call_ai_task, img, os.path.splitext(img.name)[0], user_keywords) for img in uploaded_imgs]
                    all_results = [f.result() for f in futures]
                
                # 写入 Excel
                wb = openpyxl.load_workbook(os.path.join(os.getcwd(), "templates", [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0]), keep_vba=True)
                sheet = wb.active
                headers = {str(cell.value).strip().lower(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if "key product features" in str(cell.value).lower()]

                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                current_row = 5
                
                for idx, res in enumerate(all_results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    
                    # 清洗关键词为单词格式
                    safe_keywords = clean_keywords(data.get('keywords', ''))
                    # 组合品牌标题
                    base_title = f"{brand_name} {data.get('title', '')}"

                    # 填充父体 (Row 4)
                    if idx == 0:
                        p_sku = f"{prefix}-P"
                        if "seller sku" in headers: sheet.cell(row=4, column=headers["seller sku"]).value = p_sku
                        if "parentage" in headers: sheet.cell(row=4, column=headers["parentage"]).value = "parent"
                        if "product name" in headers: sheet.cell(row=4, column=headers["product name"]).value = base_title
                        if "product description" in headers: sheet.cell(row=4, column=headers["product description"]).value = data.get('desc','')
                        if "generic keyword" in headers: sheet.cell(row=4, column=headers["generic keyword"]).value = safe_keywords
                        if "color" in headers: sheet.cell(row=4, column=headers["color"]).value = data.get('color','')
                        if "color map" in headers: sheet.cell(row=4, column=headers["color map"]).value = data.get('color','')
                        for b_idx, c_idx in enumerate(bp_cols[:5]):
                            sheet.cell(row=4, column=c_idx).value = data.get('bp',['','','','',''])[b_idx]

                    # 填充子体
                    for _, row_data in size_price_data.iterrows():
                        sz, pr = str(row_data["Size"]), str(row_data["Price"])
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        if "seller sku" in headers: sheet.cell(row=current_row, column=headers["seller sku"]).value = c_sku
                        if "parent sku" in headers: sheet.cell(row=current_row, column=headers["parent sku"]).value = f"{all_results[0]['prefix']}-P"
                        if "parentage" in headers: sheet.cell(row=current_row, column=headers["parentage"]).value = "child"
                        # 子体标题拼接尺寸
                        if "product name" in headers: sheet.cell(row=current_row, column=headers["product name"]).value = f"{base_title} - {sz}"[:150]
                        if "sale price" in headers: sheet.cell(row=current_row, column=headers["sale price"]).value = pr
                        if "size" in headers: sheet.cell(row=current_row, column=headers["size"]).value = sz
                        if "size map" in headers: sheet.cell(row=current_row, column=headers["size map"]).value = sz
                        if "sale start date" in headers: sheet.cell(row=current_row, column=headers["sale start date"]).value = s_start
                        if "sale end date" in headers: sheet.cell(row=current_row, column=headers["sale end date"]).value = s_end
                        if "product description" in headers: sheet.cell(row=current_row, column=headers["product description"]).value = data.get('desc','')
                        if "generic keyword" in headers: sheet.cell(row=current_row, column=headers["generic keyword"]).value = safe_keywords
                        if "color" in headers: sheet.cell(row=current_row, column=headers["color"]).value = data.get('color','')
                        if "color map" in headers: sheet.cell(row=current_row, column=headers["color map"]).value = data.get('color','')
                        for b_idx, c_idx in enumerate(bp_cols[:5]):
                            sheet.cell(row=current_row, column=c_idx).value = data.get('bp',['','','','',''])[b_idx]
                        current_row += 1
                
                status.update(label="⚡ 完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载表格", output.getvalue(), f"Listing_{datetime.now().strftime('%m%d')}.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 错误: {e}")
