import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import openpyxl
import re
from openpyxl.styles import Font
from openai import OpenAI
from PIL import Image
from datetime import datetime, timedelta

# --- 1. 自动计算促销时间逻辑 ---
today = datetime.now()
auto_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
auto_end_date = ((today - timedelta(days=1)) + timedelta(days=365) - timedelta(days=1)).strftime("%Y-%m-%d")

st.set_page_config(page_title="亚马逊 AI 专家 V9.4 - 规格强化版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 辅助函数：清洗乱码 ---
def clean_text(text):
    if not text: return ""
    # 移除不可见字符，保留标准 ASCII/UTF-8
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

# --- 2. 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 基础配置")
    brand_name = st.text_input("品牌名称", "YourBrand")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("变体尺寸与售价")
    # 尺寸编号示例：001, 002... 方便生成 Parent SKU 范围
    s1, p1, n1 = st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99"), "001"
    s2, p2, n2 = st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99"), "002"
    s3, p3, n3 = st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99"), "003"

# --- 3. SKU 对位矩阵 ---
st.header("🖼️ SKU 精准对位矩阵")
if 'sku_rows' not in st.session_state: st.session_state.sku_rows = 3

sku_data = []
for i in range(st.session_state.sku_rows):
    with st.expander(f"款式 {i+1} 录入区", expanded=True):
        c1, c2, c3 = st.columns([1.5, 2, 2.5])
        with c1:
            sku_name = st.text_input(f"SKU 名称 (例: ART)", key=f"s_{i}")
            local_img = st.file_uploader(f"上传分析图", key=f"f_{i}")
        with c2:
            main_url = st.text_input(f"主图链接", key=f"m_{i}")
            others = st.text_area(f"附图链接集", key=f"o_{i}", height=80)
        with c3:
            s1_u = st.text_input(f"{s1} 图片", key=f"s1u_{i}")
            s2_u = st.text_input(f"{s2} 图片", key=f"s2u_{i}")
            s3_u = st.text_input(f"{s3} 图片", key=f"s3u_{i}")
        sku_data.append({"sku": sku_name, "img": local_img, "main": main_url, "others": others, "sz_urls": [s1_u, s2_u, s3_u]})

if st.button("➕ 增加款式"):
    st.session_state.sku_rows += 1
    st.rerun()

user_kw_pool = st.text_area("📝 通用关键词 (General Keywords)", height=80)

# --- 4. 执行生成 ---
if st.button("🚀 启动全自动化精准生成", use_container_width=True):
    if not selected_tpl: st.error("请选择模板")
    else:
        try:
            with st.status("正在处理...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                
                h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value is not None}

                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_data:
                    if not item["sku"] or not item["img"]: continue
                    
                    # AI 视觉生成文案
                    img_file = item["img"]
                    img_b64 = base64.b64encode(img_file.read()).decode('utf-8')
                    # 提示词强化：要求必须返回图案元素词
                    prompt = f"Analyze this pattern. Return JSON: {{'title':'...','bp':['...','...','...','...','...'],'pattern_elements':'word1 word2','color':'color_name'}}"
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}], response_format={"type":"json_object"})
                    ai = json.loads(res.choices[0].message.content)

                    # --- 核心规格优化 ---
                    
                    # 1. Parent SKU 逻辑：编号范围 (例如 001-003)
                    p_sku_name = f"{item['sku']}-{n1}-{n3}" 

                    # 3个变体循环
                    for idx, (sz_name, sz_price, sz_num) in enumerate([(s1, p1, n1), (s2, p2, n2), (s3, p3, n3)]):
                        for col, val in defaults.items():
                            sheet.cell(row=curr_row, column=col, value=val)
                        
                        def fill_col(k, v):
                            target = [c for c in h if k.lower() in c]
                            if target: 
                                cleaned_v = clean_text(v)
                                sheet.cell(row=curr_row, column=h[target[0]], value=cleaned_v)

                        # 填充 Seller SKU
                        fill_col("seller sku", f"{item['sku']}-{sz_num}")
                        
                        # 填充 Parent SKU
                        fill_col("parent sku", p_sku_name)
                        
                        # 填充 Color & Color Map (规则：一致且包含元素词)
                        final_color = f"{ai['color']} {ai['pattern_elements']}"
                        fill_col("color", final_color)
                        fill_col("color map", final_color)

                        # 填充 Search Terms (规则：元素词 + 通用词，空格分隔)
                        # 使用正则过滤掉非空格的符号，确保只有单词间空格
                        raw_kw = f"{ai['pattern_elements']} {user_kw_pool}"
                        clean_kw = " ".join(re.sub(r'[,;._/]+', ' ', raw_kw).split())
                        fill_col("generic keyword", clean_kw)
                        
                        # 填充五点描述 (规则：修复乱码，确保5个)
                        bp_list = ai.get('bp', [])
                        # 如果AI返回不足5个，用默认值补齐
                        while len(bp_list) < 5: bp_list.append("High-quality professional print with vivid details.")
                        
                        bp_cols = [c for c in h if "key product features" in c]
                        for j in range(5):
                            if j < len(bp_cols):
                                fill_col(bp_cols[j], bp_list[j])

                        # 其他基础字段
                        fill_col("product name", f"{brand_name} {ai['title']} {ai['pattern_elements']} - {sz_name}")
                        fill_col("sale price", sz_price)
                        fill_col("sale start date", auto_start_date)
                        fill_col("sale end date", auto_end_date)
                        fill_col("main_image_url", item["main"])
                        if item["sz_urls"][idx]: fill_col("other_image_url1", item["sz_urls"][idx])
                        
                        curr_row += 1
                
                status.update(label="✅ 生成成功！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载优化版模板", output.getvalue(), f"Listing_Optimized.xlsm")
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
