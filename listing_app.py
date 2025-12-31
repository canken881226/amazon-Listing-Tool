import streamlit as st
import pandas as pd
import io
import os
import openpyxl
from openpyxl.styles import Font, Alignment

st.set_page_config(page_title="亚马逊 AI 逻辑对位 V8.8", layout="wide")

# --- 1. 侧边栏：模板与品牌 ---
with st.sidebar:
    st.header("⚙️ 全局配置")
    brand_name = st.text_input("品牌名称", "YourBrand")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择 Amazon 上架模板", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("定义三个固定尺寸")
    s1 = st.text_input("尺寸 1 名称", "16x24\"")
    s2 = st.text_input("尺寸 2 名称", "24x36\"")
    s3 = st.text_input("尺寸 3 名称", "32x48\"")
    p1 = st.text_input("尺寸 1 价格", "12.99")
    p2 = st.text_input("尺寸 2 价格", "16.99")
    p3 = st.text_input("尺寸 3 价格", "19.99")

# --- 2. 核心布局：SKU 录入矩阵 ---
st.header("🖼️ SKU 图片链接精准对位矩阵")
st.info("💡 请按行填入每个 SKU 对应的信息。同一款式的尺寸图会精准对位到变体行，其他图将共用。")

# 动态增加行数
if 'sku_rows' not in st.session_state:
    st.session_state.sku_rows = 5 # 默认显示5行

for i in range(st.session_state.sku_rows):
    with st.container():
        c1, c2, c3, c4, c5, c6 = st.columns([1.5, 2, 2, 1.5, 1.5, 1.5])
        with c1:
            st.text_input(f"SKU 名称 {i+1}", key=f"sku_{i}", placeholder="如: SQDQ-001")
        with c2:
            st.text_input(f"主图链接 {i+1}", key=f"main_{i}", placeholder="pic.yupoo.com/...")
        with c3:
            st.text_area(f"其他图链接集 (每行一个) {i+1}", key=f"others_{i}", height=68)
        with c4:
            st.text_input(f"{s1} 图片链接", key=f"s1_link_{i}")
        with c5:
            st.text_input(f"{s2} 图片链接", key=f"s2_link_{i}")
        with c6:
            st.text_input(f"{s3} 图片链接", key=f"s3_link_{i}")
        st.divider()

if st.button("➕ 增加更多 SKU 行"):
    st.session_state.sku_rows += 5
    st.rerun()

# --- 3. 关键词框 ---
st.subheader("📝 Search Terms 关键词方案")
user_all_kw = st.text_area("输入关键词词库", height=100)

# --- 4. 执行生成 ---
if st.button("🚀 生成精准对位表格", use_container_width=True):
    if not selected_tpl:
        st.error("❌ 请先在侧边栏选择模板")
    else:
        try:
            with st.status("🚄 正在按照 SKU 矩阵逻辑处理变体...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 扫描表头和默认值 (第4行)
                h = {str(c.value).lower().strip(): c.column for c in sheet[3] if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                for i in range(st.session_state.sku_rows):
                    sku_base = st.session_state[f"sku_{i}"]
                    if not sku_base: continue # 跳过空行
                    
                    # 获取该 SKU 的所有链接
                    main_url = st.session_state[f"main_{i}"]
                    other_urls = st.session_state[f"others_{i}"].split('\n')
                    size_urls = [st.session_state[f"s1_link_{i}"], st.session_state[f"s2_link_{i}"], st.session_state[f"s3_link_{i}"]]
                    sizes = [(s1, p1), (s2, p2), (s3, p3)]

                    # 生成 3 个尺寸的变体行
                    for idx, (sz_name, sz_price) in enumerate(sizes):
                        # 继承第4行默认属性
                        for col, val in defaults.items():
                            cell = sheet.cell(row=curr_row, column=col, value=val)
                            cell.font = Font(name='Arial', size=10)
                        
                        def fill(name, val):
                            if name in h:
                                cell = sheet.cell(row=curr_row, column=h[name], value=str(val))
                                cell.font = Font(name='Arial', size=10)
                        
                        # 填充精准对位数据
                        sz_tag = sz_name.replace('"', '').replace(' ', '')
                        fill("seller sku", f"{sku_base}-{sz_tag}")
                        fill("parent sku", f"{sku_base}-P")
                        fill("main_image_url", main_url)
                        fill("sale price", sz_price)
                        fill("size", sz_name)
                        
                        # 填充其他图 (最多填充到 other_image_url8)
                        for j, o_url in enumerate(other_urls):
                            if o_url.strip():
                                fill(f"other_image_url{j+1}", o_url.strip())
                        
                        # 【核心】填充当前尺寸特有的图片链接 (放在最后一个空位，例如 url7)
                        if size_urls[idx]:
                            fill("other_image_url7", size_urls[idx])
                            
                        curr_row += 1
                
                status.update(label="✅ 表格生成完成！图片链接已精准绑定。", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V8.8 终极对位版", output.getvalue(), f"Final_Listing_{sku_base}.xlsm")
        except Exception as e:
            st.error(f"❌ 错误: {e}")
