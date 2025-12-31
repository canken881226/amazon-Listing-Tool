import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import openpyxl
from openpyxl.styles import Font, Alignment
from openai import OpenAI
from PIL import Image

# --- 1. 初始化配置 ---
st.set_page_config(page_title="亚马逊 AI 对位专家 V9.0", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# 底层固化模板：品牌 + SKU特色 + 视觉描述 + SEO关键词
SYSTEM_PROMPT_FIXED = """
You are a Professional Amazon SEO Expert. 
Title Structure: [Brand] + SKU Core + Vivid Visual Description (describe lighting/textures/style) + 3 USPs + Style. (180+ chars)
Bullet Points: 5 points with Capitalized Headers (40+ words each). Focus on: 1. Immersive 3D View, 2. Material Quality, 3. Installation, 4. Scenes, 5. Gift Value.
Keywords: Use provided Search Terms naturally.
"""

with st.sidebar:
    st.header("⚙️ 模板与品牌设置")
    brand_name = st.text_input("品牌名称", "YourBrand")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择 Amazon 上架表格", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("定义变体尺寸")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("价格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("价格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("价格 3", "19.99")

# --- 2. 核心布局：SKU 物理对位矩阵 ---
st.header("🖼️ SKU 精准对位与视觉分析矩阵")

if 'total_skus' not in st.session_state: st.session_state.total_skus = 5

sku_inputs = []
for i in range(st.session_state.total_skus):
    with st.expander(f"款式 {i+1} 信息录入区", expanded=True):
        c1, c2, c3 = st.columns([1, 2, 2])
        with c1:
            sku_name = st.text_input(f"SKU 名称 {i+1}", key=f"sku_{i}")
            local_img = st.file_uploader(f"上传分析图 {i+1}", key=f"file_{i}")
        with c2:
            main_url = st.text_input(f"主图直连链接 {i+1}", key=f"main_{i}")
            others = st.text_area(f"附图链接(每行一个) {i+1}", key=f"others_{i}", height=100)
        with c3:
            s1_u = st.text_input(f"{s1} 特有图 {i+1}", key=f"s1u_{i}")
            s2_u = st.text_input(f"{s2} 特有图 {i+1}", key=f"s2u_{i}")
            s3_u = st.text_input(f"{s3} 特有图 {i+1}", key=f"s3u_{i}")
        sku_inputs.append({"sku": sku_name, "img": local_img, "main": main_url, "others": others, "size_links": [s1_u, s2_u, s3_u]})

if st.button("➕ 增加更多款式行"):
    st.session_state.total_skus += 5
    st.rerun()

st.subheader("📝 Search Terms 关键词方案")
user_keywords = st.text_area("在此填入词库方案，AI将以此为参考编写文案", height=100)

# --- 3. 执行逻辑 ---
def encode_img(file):
    img = Image.open(file)
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

if st.button("🚀 生成精准文案并对位表格", use_container_width=True):
    if not selected_tpl: st.error("❌ 请先选择表格模板")
    else:
        try:
            with st.status("🚄 AI 正在识别主图图案并生成 SEO 描述...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                h = {str(c.value).lower().strip(): c.column for c in sheet[3] if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                client = OpenAI(api_key=api_key)

                for entry in sku_inputs:
                    if not entry["sku"] or not entry["img"]: continue
                    
                    # AI 视觉分析 + 文案生成
                    b64 = encode_img(entry["img"])
                    prompt = f"{SYSTEM_PROMPT_FIXED}\nSKU:{entry['sku']}\nSearchTerms:{user_keywords}\nJSON Response:{{'title':'','bp':['','','','',''],'keywords':''}}"
                    response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}], response_format={"type":"json_object"})
                    res_data = json.loads(response.choices[0].message.content)

                    # 变体填充逻辑
                    for idx, (sz_name, sz_price) in enumerate([(s1, p1), (s2, p2), (s3, p3)]):
                        for col, val in defaults.items():
                            cell = sheet.cell(row=curr_row, column=col, value=val)
                            cell.font = Font(name='Arial', size=10)
                        
                        def fill(name, val):
                            if name in h:
                                cell = sheet.cell(row=curr_row, column=h[name], value=str(val))
                                cell.font = Font(name='Arial', size=10)
                        
                        fill("seller sku", f"{entry['sku']}-{sz_name.replace('\"','')}")
                        fill("parent sku", f"{entry['sku']}-P")
                        fill("product name", f"{brand_name} {res_data.get('title','')} - {sz_name}")
                        fill("main_image_url", entry["main"])
                        fill("other_image_url1", entry["size_links"][idx]) # 精准对位尺寸图
                        fill("generic keyword", res_data.get('keywords',''))
                        # 写入五点描述
                        bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "key product features" in str(c.value).lower()]
                        for j, c_idx in enumerate(bp_cols[:5]):
                            if j < len(res_data.get('bp', [])):
                                sheet.cell(row=curr_row, column=c_idx, value=res_data['bp'][j])
                        
                        curr_row += 1
                
                status.update(label="✅ 文案已根据图案与SKU对位完成！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V9.0 精准对位版", output.getvalue(), f"Listing_Final_{entry['sku']}.xlsm")
        except Exception as e:
            st.error(f"❌ 系统错误: {e}")
