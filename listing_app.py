import streamlit as st
import pandas as pd
import io
import os
import base64
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 頁面配置 (對齊決策系統風格) ---
st.set_page_config(page_title="亞馬遜 AI 智能上架系統 V4.0", layout="wide")

# 安全讀取 Secrets 中的 Key
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = st.sidebar.text_input("🔑 填入 API Key (若 Secrets 未配置)", type="password")

# --- 2. 側邊欄：模板與類目管理 ---
with st.sidebar:
    st.header("📂 官方模板配置")
    # 從 templates 文件夾讀取官方 xlsx
    t_path = "templates/"
    all_tpls = [f for f in os.listdir(t_path) if f.endswith('.xlsx')] if os.path.exists(t_path) else []
    selected_tpl = st.selectbox("選擇當前上架類目模板", all_tpls if all_tpls else ["請先上傳模板至 templates/"])
    
    st.divider()
    st.header("⚙️ 輸出偏好")
    lang = st.radio("文案語言", ["英文 (US)", "德文 (DE)", "日文 (JP)"])
    tone = st.selectbox("文案風格", ["專業吸引", "簡潔有力", "感性描述"])

# --- 3. 主界面布局 ---
st.title("🤖 亞馬遜 AI 智能 Flat File 填充站")

# 第一行：圖片上傳與 AI 指令
col_img, col_cmd = st.columns([1, 1])

with col_img:
    st.subheader("🖼️ 1. 上傳產品圖片")
    uploaded_imgs = st.file_uploader("支持多圖批量上傳，文件名即為 SKU", 
                                     type=["jpg", "png", "jpeg"], accept_multiple_files=True)
    if uploaded_imgs:
        st.write(f"✅ 已加載 {len(uploaded_imgs)} 張圖片")

with col_cmd:
    st.subheader("💬 2. ChatGPT 視覺分析指令")
    user_instruction = st.text_area("給 AI 的具體要求", 
                                    value="請識別圖片中的圖案元素、顏色、材質。生成吸引人的標題(150字內)、5點描述、以及精確的圖案元素詞(用於Color欄位)。",
                                    height=150)

# --- 4. 核心功能：AI 視覺與數據填充 ---
def encode_img(file):
    return base64.b64encode(file.getvalue()).decode('utf-8')

if st.button("🔥 啟動 AI 識別並填充官方表格", use_container_width=True):
    if not uploaded_imgs:
        st.error("請先上傳圖片！")
    elif not api_key:
        st.error("缺少 API Key！")
    else:
        results = []
        progress = st.progress(0)
        client = OpenAI(api_key=api_key)

        for idx, img in enumerate(uploaded_imgs):
            sku = os.path.splitext(img.name)[0] # 從文件名提取 SKU
            st.toast(f"AI 正在分析圖片: {sku}...")
            
            # 調用 GPT-4o 視覺
            b64 = encode_img(img)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"SKU: {sku}. 指令: {user_instruction}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    ]
                }],
                max_tokens=800
            )
            ai_content = response.choices[0].message.content
            
            # 自動計算時間 (昨天到一年後)
            t = datetime.now()
            results.append({
                "item_sku": sku,
                "AI_Draft_Review": ai_content, # 先展示 AI 草稿供確認
                "sale_start_date": (t - timedelta(days=1)).strftime('%Y-%m-%d'),
                "sale_end_date": (t + timedelta(days=364)).strftime('%Y-%m-%d')
            })
            progress.progress((idx + 1) / len(uploaded_imgs))

        # --- 5. 輸出預覽與導出 ---
        st.divider()
        st.subheader("📊 3. 填充結果預覽 (對齊官方欄位)")
        df_final = pd.DataFrame(results)
        st.dataframe(df_final, use_container_width=True)

        # 導出為 Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, index=False, sheet_name='Template')
        
        st.download_button("💾 下載填充好的官方表格", output.getvalue(), 
                           file_name=f"Amazon_Listing_{datetime.now().strftime('%m%d')}.xlsx",
                           use_container_width=True)
