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

# --- 1. 页面配置 ---
st.set_page_config(page_title="亚马逊 AI 专家系统 V6.8", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心 AI 指令 ---
SYSTEM_LOGIC = """
You are an Amazon Listing Expert. Language: English. Weight: Left-to-Right.
1. Title: [Brand] + Category Phrase (Group I) + Pattern element + Benefit. Length: 130-150 chars. (DO NOT add the word 'Brand' manually).
2. Search Terms: Individual words only. Sequence: Pattern elements > AI extracted keywords > Generic words. 
3. Bullets: 5 points with bold headers.
4. Description: HTML format.
5. Color: Identify main pattern theme as a single descriptive word.
"""

# --- 3. 工具函数 ---
def safe_keyword_cut(raw_text, limit=245):
    """确保关键词不截断单词且不超过 245 字符"""
    words = re.findall(r'\b[a-z0-9]{2,}\b', raw_text.lower())
    unique_words = []
    seen = set()
    current_length = 0
    for w in words:
        if w not in seen:
            new_len = current_length + len(w) + (1 if current_length > 0 else 0)
            if new_len <= limit:
                unique_words.append(w)
                seen.add(w)
                current_length = new_len
            else: break
    return " ".join(unique_words)

def reset_cell(cell, bold=False):
    """强制重置字体，彻底根除乱码"""
    cell.font = Font(name='Arial', size=10, bold=bold)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    img = Image.open(file)
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=60)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_parallel(img_file, sku_prefix, user_kw):
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img_fast(img_file)
        prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\nKeyword Pool:\n{user_kw}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=25
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except:
        return {"prefix": sku_prefix, "data": {}}

# --- 4. 主界面 ---
st.title("🚀 亚马逊 AI 全自动化上架 V6.8")

col_cfg, col_sz = st.columns([1, 2])
with col_cfg:
    brand_name = st.text_input("Brand (仅填写品牌名)", value="YourBrand")
with col_sz:
    default_df = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批量上传图片 (SKU前缀如 001, 002)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 关键词方案 (Ⅰ-Ⅴ 类词组 + 通用单词)", height=150)

# --- 5. 执行逻辑 ---
if st.button("🚀 开始极速生成", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 请先上传图片")
    else:
        try:
            with st.status("🚄 正在并行处理多款式文案...") as status:
                # 1. 提取所有 SKU 前缀并计算父 SKU 命名范围
                sku_prefixes = sorted([os.path.splitext(img.name)[0] for img in uploaded_imgs])
                if len(sku_prefixes) > 1:
                    parent_sku_base = f"{sku_prefixes[0]}-{sku_prefixes[-1]}"
                else:
                    parent_sku_base = sku_prefixes[0]
                parent_sku_final = f"{parent_sku_base}-P"
                
                # 2. 并行调用 AI
                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(lambda img: call_ai_parallel(img, os.path.splitext(img.name)[0], user_all_kw), uploaded_imgs))
                
                # 3. 加载模板
                tpl = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl), keep_vba=True)
                sheet = wb.active
                h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "key product features" in str(c.value).lower()]

                curr_row = 5
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')

                for idx, res in enumerate(results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    
                    pattern = data.get('color', 'Modern')
                    final_st = safe_keyword_cut(f"{pattern} {data.get('keywords','')} {user_all_kw}")
                    
                    # 标题优化：不再手动添加 "Brand" 单词
                    full_title = f"{brand_name} {data.get('title','')}"

                    # --- 填充父体 (Row 4) ---
                    if idx == 0:
                        def fill_p(name, val):
                            if name in h: reset_cell(sheet.cell(row=4, column=h[name], value=str(val).strip()))
                        fill_p("seller sku", parent_sku_final) # 使用动态范围命名
                        fill_p("parentage", "parent")
                        fill_p("product name", full_title)
                        fill_p("product description", data.get('desc', ''))
                        fill_p("generic keyword", final_st)
                        for i, c_idx in enumerate(bp_cols[:5]):
                            if i < len(data.get('bp', [])): reset_cell(sheet.cell(row=4, column=c_idx, value=data['bp'][i]))

                    # --- 填充子体 (Row 5+) ---
                    for _, row in size_price_data.iterrows():
                        sz, pr = str(row["Size"]), str(row["Price"])
                        child_sku = f"{prefix}-{sz.replace('\"','').replace(' ','')}"
                        def fill_c(name, val):
                            if name in h: reset_cell(sheet.cell(row=curr_row, column=h[name], value=str(val).strip()))
                        
                        fill_c("seller sku", child_sku)
                        fill_c("parent sku", parent_sku_final) # 链接至动态父 SKU
                        fill_c("parentage", "child")
                        fill_c("product name", f"{full_title} - {sz}"[:150])
                        fill_c("sale price", pr)
                        fill_c("size", sz)
                        fill_c("size map", sz)
                        fill_c("sale start date", s_start)
                        fill_c("sale end date", s_end)
                        fill_c("product description", data.get('desc', ''))
                        fill_c("generic keyword", final_st)
                        fill_c("color", pattern)
                        fill_c("color map", pattern)
                        for i, c_idx in enumerate(bp_cols[:5]):
                            if i < len(data.get('bp', [])): reset_cell(sheet.cell(row=curr_row, column=c_idx, value=data['bp'][i]))
                        curr_row += 1
                
                status.update(label=f"✅ 完成！父体 SKU 已设为: {parent_sku_final}", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V6.8 最终修正版", output.getvalue(), f"Amazon_Listing_V6.8.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
