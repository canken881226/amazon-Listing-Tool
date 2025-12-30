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
st.set_page_config(page_title="亞馬遜 AI 精細化上架 V5.6", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 固化專業寫作邏輯 (針對 150字符、單詞關鍵詞優化) ---
SYSTEM_LOGIC = """
你是一位亞馬遜精細化運營專家。請執行以下規則：
1. 標題: 長度控制在 130-150 字符。包含類目詞+核心賣點，不含尺寸。
2. 五點 (BP): 嚴格分 5 條。每條開頭加粗。
3. 關鍵詞 (Search Terms): 僅輸出單個單詞，用空格隔開，不含標點，去重，總長 < 250 字符。
4. 描述: HTML 格式，包含 <b>, <br>。
"""

# --- 3. 側邊欄 ---
with st.sidebar:
    st.header("📂 系統配置")
    if api_key: st.success("✅ API Key 已就緒")
    t_path = os.path.join(os.getcwd(), "templates")
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇模板", all_tpls if all_tpls else ["⚠️ 無模板"])

# --- 4. 輔助函數 ---
def process_img(file):
    img = Image.open(file)
    img.thumbnail((1000, 1000))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai(img_file, sku_prefix, keywords):
    client = OpenAI(api_key=api_key)
    b64 = process_img(img_file)
    prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\n關鍵詞組:{keywords}\n返回JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
        response_format={"type":"json_object"}
    )
    return json.loads(res.choices[0].message.content)

# --- 5. 主界面 ---
st.title("🤖 亞馬遜 AI 精細化填充 V5.6")

# 尺寸與價格動態配置
st.subheader("💰 尺寸與價格配置")
size_price_data = st.data_editor(
    pd.DataFrame([
        {"Size": '16x24"', "Price": "19.99"},
        {"Size": '24x32"', "Price": "29.99"},
        {"Size": '24x48"', "Price": "39.99"}
    ]),
    num_rows="dynamic"
)

col_img, col_kw = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上傳圖片", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_kw:
    user_keywords = st.text_area("📝 此款式關鍵詞庫", height=200)

# --- 6. 執行填充 ---
if st.button("🚀 啟動優化填充", use_container_width=True):
    if not uploaded_imgs: st.error("請上傳圖片")
    else:
        try:
            wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
            sheet = wb.active
            # 獲取標題列映射
            headers = {cell.value: cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
            
            # 獲取五點特徵的所有列 index
            bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value == "Key Product Features"]

            img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
            parent_sku = f"{img_prefixes[0]}-P"

            t = datetime.now()
            s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
            
            current_row = 4 # 從第四行開始 (父體)
            
            with st.status("正在處理...") as status:
                for img in uploaded_imgs:
                    prefix = os.path.splitext(img.name)[0]
                    ai_data = call_ai(img, prefix, user_keywords)
                    
                    # --- A. 填充父體 (Row 4) ---
                    if i == 0: # 僅第一張圖的信息作為父體代表
                        sheet.cell(row=4, column=headers["Seller SKU"]).value = parent_sku
                        sheet.cell(row=4, column=headers["Parentage"]).value = "parent"
                        if "Product Name" in headers: sheet.cell(row=4, column=headers["Product Name"]).value = ai_data['title']
                        if "Product Description" in headers: sheet.cell(row=4, column=headers["Product Description"]).value = ai_data['desc']
                        if "Generic Keyword" in headers: sheet.cell(row=4, column=headers["Generic Keyword"]).value = ai_data['keywords']
                        for idx, col_idx in enumerate(bp_cols[:5]):
                            if idx < len(ai_data['bp']): sheet.cell(row=4, column=col_idx).value = ai_data['bp'][idx]
                        current_row = 5 # 子體從第五行開始

                    # --- B. 循環子體 ---
                    for _, row_data in size_price_data.iterrows():
                        sz = row_data["Size"]
                        pr = row_data["Price"]
                        
                        # SKU & 關係
                        if "Seller SKU" in headers: sheet.cell(row=current_row, column=headers["Seller SKU"]).value = f"{prefix}-{sz.replace('\"','')}"
                        if "Parent SKU" in headers: sheet.cell(row=current_row, column=headers["Parent SKU"]).value = parent_sku
                        if "Parentage" in headers: sheet.cell(row=current_row, column=headers["Parentage"]).value = "child"
                        
                        # 標題 (末尾加尺寸)
                        full_title = f"{ai_data['title']} - {sz}"
                        if "Product Name" in headers: sheet.cell(row=current_row, column=headers["Product Name"]).value = full_title[:150]
                        
                        # 價格與尺寸
                        if "Standard Price" in headers: sheet.cell(row=current_row, column=headers["Standard Price"]).value = pr
                        if "Size" in headers: sheet.cell(row=current_row, column=headers["Size"]).value = sz
                        if "Size Map" in headers: sheet.cell(row=current_row, column=headers["Size Map"]).value = sz
                        
                        # 文案同步
                        if "Product Description" in headers: sheet.cell(row=current_row, column=headers["Product Description"]).value = ai_data['desc']
                        if "Generic Keyword" in headers: sheet.cell(row=current_row, column=headers["Generic Keyword"]).value = ai_data['keywords']
                        if "Color" in headers: sheet.cell(row=current_row, column=headers["Color"]).value = ai_data['color']
                        
                        # 五點寫入 (修復亂碼/錯位)
                        for idx, col_idx in enumerate(bp_cols[:5]):
                            if idx < len(ai_data['bp']):
                                sheet.cell(row=current_row, column=col_idx).value = ai_data['bp'][idx]
                        
                        current_row += 1
                
                status.update(label="✅ 優化填充完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載優化後的 Excel (.xlsm)", output.getvalue(), f"Amazon_{prefix}.xlsm", use_container_width=True)

        except Exception as e:
            st.error(f"錯誤: {e}")
