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
st.set_page_config(page_title="亚马逊 AI 极速填充 V6.2", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 增强型专业写作逻辑 (针对关键词丰富度与英文输出) ---
SYSTEM_LOGIC = """
You are an Amazon Listing Expert. All output must be in ENGLISH.
1. Title: Professional title (~120 chars). Format: [Brand] [Core Name] [Elements] [Occasion].
2. Search Terms (Keywords): Provide a rich list of individual words including: Core Keywords, Pattern elements (e.g., boho, vintage), Scenarios (e.g., office, bedroom), Material (e.g., canvas), and Functional words. 
   - Format: Single words separated by spaces. No commas.
3. Bullets: 5 complete points with bold headers. Each bullet must be 15-25 words long.
4. Description: HTML format with <b> and <br>.
5. Color: One or two specific color words.
"""

# --- 3. 辅助函数：关键词深度清洗与融合 ---
def enrich_and_clean_keywords(ai_kw, user_kw):
    """融合AI生成和用户库的关键词，去重并限制长度"""
    combined = f"{ai_kw} {user_kw}".lower()
    # 只保留英文和数字，去掉标点
    words = re.findall(r'\b[a-z0-9]+\b', combined)
    
    unique_words = []
    seen = set()
    for w in words:
        if w not in seen and len(w) > 1:
            unique_words.append(w)
            seen.add(w)
    
    # 组合成字符串并截断至 245 字符，确保不超标
    result = " ".join(unique_words)
    return result[:245].strip()

def process_img(file):
    img = Image.open(file)
    img.thumbnail((800, 800))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_task(img_file, sku_prefix, keywords):
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img(img_file)
        prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\nUser Material Keywords:{keywords}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=45
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except Exception as e:
        return {"prefix": sku_prefix, "data": {}}

# --- 4. 主界面 ---
st.title("⚡ 亚马逊 AI 极速填充系统 V6.2")

st.subheader("⚙️ 全局配置")
col_brand, col_price = st.columns([1, 2])
with col_brand:
    brand_name = st.text_input("品牌名 (Brand)", value="YourBrand")
with col_price:
    default_sp = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_sp, num_rows="dynamic")

col_img, col_kw = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上传图案图片", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_kw:
    user_keywords = st.text_area("📝 基础关键词库 (用于丰富结果)", height=150, placeholder="例如: canvas wall art, home decor, modern...")

# --- 5. 核心逻辑 ---
if st.button("🚀 开始生成并填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 请上传图片")
    else:
        try:
            with st.status("正在并行处理图片与文案...") as status:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(call_ai_task, img, os.path.splitext(img.name)[0], user_keywords) for img in uploaded_imgs]
                    all_results = [f.result() for f in futures]
                
                # 加载模板
                tpl_file = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl_file), keep_vba=True)
                sheet = wb.active
                
                # 建立表头索引
                headers = {str(cell.value).strip().lower(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if "key product features" in str(cell.value).lower()]

                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                current_row = 5
                
                for idx, res in enumerate(all_results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    
                    # 处理关键词与标题
                    rich_keywords = enrich_and_clean_keywords(data.get('keywords', ''), user_keywords)
                    full_base_title = f"{brand_name} {data.get('title', '')}"

                    # --- 填充逻辑：Row 4 (父体) ---
                    if idx == 0:
                        st.write(f"正在填充父体: {prefix}-P")
                        p_sku = f"{prefix}-P"
                        def write_p(col_name, val):
                            if col_name in headers: sheet.cell(row=4, column=headers[col_name], value=val)
                        
                        write_p("seller sku", p_sku)
                        write_p("parentage", "parent")
                        write_p("product name", full_base_title)
                        write_p("product description", data.get('desc', ''))
                        write_p("generic keyword", rich_keywords)
                        write_p("color", data.get('color', ''))
                        write_p("color map", data.get('color', ''))
                        for b_idx, c_idx in enumerate(bp_cols[:5]):
                            if b_idx < len(data.get('bp', [])):
                                sheet.cell(row=4, column=c_idx, value=data['bp'][b_idx])

                    # --- 填充逻辑：子体 ---
                    for _, row_data in size_price_data.iterrows():
                        sz, pr = str(row_data["Size"]), str(row_data["Price"])
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        
                        def write_c(col_name, val):
                            if col_name in headers: sheet.cell(row=current_row, column=headers[col_name], value=val)
                        
                        write_c("seller sku", c_sku)
                        write_c("parent sku", f"{all_results[0]['prefix']}-P")
                        write_c("parentage", "child")
                        write_c("product name", f"{full_base_title} - {sz}"[:150])
                        write_c("sale price", pr)
                        write_c("size", sz)
                        write_c("size map", sz)
                        write_c("sale start date", s_start)
                        write_c("sale end date", s_end)
                        write_c("product description", data.get('desc', ''))
                        write_c("generic keyword", rich_keywords)
                        write_c("color", data.get('color', ''))
                        write_c("color map", data.get('color', ''))
                        
                        # 子体五点写入
                        for b_idx, c_idx in enumerate(bp_cols[:5]):
                            if b_idx < len(data.get('bp', [])):
                                sheet.cell(row=current_row, column=c_idx, value=data['bp'][b_idx])
                        
                        current_row += 1
                
                status.update(label="✅ 极速填充完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 点击下载填充好的 Excel", output.getvalue(), f"Amazon_Listing_Final.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 运行中出现错误: {e}")
