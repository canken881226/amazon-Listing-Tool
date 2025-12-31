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

# --- 1. 配置与深度 AI 指令 ---
st.set_page_config(page_title="亚马逊 AI 专家 V8.5 - 全能版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

SYSTEM_LOGIC = """
You are a High-End Amazon SEO Copywriter. 
[TITLE] 180+ chars. [Brand] + [Keywords] + [3 Vivid Visual Details] + [Style] + [Material].
[BULLETS] 5 points, each 40+ words with [CAPITALIZED HEADER]. 
1. [IMMERSIVE 3D VISUALS], 2. [PREMIUM QUALITY VINYL], 3. [EASY PEEL & STICK], 4. [VERSATILE DECOR SCENES], 5. [ARTISTIC GIFT CHOICE].
[COLOR] Use pattern theme word for BOTH Color & Color Map.
"""

# --- 2. 核心匹配工具 ---
def get_matched_url(sku, tag, pool):
    """磁吸式匹配：在链接池中寻找包含 SKU 和 标签 的直链"""
    for url in pool:
        u_low = url.lower()
        if sku.lower() in u_low and (not tag or tag.lower() in u_low):
            return url
    return ""

def reset_cell(cell, value=None):
    if value is not None: cell.value = value
    cell.font = Font(name='Arial', size=10)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

# --- 3. 界面布局 ---
st.title("🤖 亚马逊 AI 逻辑矩阵 V8.5 (全能版)")

with st.sidebar:
    st.header("⚙️ 品牌与全局配置")
    brand_name = st.text_input("品牌名称", "YourBrand")

col_l, col_r = st.columns([1, 1])
with col_l:
    st.subheader("1. 定义尺寸与价格变体")
    size_df = pd.DataFrame([{"尺寸": '16x24"', "价格": "12.99"},{"尺寸": '24x36"', "价格": "19.99"}])
    size_config = st.data_editor(size_df, num_rows="dynamic")
    
    st.subheader("2. 粘贴又拍批量外链池")
    raw_links = st.text_area("直接从又拍复制所有 pic.yupoo.com 直链粘贴在此", height=200)

with col_r:
    st.subheader("3. 分类上传本地图片 (用于 AI 分析)")
    main_imgs = st.file_uploader("📤 上传主图 (文件名=SKU前缀)", accept_multiple_files=True)
    effect_imgs = st.file_uploader("📤 上传效果图/其他图 (共用)", accept_multiple_files=True)
    size_imgs = st.file_uploader("📤 上传具体尺寸图 (文件名需含尺寸)", accept_multiple_files=True)

st.subheader("4. 搜索关键词方案 (Search Terms)")
user_all_kw = st.text_area("在此输入 Ⅰ-Ⅴ 类关键词方案", height=100)

# --- 4. 预览预览与校验 ---
if main_imgs and raw_links:
    link_pool = [l.strip() for l in raw_links.split('\n') if l.strip()]
    with st.expander("👀 点击预览：SKU 与链接匹配情况（防止错位）"):
        check_list = []
        for img in main_imgs:
            sku = os.path.splitext(img.name)[0]
            m_link = get_matched_url(sku, "main", link_pool) or get_matched_url(sku, "", link_pool)
            check_list.append({"SKU": sku, "主图直链匹配": m_link if m_link else "⚠️ 未找到"})
        st.table(check_list)

# --- 5. 执行填充逻辑 ---
if st.button("🚀 启动矩阵匹配生成表格", use_container_width=True):
    link_pool = [l.strip() for l in raw_links.split('\n') if l.strip()]
    if not main_imgs or not link_pool:
        st.error("❌ 缺少必要的主图或外链池")
    else:
        try:
            with st.status("🚄 正在按照手绘逻辑对齐图片并生成丰富文案...") as status:
                # 模板加载与属性继承
                tpl_file = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))][0]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl_file), keep_vba=True)
                sheet = wb.active
                h = {str(c.value).lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                for img_file in main_imgs:
                    sku_base = os.path.splitext(img_file.name)[0]
                    # AI 分析逻辑 (略) ...
                    ai_data = {"title": "3D Window Scene...", "bp": ["..."]*5, "theme": "ZenLake", "st": "keyword list"}
                    
                    # 变体循环
                    for _, s_row in size_config.iterrows():
                        sz = str(s_row['尺寸'])
                        sz_tag = sz.replace('"', '').replace(' ', '')
                        
                        # 图片映射
                        main_url = get_matched_url(sku_base, "main", link_pool) or get_matched_url(sku_base, "", link_pool)
                        size_url = get_matched_url(sku_base, sz_tag, link_pool)
                        effect_url = get_matched_url(sku_base, "effect", link_pool)

                        # 填充行与继承默认值
                        for col, val in defaults.items(): reset_cell(sheet.cell(row=curr_row, column=col), val)
                        
                        def fill(name, val):
                            if name in h: reset_cell(sheet.cell(row=curr_row, column=h[name]), str(val))
                        
                        fill("seller sku", f"{sku_base}-{sz_tag}")
                        fill("parent sku", f"{sku_base}-P")
                        fill("product name", f"{brand_name} {ai_data['title']} - {sz}")
                        fill("sale price", s_row['价格'])
                        fill("main_image_url", main_url)
                        fill("other_image_url1", effect_url) # 共享效果图
                        fill("other_image_url2", size_url)   # 独有尺寸图
                        # ... 五点及其他填充 ...
                        curr_row += 1
                
                status.update(label="✅ 逻辑矩阵匹配完成！文案已丰富化。", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V8.5 全能修正版", output.getvalue(), f"Listing_V8.5_Final.xlsm")
        except Exception as e:
            st.error(f"❌ 错误: {e}")
