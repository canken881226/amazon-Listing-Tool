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

# --- 1. 配置与 AI 指令 ---
st.set_page_config(page_title="亚马逊 AI 专家 V8.6", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

SYSTEM_LOGIC = """
You are a Professional Amazon SEO Copywriter. 
[TITLE] 180+ chars. Rich visual details + Style + Scene.
[BULLETS] 5 points, each 40+ words with [CAPITALIZED HEADER].
[COLOR] Use descriptive theme word for Color & Color Map.
"""

# --- 2. 核心磁吸对位工具 ---
def get_best_match(sku, pool, tag=None):
    """
    以 SKU 为出发点寻找链接。
    如果提供了 tag (如尺寸)，则必须同时包含 SKU 和 tag。
    """
    for url in pool:
        u_low = url.lower()
        s_low = sku.lower()
        if s_low in u_low:
            if tag:
                if tag.lower() in u_low: return url
            else:
                # 寻找不含特定尺寸标识的主图
                return url
    return ""

def reset_cell(cell, value=None):
    if value is not None: cell.value = value
    cell.font = Font(name='Arial', size=10)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

# --- 3. 界面布局 ---
st.title("🤖 亚马逊 AI 核心对位填充 V8.6")

with st.sidebar:
    st.header("⚙️ 全局配置")
    brand_name = st.text_input("品牌名称", "YourBrand")

c1, c2 = st.columns([1, 1])
with c1:
    st.subheader("1. 尺寸变体配置")
    size_df = pd.DataFrame([{"尺寸": '16x24"', "价格": "12.99"},{"尺寸": '24x36"', "价格": "19.99"}])
    size_config = st.data_editor(size_df, num_rows="dynamic")
    
    st.subheader("2. 粘贴又拍乱序外链池")
    raw_links = st.text_area("复制又拍生成的全部链接粘贴于此", height=200)

with c2:
    st.subheader("3. SKU 导向图片上传")
    main_imgs = st.file_uploader("📤 上传主图 (文件名即为 SKU)", accept_multiple_files=True)
    effect_imgs = st.file_uploader("📤 上传共有效果图", accept_multiple_files=True)
    size_imgs = st.file_uploader("📤 上传特定尺寸图 (文件名含尺寸关键字)", accept_multiple_files=True)

st.subheader("4. Search Terms 关键词方案")
user_all_kw = st.text_area("输入关键词库", height=100)

# --- 4. 生成逻辑 ---
if st.button("🚀 执行 SKU 精准对位填充", use_container_width=True):
    link_pool = [l.strip() for l in raw_links.split('\n') if l.strip()]
    if not main_imgs or not link_pool:
        st.error("❌ 缺少 SKU 主图或外链池")
    else:
        try:
            with st.status("🚄 正在以 SKU 为核心进行磁吸匹配与文案生成...") as status:
                # 扫描模板
                tpl_files = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl_files[0]), keep_vba=True)
                sheet = wb.active
                h = {str(c.value).lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                for img_file in main_imgs:
                    sku_base = os.path.splitext(img_file.name)[0]
                    # AI 分析逻辑... (略)
                    ai_data = {"title": "3D Window Art...", "bp": ["..."]*5, "theme": "ZenForest"}
                    
                    # 匹配该 SKU 的共有图片
                    main_url = get_best_match(sku_base, link_pool)
                    effect_url = get_best_match(sku_base, link_pool, "effect") or get_best_match(sku_base, link_pool)

                    for _, s_row in size_config.iterrows():
                        sz = str(s_row['尺寸'])
                        sz_tag = sz.replace('"', '').replace(' ', '')
                        
                        # 精准匹配尺寸图
                        size_url = get_best_match(sku_base, link_pool, sz_tag)

                        # 填充与继承
                        for col, val in defaults.items(): reset_cell(sheet.cell(row=curr_row, column=col), val)
                        
                        def fill(name, val):
                            if name in h: reset_cell(sheet.cell(row=curr_row, column=h[name]), str(val))
                        
                        fill("seller sku", f"{sku_base}-{sz_tag}")
                        fill("product name", f"{brand_name} {ai_data['title']} - {sz}")
                        fill("main_image_url", main_url)
                        fill("other_image_url1", effect_url) # 共有图
                        fill("other_image_url2", size_url)   # 尺寸图
                        curr_row += 1
                
                status.update(label="✅ SKU 对位填充完成！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V8.6 核心对位版表格", output.getvalue(), f"Listing_Aligned_V8.6.xlsm")
        except Exception as e:
            st.error(f"❌ 错误: {e}")
