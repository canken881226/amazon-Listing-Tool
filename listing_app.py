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

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="亞馬遜 AI 多尺寸填充工具 V4.7", layout="wide")

# 安全讀取 Secrets 中的 OpenAI Key
api_key = st.secrets.get("OPENAI_API_KEY") or st.sidebar.text_input("🔑 填入 API Key", type="password")

# --- 2. 側邊欄：模板管理 ---
with st.sidebar:
    st.header("📂 模板配置")
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path): os.makedirs(t_path)
    # 讀取 xlsx 和 xlsm
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇要填充的官方模板", all_tpls if all_tpls else ["請先上傳模板至 templates/"])

# --- 3. 核心函數 ---
def encode_img(file):
    """將圖片轉換為 Base64"""
    return base64.b64encode(file.getvalue()).decode('utf-8')

def generate_parent_sku(image_skus):
    """根據子體前綴生成父類 SKU (格式: 前綴-起始-結束)"""
    if not image_skus: return "PARENT-SKU"
    image_skus.sort()
    first, last = image_skus[0], image_skus[-1]
    # 正則提取前綴與序號
    prefix_match = re.match(r"(.*-)(\d+)", first)
    if prefix_match:
        prefix = prefix_match.group(1)
        start_num = prefix_match.group(2)
        end_match = re.search(r"(\d+)$", last)
        end_num = end_match.group(1) if end_match else start_num
        return f"{prefix}{start_num}-{end_num}"
    return f"{first}-PARENT"

def call_ai_vision(img_file, sku_prefix, instruction):
    """調用 OpenAI 視覺模型分析圖案元素"""
    client = OpenAI(api_key=api_key)
    b64 = encode_img(img_file)
    # 強制要求 JSON 返回
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"SKU前綴:{sku_prefix}。分析圖片並返回JSON: {{'title':'', 'desc':'', 'bp':['','','','',''], 'keywords':'', 'color':''}}。指令: {instruction}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)

# --- 4. 主界面 ---
st.title("🤖 亞馬遜 AI 多尺寸變體填充系統")

st.subheader("📏 尺寸自定義配置")
size_input = st.text_input("輸入子變體尺寸 (多個請用英文逗號隔開)", value='16x24", 24x32", 24x48"')
size_list = [s.strip() for s in size_input.split(",") if s.strip()]

col_img, col_cmd = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("上傳圖片 (文件名即 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_cmd:
    user_instruction = st.text_area("文案要求", value="識別圖案元素，生成標題、5點描述、關鍵詞及圖案詞(Color)。", height=150)

if st.button("🚀 啟動 AI 批量生成並填充", use_container_width=True):
    if not uploaded_imgs:
        st.error("❌ 請上傳圖片")
    elif not api_key:
        st.error("❌ 缺少 API Key，請檢查 Secrets 配置")
    elif not selected_tpl or "請檢查" in selected_tpl:
        st.error("❌ 請選擇正確的 Excel 模板")
    else:
        try:
            with st.spinner("正在加載模板並聯繫 AI..."):
                wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 掃描欄位座標
                headers = {}
                for row in sheet.iter_rows(min_row=1, max_row=3):
                    for cell in row:
                        if cell.value: headers[cell.value] = cell.column
                
                mapping = {
                    "SKU": headers.get("Seller SKU"),
                    "ParentSKU": headers.get("Parent SKU"),
                    "Parentage": headers.get("Parentage"),
                    "Title": headers.get("Product Name"),
                    "Desc": headers.get("Product Description"),
                    "BP": [c for v, c in headers.items() if v == "Key Product Features"],
                    "KW": headers.get("Generic Keyword"),
                    "Color": headers.get("Color"),
                    "Size": headers.get("Size"),
                    "Start": headers.get("Sale Start Date"),
                    "End": headers.get("Sale End Date")
                }

                # 生成父類 SKU
                img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
                parent_sku = generate_parent_sku(img_prefixes)
                
                # 填充父類行 (第 4 行)
                if mapping["SKU"]: sheet.cell(row=4, column=mapping["SKU"]).value = parent_sku
                if mapping["Parentage"]: sheet.cell(row=4, column=mapping["Parentage"]).value = "parent"

                # 填充子類行
                current_fill_row = 5
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                
                progress = st.progress(0)
                for i, img in enumerate(uploaded_imgs):
                    prefix = os.path.splitext(img.name)[0]
                    st.write(f"正在分析圖案: **{prefix}**")
                    ai_data = call_ai_vision(img, prefix, user_instruction)
                    
                    for size in size_list:
                        child_sku = f"{prefix}-{size}"
                        # 執行填充
                        if mapping["SKU"]: sheet.cell(row=current_fill_row, column=mapping["SKU"]).value = child_sku
                        if mapping["ParentSKU"]: sheet.cell(row=current_fill_row, column=mapping["ParentSKU"]).value = parent_sku
                        if mapping["Parentage"]: sheet.cell(row=current_fill_row, column=mapping["Parentage"]).value = "child"
                        if mapping["Size"]: sheet.cell(row=current_fill_row, column=mapping["Size"]).value = size
                        if mapping["Title"]: sheet.cell(row=current_fill_row, column=mapping["Title"]).value = ai_data['title']
                        if mapping["Desc"]: sheet.cell(row=current_fill_row, column=mapping["Desc"]).value = ai_data['desc']
                        if mapping["Color"]: sheet.cell(row=current_fill_row, column=mapping["Color"]).value = ai_data['color']
                        if mapping["KW"]: sheet.cell(row=current_fill_row, column=mapping["KW"]).value = ai_data['keywords']
                        if mapping["Start"]: sheet.cell(row=current_fill_row, column=mapping["Start"]).value = s_start
                        if mapping["End"]: sheet.cell(row=current_fill_row, column=mapping["End"]).value = s_end
                        for bp_idx, bp_col in enumerate(mapping["BP"][:5]):
                            sheet.cell(row=current_fill_row, column=bp_col).value = ai_data['bp'][bp_idx]
                        current_fill_row += 1
                    progress.progress((i + 1) / len(uploaded_imgs))

                output = io.BytesIO()
                wb.save(output)
                st.success(f"🎉 填充完畢！生成父體: {parent_sku}")
                st.download_button("💾 下載變體表格", output.getvalue(), file_name=f"Variation_{parent_sku}.xlsm")
        except Exception as e:
            st.error(f"❌ 運行錯誤: {str(e)}")
