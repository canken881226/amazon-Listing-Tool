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
from PIL import Image

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 智能上架 V5.3", layout="wide")

# --- 2. 密鑰安全診斷 ---
api_key = ""
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
    st.sidebar.success("✅ Secrets API Key 已加載")
else:
    api_key = st.sidebar.text_input("🔑 手動輸入 API Key (Secrets 未偵測到)", type="password")
    if not api_key:
        st.sidebar.warning("⚠️ 請在 Secrets 或此處填入 Key 以啟用功能")

# --- 3. 固化寫作邏輯 ---
SYSTEM_LOGIC = """
你是一位資深亞馬遜運營專家。請嚴格遵守放置規劃：
1. 標題: 前80字符含類目詞+賣點。不堆砌，不侵權。
2. Bullets: B1功能, B2結構/3D效果, B3材質(Vinyl), B4場景, B5簡單安裝。
3. Description: 必須含HTML標籤(<b>, <br>)，採用問題→解決→場景邏輯。
4. 禁忌: 嚴禁誇大詞(Best/Top/100%)。符合 Rufus 自然語言偏好。
"""

# --- 4. 側邊欄：模板管理 ---
with st.sidebar:
    st.header("📂 模板配置")
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path): os.makedirs(t_path)
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇官方模板", all_tpls if all_tpls else ["⚠️ 請上傳模板"])

# --- 5. 圖片處理優化 ---
def process_and_encode_img(file):
    img = Image.open(file)
    if max(img.size) > 1200:
        img.thumbnail((1200, 1200))
    buffered = io.BytesIO()
    img.convert("RGB").save(buffered, format="JPEG", quality=75)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def call_ai_vision(img_file, sku_prefix, user_keywords):
    if not api_key:
        raise Exception("API Key 未配置")
    
    client = OpenAI(api_key=api_key)
    b64 = process_and_encode_img(img_file)
    
    final_prompt = f"{SYSTEM_LOGIC}\n\nSKU:{sku_prefix}\n關鍵詞組:\n{user_keywords}\n\n返回JSON: {{'title':'', 'desc':'', 'bp':['','','','',''], 'keywords':'', 'color':''}}"
    
    # 增加超時控制，防止卡死
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": final_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]}],
        response_format={ "type": "json_object" },
        timeout=45.0 
    )
    return json.loads(response.choices[0].message.content)

# --- 6. 主界面 ---
st.title("🤖 亞馬遜 AI 智能填充系統 V5.3")

size_input = st.text_input("📏 輸入子變體尺寸 (逗號隔開)", value='16x24", 24x32", 24x48"')
size_list = [s.strip() for s in size_input.split(",") if s.strip()]

col_img, col_cmd = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上傳圖案 (文件名為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_cmd:
    user_keywords = st.text_area("📝 填入此款式的關鍵詞組", placeholder="請粘貼關鍵詞...", height=200)

# --- 7. 執行邏輯 ---
if st.button("🚀 啟動 AI 識別並填充原表", use_container_width=True):
    if not uploaded_imgs:
        st.error("❌ 請上傳圖片")
    elif not api_key:
        st.error("❌ 缺少 API Key，請檢查左側配置")
    elif "請上傳" in selected_tpl:
        st.error("❌ 尚未在 templates 文件夾中檢測到模板")
    else:
        try:
            status_container = st.container()
            with status_container:
                st.info("🔄 正在讀取模板並分析圖片...")
                
            wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
            sheet = wb.active
            headers = {cell.value: cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
            
            img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
            parent_sku = f"{img_prefixes[0]}-{img_prefixes[-1].split('-')[-1]}" if len(img_prefixes) > 1 else img_prefixes[0]
            
            if headers.get("Seller SKU"): sheet.cell(row=4, column=headers["Seller SKU"]).value = parent_sku
            if headers.get("Parentage"): sheet.cell(row=4, column=headers["Parentage"]).value = "parent"

            current_row = 5
            t = datetime.now()
            s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
            
            progress_bar = st.progress(0)
            
            for i, img in enumerate(uploaded_imgs):
                prefix = os.path.splitext(img.name)[0]
                st.write(f"⏳ 正在分析: **{prefix}**")
                
                # 這裡最容易卡死，加入錯誤捕捉
                try:
                    ai_data = call_ai_vision(img, prefix, user_keywords)
                except Exception as ai_err:
                    st.error(f"❌ AI 分析失敗 ({prefix}): {str(ai_err)}")
                    continue # 跳過錯誤項
                
                for size in size_list:
                    c_sku = f"{prefix}-{size}"
                    if headers.get("Seller SKU"): sheet.cell(row=current_row, column=headers["Seller SKU"]).value = c_sku
                    if headers.get("Parent SKU"): sheet.cell(row=current_row, column=headers["Parent SKU"]).value = parent_sku
                    if headers.get("Parentage"): sheet.cell(row=current_row, column=headers["Parentage"]).value = "child"
                    if headers.get("Size"): sheet.cell(row=current_row, column=headers["Size"]).value = size
                    if headers.get("Product Name"): sheet.cell(row=current_row, column=headers["Product Name"]).value = ai_data['title']
                    if headers.get("Product Description"): sheet.cell(row=current_row, column=headers["Product Description"]).value = ai_data['desc']
                    if headers.get("Generic Keyword"): sheet.cell(row=current_row, column=headers["Generic Keyword"]).value = ai_data['keywords']
                    if headers.get("Color"): sheet.cell(row=current_row, column=headers["Color"]).value = ai_data['color']
                    if headers.get("Sale Start Date"): sheet.cell(row=current_row, column=headers["Sale Start Date"]).value = s_start
                    if headers.get("Sale End Date"): sheet.cell(row=current_row, column=headers["Sale End Date"]).value = s_end
                    
                    bp_cols = [c for v, c in headers.items() if v == "Key Product Features"]
                    for bp_idx, bp_col in enumerate(bp_cols[:5]):
                        if bp_idx < len(ai_data['bp']):
                            sheet.cell(row=current_row, column=bp_col).value = ai_data['bp'][bp_idx]
                    current_row += 1
                progress_bar.progress((i + 1) / len(uploaded_imgs))

            st.success("✅ 填充完成！")
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            
            st.download_button(
                label="💾 立即下載填充好的官方原表 (.xlsm)",
                data=output.getvalue(),
                file_name=f"Filled_Listing_{parent_sku}.xlsm",
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"❌ 嚴重錯誤: {str(e)}")
