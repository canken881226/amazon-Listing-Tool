import streamlit as st
import pandas as pd
import io
import os
import openpyxl
from openpyxl.styles import Font, Alignment
from PIL import Image

# --- 1. 初始化设置 ---
st.set_page_config(page_title="亚马逊 AI 专家 V8.7", layout="wide")

# --- 2. 侧边栏：配置中心与模板选择 ---
with st.sidebar:
    st.header("⚙️ 配置中心")
    brand_name = st.text_input("品牌名称", "YourBrand")
    
    # 找回模板选择框
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择 Amazon 上架模板", tpl_list) if tpl_list else None

# --- 3. 尺寸变体配置 ---
st.subheader("1. 尺寸变体配置")
size_df = pd.DataFrame([{"尺寸": '16x24"', "价格": "12.99"},{"尺寸": '24x36"', "价格": "19.99"}])
size_config = st.data_editor(size_df, num_rows="dynamic")

# --- 4. 核心：手绘图对位布局实现 ---
st.subheader("2. 图片与链接精准匹配（SKU 导向）")
uploaded_files = st.file_uploader("📤 批量上传款式主图", accept_multiple_files=True)

# 存储 SKU 对应的链接映射
sku_link_map = {}

if uploaded_files:
    st.info("💡 请在下方针对每个款式，填入对应的又拍直链。")
    for file in uploaded_files:
        sku = os.path.splitext(file.name)[0]
        col_img, col_sku, col_link = st.columns([1, 1, 3])
        
        with col_img:
            st.image(file, width=80)
        with col_sku:
            st.markdown(f"**SKU:** `{sku}`")
        with col_link:
            sku_link_map[sku] = st.text_input(f"粘贴 {sku} 的主图链接", key=f"link_{sku}")

# --- 5. 关键词方案 ---
st.subheader("3. Search Terms 关键词方案")
user_kw = st.text_area("在此输入 Ⅰ-Ⅴ 类关键词方案", height=100)

# --- 6. 生成逻辑 ---
if st.button("🚀 生成精准匹配表格", use_container_width=True):
    if not selected_tpl or not uploaded_files:
        st.error("❌ 请确保已上传图片并选择模板。")
    else:
        try:
            with st.status("🚄 正在按照手绘对位逻辑写入 Excel...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 扫描表头与第4行固定值
                h = {str(c.value).lower(): c.column for c in sheet[3] if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                for file in uploaded_files:
                    sku_base = os.path.splitext(file.name)[0]
                    main_url = sku_link_map.get(sku_base, "")
                    
                    for _, s_row in size_config.iterrows():
                        # 继承模板第4行所有属性
                        for col, val in defaults.items():
                            cell = sheet.cell(row=curr_row, column=col, value=val)
                            cell.font = Font(name='Arial', size=10)
                        
                        def fill(name, val):
                            if name in h:
                                cell = sheet.cell(row=curr_row, column=h[name], value=str(val))
                                cell.font = Font(name='Arial', size=10)
                        
                        # 写入动态内容
                        sz_tag = str(s_row['尺寸']).replace('"', '').replace(' ', '')
                        fill("seller sku", f"{sku_base}-{sz_tag}")
                        fill("parent sku", f"{sku_base}-P")
                        fill("main_image_url", main_url) # 款式共用图片
                        fill("sale price", s_row['价格'])
                        fill("size", s_row['尺寸'])
                        # ... 其余 AI 文案填充逻辑
                        curr_row += 1
                
                status.update(label="✅ 表格生成成功！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V8.7 精准版", output.getvalue(), f"Listing_{selected_tpl}")
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
