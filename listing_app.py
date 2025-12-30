import streamlit as st
import pandas as pd
import io

# --- 1. 页面基础配置 ---
st.set_page_config(page_title="亚马逊上架表格生成器", layout="wide")

st.title("📦 亚马逊批量上架工具 (11个核心字段版)")
st.info("💡 提示：SKU 建议格式为 '品牌-款式-颜色-尺寸'；Color 请使用标准颜色名称。")

# --- 2. 字段定义 (完全对应您的要求) ---
# SKU、标题、描述、五点特征(1-5)、关键词、color、size自定义、促销价、促销开始时间、促销结束时间
column_config = [
    "SKU (品牌-款式-颜色-尺寸)", 
    "Title (标题)", 
    "Description (描述)", 
    "Bullet Point 1", "Bullet Point 2", "Bullet Point 3", "Bullet Point 4", "Bullet Point 5",
    "Search Terms (关键词)", 
    "Color (首字母大写)", 
    "Size (自定义)", 
    "Sale Price (促销价)", 
    "Sale Start Date (YYYY-MM-DD)", 
    "Sale End Date (YYYY-MM-DD)"
]

# --- 3. 初始数据填充 ---
if 'listing_df' not in st.session_state:
    st.session_state.listing_df = pd.DataFrame([{
        "SKU (品牌-款式-颜色-尺寸)": "TPC-TS01-BLK-S",
        "Title (标题)": "Example Product Title",
        "Description (描述)": "High quality material...",
        "Bullet Point 1": "Feature 1",
        "Bullet Point 2": "Feature 2",
        "Bullet Point 3": "Feature 3",
        "Bullet Point 4": "Feature 4",
        "Bullet Point 5": "Feature 5",
        "Search Terms (关键词)": "keyword1, keyword2",
        "Color (首字母大写)": "Black",
        "Size (自定义)": "Small",
        "Sale Price (促销价)": 15.99,
        "Sale Start Date (YYYY-MM-DD)": "2026-01-01",
        "Sale End Date (YYYY-MM-DD)": "2026-12-31"
    }])

# --- 4. 数据录入区 ---
st.subheader("1. 录入/粘贴产品信息")
edited_df = st.data_editor(
    st.session_state.listing_df,
    num_rows="dynamic",
    use_container_width=True,
    key="listing_editor"
)

# --- 5. 生成与下载 ---
if st.button("🚀 生成 Amazon 上架 Excel"):
    if edited_df.empty:
        st.warning("表格内容为空")
    else:
        st.write("### ✅ 预览数据")
        st.dataframe(edited_df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name='Template')
            
        st.download_button(
            label="💾 下载上架表格 (.xlsx)",
            data=output.getvalue(),
            file_name="Amazon_Listing_Batch.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
