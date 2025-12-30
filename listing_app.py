import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta

# --- 1. 页面基础配置 ---
st.set_page_config(page_title="亚马逊批量上架工具", layout="wide")

st.title("📦 亚马逊批量上架工具 (V2.0 自动日期版)")
st.info("💡 提示：系统已为您自动设置促销时间：开始时间为昨天，结束时间为一年后。")

# --- 2. 自动生成时间逻辑 ---
today = datetime.now()
yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
one_year_later = (today - timedelta(days=1) + timedelta(days=364)).strftime('%Y-%m-%d')

# --- 3. 字段定义 ---
column_config = [
    "SKU (品牌-款式-颜色-尺寸)", "Title (标题)", "Description (描述)", 
    "Bullet Point 1", "Bullet Point 2", "Bullet Point 3", "Bullet Point 4", "Bullet Point 5",
    "Search Terms (关键词)", "Color (首字母大写)", "Size (自定义)", 
    "Sale Price (促销价)", "Sale Start Date", "Sale End Date"
]

# --- 4. 初始数据填充 ---
if 'listing_df' not in st.session_state:
    st.session_state.listing_df = pd.DataFrame([{
        "SKU (品牌-款式-颜色-尺寸)": "TPC-TS01-BLK-S",
        "Title (标题)": "",
        "Description (描述)": "",
        "Bullet Point 1": "",
        "Bullet Point 2": "",
        "Bullet Point 3": "",
        "Bullet Point 4": "",
        "Bullet Point 5": "",
        "Search Terms (关键词)": "",
        "Color (首字母大写)": "Black",
        "Size (自定义)": "Small",
        "Sale Price (促销价)": 0.0,
        "Sale Start Date": yesterday,       # 自动生成昨天的日期
        "Sale End Date": one_year_later     # 自动生成一年后的日期
    }])

# --- 5. 数据录入区 ---
st.subheader("1. 录入/粘贴产品信息 (支持从 Excel 批量复制粘贴)")
edited_df = st.data_editor(
    st.session_state.listing_df,
    num_rows="dynamic",
    use_container_width=True,
    key="listing_editor"
)

# --- 6. 生成与下载 ---
if st.button("🚀 生成 Amazon 上架 Excel"):
    if edited_df.empty:
        st.warning("表格内容为空")
    else:
        st.write("### ✅ 预览生成的表格数据")
        st.dataframe(edited_df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name='Template')
            
        st.download_button(
            label="💾 下载批量上架表格 (.xlsx)",
            data=output.getvalue(),
            file_name=f"Amazon_Batch_{today.strftime('%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
