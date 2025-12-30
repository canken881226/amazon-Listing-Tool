import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="亞馬遜批量上架工具 V2.2", layout="wide")

st.title("📦 亞馬遜批量上架工具 (AI 協作加固版)")
st.info("💡 操作指引：請參考 ChatGPT 為圖片生成的文案，將其中的『圖案元素詞』填入 Color 欄位。")

# --- 2. 促銷時間自動計算邏輯 ---
# 基於當前時間 (2025-12-29) 執行您要求的邏輯：
# 開始日期：2025-12-28 (昨天的固定格式)
# 結束日期：2026-12-27 (間隔一年的同一天)
today = datetime.now()
sale_start = (today - timedelta(days=1)).strftime('%Y-%m-%d')
sale_end = (today - timedelta(days=1) + timedelta(days=364)).strftime('%Y-%m-%d')

# --- 3. 欄位結構定義 ---
column_config = [
    "SKU (前綴-序號-Size)", 
    "Title (標題)", 
    "Description (描述)", 
    "Bullet Point 1", "Bullet Point 2", "Bullet Point 3", "Bullet Point 4", "Bullet Point 5",
    "Search Terms (關鍵詞)", 
    "Color (參考AI文案填寫圖案元素詞)", 
    "Size (自定義)", 
    "Sale Price (促銷價)", 
    "Sale Start Date", 
    "Sale End Date"
]

# --- 4. 數據初始化 ---
if 'listing_df' not in st.session_state:
    st.session_state.listing_df = pd.DataFrame([{
        "SKU (前綴-序號-Size)": "CHAO-BH-XMT-XFCT-001-S",
        "Title (標題)": "",
        "Description (描述)": "",
        "Bullet Point 1": "",
        "Bullet Point 2": "",
        "Bullet Point 3": "",
        "Bullet Point 4": "",
        "Bullet Point 5": "",
        "Search Terms (關鍵詞)": "",
        "Color (參考AI文案填寫圖案元素詞)": "", # 此處留空供用戶粘貼 AI 生成的元素詞
        "Size (自定義)": "Small",
        "Sale Price (促銷價)": 0.0,
        "Sale Start Date": sale_start,
        "Sale End Date": sale_end
    }])

# --- 5. 數據錄入表格 ---
st.subheader("1. 錄入/粘貼產品信息")
edited_df = st.data_editor(
    st.session_state.listing_df,
    num_rows="dynamic",
    use_container_width=True,
    key="listing_editor"
)

# --- 6. 生成與導出 ---
if st.button("🚀 生成 Amazon 上架 Excel"):
    if edited_df.empty:
        st.warning("表格內容為空")
    else:
        st.write("### ✅ 數據預覽")
        st.dataframe(edited_df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name='Template')
            
        st.download_button(
            label="💾 下載批量上架表格 (.xlsx)",
            data=output.getvalue(),
            file_name=f"Amazon_Batch_{today.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
