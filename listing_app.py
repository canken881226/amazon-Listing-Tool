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
st.set_page_config(page_title="亚马逊 AI 专家 V7.2 - 链接自动化版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心 AI 指令 ---
SYSTEM_LOGIC = """
You are an Amazon Listing Optimization Expert.
1. Title: [Brand] + [Category Phrase] + [Vivid Pattern Description] + [Style]. No 'Brand' word.
2. Color/Color Map: IDENTIFY THE THEME WORD (e.g., AutumnForest). Use it for BOTH.
3. Search Terms: Max 240 chars. Individual words.
"""

# --- 3. 工具函数 ---
def generate_slim_parent_sku(prefixes):
    if not prefixes: return "PARENT-P"
    if len(prefixes) == 1: return f"{prefixes[0]}-P"
    s, e = prefixes[0], prefixes[-1]
    i = 0
    while i < min(len(s), len(e)) and s[i] == e[i]: i += 1
    last_dash = s[:i].rfind('-')
    return f"{s}-{e[last_dash+1:]}-P" if last_dash != -1 else f"{s}-{e}-P"

def reset_cell(cell):
    cell.font = Font(name='Arial', size=10)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    img = Image.open(file)
    img.thumbnail((800, 800))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 4. 主界面 ---
st.title("🤖 亚马逊 AI 专家填充系统 V7.2")

col_cfg, col_sz = st.columns([1, 2])
with col_cfg:
    brand_name = st.text_input("Brand", value="YourBrand")
    yupoo_base = st.text_input("又拍相册根地址 (末尾加斜杠)", value="https://x.yupoo.com/photos/username/albums/")
    st.info("💡 链接生成逻辑：根地址 + SKU + /1.jpg (主图)")
with col_sz:
    default_df = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批量上传主图 (SKU前缀命名)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 关键词方案", height=100)

# --- 5. 执行逻辑 ---
if st.button("🚀 启动全自动填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 未上传图片")
    else:
        try:
            with st.status("🚄 正在同步文案与图片链接...") as status:
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
                
                tpl = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl), keep_vba=True)
                sheet = wb.active
                
                # 建立表头索引
                header_map = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                # 扫描第4行所有默认值
                template_defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column + 1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                for idx, res in enumerate(results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    theme = data.get('theme_word', 'Art')
                    bt = f"{brand_name} {data.get('title','')}"

                    # 循环生成子体
                    for _, s_row in size_price_data.iterrows():
                        if pd.isna(s_row['Size']): continue # 防止出现 None SKU
                        
                        # 1. 继承第4行所有固定值
                        for col_idx, def_val in template_defaults.items():
                            sheet.cell(row=curr_row, column=col_idx, value=def_val)
                            reset_cell(sheet.cell(row=curr_row, column=col_idx))
                        
                        # 2. 覆盖 AI 动态内容
                        def fill(name, val):
                            if name in header_map:
                                cell = sheet.cell(row=curr_row, column=header_map[name], value=str(val).strip())
                                reset_cell(cell)
                        
                        sz_str = str(s_row['Size']).replace('\"','').replace(' ','')
                        fill("seller sku", f"{prefix}-{sz_str}")
                        fill("parent sku", parent_sku_final)
                        fill("parentage", "child")
                        fill("product name", f"{bt} - {s_row['Size']}"[:150])
                        fill("sale price", s_row['Price'])
                        fill("size", s_row['Size'])
                        fill("size map", s_row['Size'])
                        fill("product description", data.get('desc',''))
                        fill("generic keyword", data.get('keywords',''))
                        fill("color", theme)
                        fill("color map", theme)
                        
                        # 3. 核心：自动生成又拍图片链接
                        fill("main_image_url", f"{yupoo_base}{prefix}/1.jpg")
                        fill("other_image_url1", f"{yupoo_base}{prefix}/2.jpg")
                        fill("other_image_url2", f"{yupoo_base}{prefix}/3.jpg")
                        fill("other_image_url3", f"{yupoo_base}{prefix}/4.jpg")

                        # 填充五点描述
                        bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "key product features" in str(c.value).lower()]
                        for i, c_idx in enumerate(bp_cols[:5]):
                            if i < len(data.get('bp', [])):
                                reset_cell(sheet.cell(row=curr_row, column=c_idx, value=data['bp'][i]))
                        curr_row += 1

                # 4. 最后单独处理父体（Row 4），确保不产生多余行
                for col_idx, def_val in template_defaults.items():
                    reset_cell(sheet.cell(row=4, column=col_idx, value=def_val))
                def fill_p(name, val):
                    if name in header_map: reset_cell(sheet.cell(row=4, column=header_map[name], value=str(val).strip()))
                fill_p("seller sku", parent_sku_final)
                fill_p("parentage", "parent")
                fill_p("product name", f"{brand_name} {results[0]['data'].get('title','')}")
                fill_p("color", "")
                fill_p("color map", "")
                fill_p("main_image_url", f"{yupoo_base}{results[0]['prefix']}/1.jpg")

                status.update(label="✅ 处理完毕！SKU 无多余，链接已生成。", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V7.2 终极版表格", output.getvalue(), f"Listing_Final_{parent_sku_final}.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
