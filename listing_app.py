import streamlit as st
import pandas as pd
import io
import os
import openpyxl
from openpyxl.styles import Font, Alignment
from PIL import Image

# --- 1. 核心匹配逻辑 ---
def find_image_link(sku_base, size_tag, link_pool, img_type="main"):
    """
    sku_base: SKU 基础名 (如 SQDQ-001)
    size_tag: 尺寸标签 (如 16x24)
    link_pool: 所有粘贴进来的直链列表
    img_type: main(主图), effect(效果图), size(尺寸图)
    """
    for link in link_pool:
        l_low = link.lower()
        s_low = sku_base.lower()
        # 匹配逻辑：链接必须包含 SKU 基础名
        if s_low in l_low:
            if img_type == "size" and size_tag.lower() in l_low:
                return link # 找到对应尺寸的图
            if img_type == "main" and "main" in l_low:
                return link # 找到带 main 标记的主图
            if img_type == "effect" and "effect" in l_low:
                return link
    return ""

# --- 2. 界面布局 ---
st.title("🤖 亚马逊 AI 逻辑矩阵版 V8.3")

with st.sidebar:
    st.header("⚙️ 配置中心")
    brand_name = st.text_input("品牌名称", "YourBrand")
    # 支持自定义链接前缀，方便使用 GitHub 或又拍
    img_root = st.text_input("链接前缀 (可选)", "https://v.yupoo.com/xxx/")

# 第一步：定义变体
st.subheader("第一步：定义尺寸变体")
default_df = pd.DataFrame([{"尺寸名称": '16x24"', "价格": "12.99"},{"尺寸名称": '24x36"', "价格": "19.99"}])
size_config = st.data_editor(default_df, num_rows="dynamic")

# 第二步：上传图片（分区域）
st.subheader("第二步：分类图片上传")
c1, c2, c3 = st.columns(3)
with c1:
    main_imgs = st.file_uploader("📤 上传主图 (文件名需含SKU)", accept_multiple_files=True)
with c2:
    effect_imgs = st.file_uploader("📤 上传效果图 (可选)", accept_multiple_files=True)
with c3:
    size_imgs = st.file_uploader("📤 上传尺寸图 (文件名含SKU+尺寸)", accept_multiple_files=True)

# 第三步：输入链接池（从又拍批量外链复制）
st.subheader("第三步：输入外链池")
raw_links = st.text_area("直接粘贴又拍生成的全部乱序外链", height=150)

# --- 3. 执行生成 ---
if st.button("🚀 生成精准匹配表格", use_container_width=True):
    link_pool = [l.strip() for l in raw_links.split('\n') if l.strip()]
    
    if not main_imgs or not link_pool:
        st.error("❌ 请确保已上传主图并粘贴了对应的链接池")
    else:
        # 加载模板
        tpl_path = "templates/template.xlsm" # 假设模板在此
        wb = openpyxl.load_workbook(tpl_path, keep_vba=True)
        sheet = wb.active
        
        # 获取列索引
        h = {str(cell.value).lower(): cell.column for cell in sheet[3] if cell.value}
        
        curr_row = 5
        # 遍历每一款产品（以主图为准）
        for img in main_imgs:
            sku_base = os.path.splitext(img.name)[0]
            
            # 为每一款产品生成变体行
            for _, s_info in size_config.iterrows():
                size_name = s_info['尺寸名称']
                clean_size = size_name.replace('"', '').replace(' ', '')
                
                # 寻找匹配的链接
                main_url = find_image_link(sku_base, "", link_pool, "main")
                size_url = find_image_link(sku_base, clean_size, link_pool, "size")
                
                # 写入 Excel
                def fill(col_name, val):
                    if col_name in h:
                        cell = sheet.cell(row=curr_row, column=h[col_name])
                        cell.value = val
                        cell.font = Font(name='Arial', size=10)

                fill("seller sku", f"{sku_base}-{clean_size}")
                fill("product name", f"{brand_name} {sku_base} Wall Art - {size_name}")
                fill("main_image_url", main_url)
                fill("other_image_url1", size_url) # 尺寸图放在次图1
                fill("sale price", s_info['价格'])
                
                curr_row += 1
        
        # 导出
        output = io.BytesIO()
        wb.save(output)
        st.download_button("💾 下载精准对位表格", output.getvalue(), "Listing_Final_V8.3.xlsm")
