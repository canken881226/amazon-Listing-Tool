import streamlit as st
import pandas as pd
import io
import os
import base64
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 核心初始化與安全密鑰讀取 ---
st.set_page_config(page_title="亞馬遜 AI 智能上架系統 V3.2", layout="wide")

# 優先從 Streamlit Secrets 讀取 Key，如果沒有則從側邊欄讀取
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = st.sidebar.text_input("輸入 OpenAI API Key (Secrets 未配置時)", type="password")

# --- 2. 側邊欄配置 ---
with st.sidebar:
    st.header("⚙️ 參數設置")
    selected_category = st.selectbox("產品類目", ["服飾 (Apparel)", "家居 (Home)", "飾品 (Jewelry)"])
    
    st.divider()
    st.header("📂 模板管理")
    template_path = "templates/"
    available_templates = [f for f in os.listdir(template_path) if f.endswith('.xlsx')] if os.path.exists(template_path) else []
    selected_tpl = st.selectbox("選擇官方模板", available_templates if available_templates else ["請上傳模板到GitHub/templates"])

# --- 3. 圖片處理函數 ---
def encode_image(image_file):
    return base64.b64encode(image_file.getvalue()).decode('utf-8')

# --- 4. 調用 GPT-4o 視覺模型 ---
def call_ai_vision(image_file, sku, category, instruction):
    if not api_key:
        st.error("❌ 找不到 API Key，請在 Secrets 或側邊欄配置")
        return None
        
    client = OpenAI(api_key=api_key)
    base64_image = encode_image(image_file)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"你是一個亞馬遜專家。SKU是{sku}，類目是{category}。請識別圖中的圖案元素，並根據要求寫出標題、五點、關鍵詞和圖案詞：{instruction}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ],
                }
            ],
            max_tokens=1000,
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"❌ AI 調用失敗: {str(e)}")
        return None

# --- 5. 主界面 ---
st.title("🤖 亞馬遜智能 AI 視覺填充系統")
st.info("💡 當前狀態：API Key 已通過 Secrets 安全加載" if "OPENAI_API_KEY" in st.secrets else "💡 當前狀態：請在側邊欄手動輸入 Key")

uploaded_images = st.file_uploader("📤 上傳產品圖片 (文件名即為 SKU)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
instruction = st.text_area("✍️ 寫給 AI 的指令", value="請識別圖案元素，寫出吸引人的標題、5點描述、Search Terms、以及精煉的圖案元素詞（用於Color欄位）。")

if st.button("🚀 啟動 AI 識別並填充表格"):
    if not uploaded_images:
        st.error("❌ 請先上傳圖片")
    else:
        results = []
        progress = st.progress(0)
        
        for i, img in enumerate(uploaded_images):
            sku = os.path.splitext(img.name)[0]
            st.write(f"正在分析 SKU: **{sku}**...")
            
            ai_text = call_ai_vision(img, sku, selected_category, instruction)
            
            if ai_text:
                today = datetime.now()
                s_start = (today - timedelta(days=1)).strftime('%Y-%m-%d')
                s_end = (today - timedelta(days=1) + timedelta(days=364)).strftime('%Y-%m-%d')
                
                results.append({
                    "SKU": sku,
                    "AI 分析結果": ai_text,
                    "Sale Start": s_start,
                    "Sale End": s_end
                })
            progress.progress((i + 1) / len(uploaded_images))
            
        if results:
            final_df = pd.DataFrame(results)
            st.success("✅ 識別完成！")
            st.dataframe(final_df)
            
            output = io.BytesIO()
            final_df.to_excel(output, index=False)
            st.download_button("💾 下載填充好的數據", output.getvalue(), "Amazon_AI_Listing.xlsx")
