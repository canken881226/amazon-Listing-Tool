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
st.set_page_config(page_title="亚马逊 AI 视觉专家 V7.4 - 对齐版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 深度视觉描述指令 ---
SYSTEM_LOGIC = """
You are an Amazon Listing Expert. 
1. Title: [Brand] + Category Phrase + [Vivid Pattern: e.g., 3D Window View Forest] + Style. No 'Brand' word. 140 chars.
2. Color/Color Map: IDENTIFY THE THEME WORD (e.g., MountainMist). Same word for BOTH fields. NO basic colors.
3. Search Terms: Max 240 chars. Unique words. No cut-off words.
"""

# --- 3. 核心工具函数 ---
def generate_slim_parent_sku(prefixes):
    """精简父 SKU 逻辑：082-087-P"""
    if not prefixes: return "PARENT-P"
    if len(prefixes) == 1: return f"{prefixes[0]}-P"
    s, e = prefixes[0], prefixes[-1]
    i = 0
    while i < min(len(s), len(e)) and s[i] == e[i]: i += 1
    last_dash = s[:i].rfind('-')
    return f"{s}-{e[last_dash+1:]}-P" if last_dash != -1 else f"{s}-{e}-P"

def safe_keyword_cut(raw_text, limit=245):
    """逐词截断，严禁切断单词"""
    words = re.findall(r'\b[a-z0-9]{2,}\b', raw_text.lower())
    unique, seen, cur_len = [], set(), 0
    for w in words:
        if w not in seen:
            new_len = cur_len + len(w) + (1 if current_length > 0 else 0) if 'current_length' in locals() else len(w)
            # 修正 current_length 逻辑
            if cur_len + len(w) + (1 if cur_len > 0 else 0) <= limit:
                unique.append(w); seen.add(w); cur_len += len(w) + (1 if cur_len > 0 else 0)
            else: break
    return " ".join(unique)

def reset_cell(cell, value=None):
    """强制重置字体彻底解决乱码"""
    if value is not None: cell.value = value
    cell.font = Font(name='Arial', size=10)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    img = Image.open(file)
    img.thumbnail((800, 800))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 4. 主界面 ---
st.title("🤖 亚马逊 AI 视觉填充专家 V7.4")

col_cfg, col_sz = st.columns([1, 2])
with col_cfg:
    brand_name = st.text_input("Brand (品牌名)", value="YourBrand")
    yupoo_base = st.text_input("又拍相册根地址", value="https://x.yupoo.com/photos/sqdqjp/albums/")
with col_sz:
    default_df = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 上传图片 (SKU 前缀命名)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 关键词方案库", height=100)

# --- 5. 执行逻辑 ---
if st.button("🚀 启动全自动精细填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 请上传图片")
    else:
        try:
            with st.status("🚄 正在执行自适应填充与链接生成...") as status:
                sku_prefixes = sorted([os.path.splitext(img.name)[0] for img in uploaded_imgs])
                parent_sku_final = generate_slim_parent_sku(sku_prefixes)
                
                def call_ai(img):
                    prefix = os.path.splitext(img.name)[0]
                    client = OpenAI(api_key=api_key)
                    b64 = process_img_fast(img)
                    prompt = f"{SYSTEM_LOGIC}\nSKU:{prefix}\nKW:{user_all_kw}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','theme_word':''}}"
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}], response_format={"type":"json_object"})
                    return {"prefix": prefix, "data": json.loads(res.choices[0].message.content)}

                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(call_ai, uploaded_imgs))
                
                tpl_path = os.path.join("templates", [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0])
                wb = openpyxl.load_workbook(tpl_path, keep_vba=True)
                sheet = wb.active
                
                h_map = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column + 1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                for idx, res in enumerate(results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    theme = data.get('theme_word', 'PatternArt')
                    st_words = safe_keyword_cut(f"{theme} {data.get('keywords','')} {user_all_kw}")
                    bt = f"{brand_name} {data.get('title','')}"

                    for _, s_row in size_price_data.iterrows():
                        if pd.isna(s_row['Size']): continue
                        
                        # 继承固定值并重置样式
                        for col, val in defaults.items():
                            reset_cell(sheet.cell(row=curr_row, column=col), value=val)
                        
                        def fill(name, val):
                            if name in h_map: reset_cell(sheet.cell(row=curr_row, column=h_map[name]), value=str(val).strip())
                        
                        sz_str = str(s_row['Size']).replace('\"','').replace(' ','')
                        fill("seller sku", f"{prefix}-{sz_str}")
                        fill("parent sku", parent_sku_final)
                        fill("parentage", "child")
                        fill("product name", f"{bt} - {s_row['Size']}"[:150])
                        fill("sale price", s_row['Price'])
                        fill("size", s_row['Size'])
                        fill("size map", s_row['Size'])
                        fill("product description", data.get('desc',''))
                        fill("generic keyword", st_words)
                        fill("color", theme); fill("color map", theme)
                        
                        # 自动拼接又拍链接
                        base = yupoo_base if yupoo_base.endswith('/') else yupoo_base + '/'
                        fill("main_image_url", f"{base}{prefix}/1.jpg")
                        fill("other_image_url1", f"{base}{prefix}/2.jpg")
                        fill("other_image_url2", f"{base}{prefix}/3.jpg")

                        bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "key product features" in str(c.value).lower()]
                        for i, c_idx in enumerate(bp_cols[:5]):
                            if i < len(data.get('bp', [])):
                                reset_cell(sheet.cell(row=curr_row, column=c_idx), value=data['bp'][i])
                        curr_row += 1

                # 独立处理父体（Row 4）
                for col, val in defaults.items(): reset_cell(sheet.cell(row=4, column=col), value=val)
                def fill_p(name, val):
                    if name in h_map: reset_cell(sheet.cell(row=4, column=h_map[name]), value=str(val).strip())
                fill_p("seller sku", parent_sku_final)
                fill_p("parentage", "parent")
                fill_p("product name", f"{brand_name} {results[0]['data'].get('title','')}")
                fill_p("color", ""); fill_p("color map", "")
                base = yupoo_base if yupoo_base.endswith('/') else yupoo_base + '/'
                fill_p("main_image_url", f"{base}{results[0]['prefix']}/1.jpg")

                status.update(label=f"✅ 完成！父 SKU: {parent_sku_final}", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V7.4 最终对齐表格", output.getvalue(), f"Listing_{parent_sku_final}.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 系统错误: {e}")
