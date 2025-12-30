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
st.set_page_config(page_title="亞馬遜 AI 精細化填充 V5.7", layout="wide")

# 安全讀取 Secrets
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 固化專業寫作邏輯 (150字符、單詞關鍵詞) ---
SYSTEM_LOGIC = """
你是一位亞馬遜精細化運營專家。請執行以下規則：
1. 標題: 長度 130-150 字符。包含類目詞+核心賣點，不含尺寸。
2. 五點 (BP): 嚴格分 5 條。每條開頭加粗。
3. 關鍵詞 (Search Terms): 僅輸出單個單詞，用空格隔開，不含標點，去重，總長控制在 200-250 字符。
4. 描述: HTML 格式，包含 <b>, <br>，採用 問題->解決->場景 邏輯。
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
        response_format={"type":"json_object"},
        timeout=60
    )
    return json.loads(res.choices[0].message.content)

# --- 5. 主界面 ---
st.title("🤖 亞馬遜 AI 精細化填充 V5.7")

# 尺寸與價格動態配置
st.subheader("💰 尺寸與價格配置 (價格將對應 Sale Price)")
default_sp = pd.DataFrame([
    {"Size": '16x24"', "Price": "9.99"},
    {"Size": '24x36"', "Price": "16.99"},
    {"Size": '32x48"', "Price": "18.99"}
])
size_price_data = st.data_editor(default_sp, num_rows="dynamic")

col_img, col_kw = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上傳圖片 (SKU前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_kw:
    user_keywords = st.text_area("📝 此款式關鍵詞庫", height=200, placeholder="請粘貼關鍵詞...")

# --- 6. 執行填充 ---
if st.button("🚀 啟動優化填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 請先上傳圖片")
    elif not api_key: st.error("❌ 缺少 API Key")
    else:
        try:
            with st.status("🔄 正在執行精細化填充...") as status:
                st.write("正在讀取模板與掃描欄位...")
                wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 掃描標題列映射
                headers = {cell.value.strip(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value == "Key Product Features"]

                # 日期計算
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                
                # 父體行號 (Row 4)
                parent_row = 4
                current_row = 5 # 子體從 Row 5 開始
                
                # 取上傳的第一張圖作為父類代表
                first_img = uploaded_imgs[0]
                first_prefix = os.path.splitext(first_img.name)[0]
                parent_sku_name = f"{first_prefix}-P"
                
                st.write(f"正在為父體 **{parent_sku_name}** 生成文案...")
                ai_data = call_ai(first_img, first_prefix, user_keywords)

                # --- 填充父體 (Row 4) ---
                if "Seller SKU" in headers: sheet.cell(row=parent_row, column=headers["Seller SKU"]).value = parent_sku_name
                if "Parentage" in headers: sheet.cell(row=parent_row, column=headers["Parentage"]).value = "parent"
                if "Product Name" in headers: sheet.cell(row=parent_row, column=headers["Product Name"]).value = ai_data['title']
                if "Product Description" in headers: sheet.cell(row=parent_row, column=headers["Product Description"]).value = ai_data['desc']
                if "Generic Keyword" in headers: sheet.cell(row=parent_row, column=headers["Generic Keyword"]).value = ai_data['keywords']
                if "Color" in headers: sheet.cell(row=parent_row, column=headers["Color"]).value = ai_data['color']
                # 填充父體五點
                for idx, col_idx in enumerate(bp_cols[:5]):
                    if idx < len(ai_data['bp']): sheet.cell(row=parent_row, column=col_idx).value = ai_data['bp'][idx]

                # --- 循環子體填充 ---
                for img in uploaded_imgs:
                    prefix = os.path.splitext(img.name)[0]
                    st.write(f"正在處理圖片: **{prefix}** ...")
                    # 每一款圖案都重新分析以保證 Color 準確
                    child_ai_data = call_ai(img, prefix, user_keywords)
                    
                    for _, row_data in size_price_data.iterrows():
                        sz = str(row_data["Size"])
                        pr = str(row_data["Price"])
                        # 生成子體 SKU：去掉引號防止路徑出錯
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        
                        # 基礎資訊填充
                        if "Seller SKU" in headers: sheet.cell(row=current_row, column=headers["Seller SKU"]).value = c_sku
                        if "Parent SKU" in headers: sheet.cell(row=current_row, column=headers["Parent SKU"]).value = parent_sku_name
                        if "Parentage" in headers: sheet.cell(row=current_row, column=headers["Parentage"]).value = "child"
                        
                        # 標題加尺寸
                        full_title = f"{child_ai_data['title']} - {sz}"
                        if "Product Name" in headers: sheet.cell(row=current_row, column=headers["Product Name"]).value = full_title[:150]
                        
                        # 價格與尺寸映射 (精確匹配 Sale Price)
                        if "Sale Price" in headers: sheet.cell(row=current_row, column=headers["Sale Price"]).value = pr
                        if "Size" in headers: sheet.cell(row=current_row, column=headers["Size"]).value = sz
                        if "Size Map" in headers: sheet.cell(row=current_row, column=headers["Size Map"]).value = sz
                        
                        # 促銷日期
                        if "Sale Start Date" in headers: sheet.cell(row=current_row, column=headers["Sale Start Date"]).value = s_start
                        if "Sale End Date" in headers: sheet.cell(row=current_row, column=headers["Sale End Date"]).value = s_end

                        # 內容填充
                        if "Product Description" in headers: sheet.cell(row=current_row, column=headers["Product Description"]).value = child_ai_data['desc']
                        if "Generic Keyword" in headers: sheet.cell(row=current_row, column=headers["Generic Keyword"]).value = child_ai_data['keywords']
                        if "Color" in headers: sheet.cell(row=current_row, column=headers["Color"]).value = child_ai_data['color']
                        
                        # 子體五點
                        for idx, col_idx in enumerate(bp_cols[:5]):
                            if idx < len(child_ai_data['bp']): sheet.cell(row=current_row, column=col_idx).value = child_ai_data['bp'][idx]
                        
                        current_row += 1
                
                status.update(label="✅ 優化填充完成！文件已生成。", state="complete")

            # --- 下載按鈕 ---
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            st.divider()
            st.balloons()
            st.download_button(
                label="💾 立即下載填充好的官方原表 (.xlsm)",
                data=output.getvalue(),
                file_name=f"Amazon_Listing_{parent_sku_name}.xlsm",
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"❌ 發生嚴重錯誤: {str(e)}")
            st.info("💡 提示：請檢查模板標題是否包含 'Sale Price', 'Size Map' 等關鍵字。")
