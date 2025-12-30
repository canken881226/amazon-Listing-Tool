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
st.set_page_config(page_title="亚马逊 AI 极速填充 V6.3", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 深度优化的 AI 指令 ---
SYSTEM_LOGIC = """
You are an Amazon Listing Expert. All output in ENGLISH.
1. Title: Professional title (120-130 chars). Start with Brand.
2. Search Terms: Extract individual words only: Core keywords + Pattern Elements (e.g., Abstract, Floral, Zen) + Scenarios (e.g., Office, Home Decor) + Functional words (e.g., Gift, Modern). No commas.
3. Bullets: 5 points. Focus on quality, size details, 3D effect, easy to hang, and gift value.
4. Description: HTML format.
5. Color: Identify the MAIN PATTERN ELEMENT (e.g., Forest, BlueGeometric, Minimalist) as a specific color value.
"""

# --- 3. 核心清洗函数 ---
def clean_for_excel(text):
    """移除可能导致 Excel 显示乱码的特殊字符"""
    if not text: return ""
    # 只保留可见字符和标准标点，移除特殊转义符
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    return text.strip()

def enrich_keywords(ai_kw, user_kw):
    """强力融合关键词：单词化、去重、限长 245 字符"""
    raw_combined = f"{ai_kw} {user_kw}".lower().replace(',', ' ').replace('.', ' ')
    words = re.findall(r'\b[a-z0-9]{2,}\b', raw_combined)
    
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

def call_ai_task(img_file, sku_prefix, keywords):
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img(img_file)
        prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\nKeywords:{keywords}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=40
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except:
        return {"prefix": sku_prefix, "data": {}}

# --- 4. 主界面 ---
st.title("🤖 亚马逊 AI 极速填充系统 V6.3")

st.subheader("⚙️ 核心配置")
col_brand, col_price = st.columns([1, 2])
with col_brand:
    brand_input = st.text_input("Brand (品牌名)", value="YourBrand")
with col_price:
    default_sp = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_sp, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 上传图案图片", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_keywords = st.text_area("📝 扩展词库", placeholder="粘贴关键词，AI 会自动融合去重...")

# --- 5. 执行填充 ---
if st.button("🚀 启动极速处理", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 未发现图片")
    else:
        try:
            with st.status("⚡ 正在并行生成文案并精准映射...") as status:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(call_ai_task, img, os.path.splitext(img.name)[0], user_keywords) for img in uploaded_imgs]
                    all_results = [f.result() for f in futures]
                
                tpl_path = os.path.join("templates", [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0])
                wb = openpyxl.load_workbook(tpl_path, keep_vba=True)
                sheet = wb.active
                
                headers = {str(cell.value).strip().lower(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if "key product features" in str(cell.value).lower()]

                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                current_row = 5
                
                for idx, res in enumerate(all_results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    
                    full_keywords = enrich_keywords(data.get('keywords', ''), user_keywords)
                    brand_title = f"{brand_input} {data.get('title', '')}"
                    pattern_color = clean_for_excel(data.get('color', 'Multi-color'))

                    # --- 填充父体 (Row 4) ---
                    if idx == 0:
                        row_p = 4
                        def fill_p(name, val):
                            if name in headers: sheet.cell(row=row_p, column=headers[name], value=clean_for_excel(val))
                        
                        fill_p("seller sku", f"{prefix}-P")
                        fill_p("parentage", "parent")
                        fill_p("product name", brand_title)
                        fill_p("product description", data.get('desc', ''))
                        fill_p("generic keyword", full_keywords)
                        # 父类 Color 放空
                        fill_p("color", "")
                        fill_p("color map", "")
                        for b_i, c_i in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                sheet.cell(row=row_p, column=c_i, value=clean_for_excel(data['bp'][b_i]))

                    # --- 填充子体 ---
                    for _, r_data in size_price_data.iterrows():
                        sz, pr = str(r_data["Size"]), str(r_data["Price"])
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        
                        def fill_c(name, val):
                            if name in headers: sheet.cell(row=current_row, column=headers[name], value=clean_for_excel(val))
                        
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
                        fill_c("generic keyword", full_keywords)
                        # 子类使用图案词填充 Color
                        fill_c("color", pattern_color)
                        fill_c("color map", pattern_color)
                        
                        for b_i, c_i in enumerate(bp_cols[:5]):
                            if b_i < len(data.get('bp', [])):
                                sheet.cell(row=current_row, column=c_i, value=clean_for_excel(data['bp'][b_i]))
                        current_row += 1
                
                status.update(label="✅ 填充已完成，已优化显示与颜色逻辑", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载优化后的表格", output.getvalue(), f"Amazon_V6.3.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 运行失败: {e}")
