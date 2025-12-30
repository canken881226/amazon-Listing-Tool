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
st.set_page_config(page_title="亞馬遜 AI 原表填充 V5.0", layout="wide")

# 安全讀取 Secrets
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 側邊欄：模板管理 ---
with st.sidebar:
    st.header("📂 模板配置")
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path): os.makedirs(t_path)
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇要填充的官方模板", all_tpls if all_tpls else ["⚠️ 請上傳模板"])
    if not api_key:
        api_key = st.text_input("🔑 API Key (Secrets 未配置時填寫)", type="password")

# --- 3. 圖片處理：自動縮圖 ---
def process_and_encode_img(file):
    img = Image.open(file)
    # 若圖片太大，縮小尺寸以加快 API 響應
    if max(img.size) > 1500:
        img.thumbnail((1500, 1500))
    
    buffered = io.BytesIO()
    img.convert("RGB").save(buffered, format="JPEG", quality=80)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def call_ai_vision(img_file, sku_prefix, instruction):
    client = OpenAI(api_key=api_key)
    b64 = process_and_encode_img(img_file)
    
    prompt_text = f"你是一個亞馬遜專家。產品前綴SKU:{sku_prefix}。請識別圖中的圖案、風格，並嚴格返回JSON格式：{{'title':'', 'desc':'', 'bp':['','','','',''], 'keywords':'', 'color':''}}。具體要求: {instruction}"
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]}],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)

# --- 4. 主界面 ---
st.title("🤖 亞馬遜 AI 原表填充系統 (V5.0 穩定版)")

size_input = st.text_input("📏 輸入子變體尺寸 (英文逗號隔開)", value='16x24", 24x32", 24x48"')
size_list = [s.strip() for s in size_input.split(",") if s.strip()]

col_img, col_cmd = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上傳圖片 (文件名為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_cmd:
    user_instruction = st.text_area("💬 給 AI 的指令", value="請根據圖片內容生成標題、五點、關鍵詞和圖案元素詞。", height=150)

# --- 5. 啟動與填充邏輯 ---
if st.button("🚀 啟動分析並填充模板", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 請先上傳圖片")
    elif not api_key: st.error("❌ 缺少 API Key")
    elif "請上傳" in selected_tpl: st.error("❌ 尚未檢測到 Excel 模板")
    else:
        try:
            with st.spinner("正在進行 AI 視覺分析..."):
                template_path = os.path.join(t_path, selected_tpl)
                wb = openpyxl.load_workbook(template_path, keep_vba=True)
                sheet = wb.active
                
                # 掃描前 3 行找到標題
                headers = {cell.value: cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                
                # SKU 前綴與 Parent SKU 生成
                img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
                parent_sku = f"{img_prefixes[0]}-{img_prefixes[-1].split('-')[-1]}" if len(img_prefixes) > 1 else img_prefixes[0]
                
                # 填充父體 (Row 4)
                if headers.get("Seller SKU"): sheet.cell(row=4, column=headers["Seller SKU"]).value = parent_sku
                if headers.get("Parentage"): sheet.cell(row=4, column=headers["Parentage"]).value = "parent"

                current_row = 5
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                
                # 用於網頁預覽
                preview_list = []

                for img in uploaded_imgs:
                    prefix = os.path.splitext(img.name)[0]
                    ai_data = call_ai_vision(img, prefix, user_instruction)
                    preview_list.append({"SKU": prefix, "標題": ai_data['title']})
                    
                    for size in size_list:
                        c_sku = f"{prefix}-{size}"
                        # 填充邏輯
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
                        
                        # 處理重複名稱的 Key Product Features
                        bp_cols = [c for v, c in headers.items() if v == "Key Product Features"]
                        for bp_idx, bp_col in enumerate(bp_cols[:5]):
                            if bp_idx < len(ai_data['bp']):
                                sheet.cell(row=current_row, column=bp_col).value = ai_data['bp'][bp_idx]
                        current_row += 1

                # 生成下載
                output = io.BytesIO()
                wb.save(output)
                output.seek(0)
                
                st.success(f"🎉 成功完成 {len(img_prefixes)} 款產品的 AI 文案分析與填充！")
                st.download_button(
                    label="💾 點此立即下載官方表格 (.xlsm)",
                    data=output.getvalue(),
                    file_name=f"Amazon_Bulk_{datetime.now().strftime('%m%d')}.xlsm",
                    mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                    use_container_width=True
                )
                st.write("🔍 **AI 文案預覽：**", pd.DataFrame(preview_list))

        except Exception as e:
            st.error(f"❌ 發生錯誤：{str(e)}")
