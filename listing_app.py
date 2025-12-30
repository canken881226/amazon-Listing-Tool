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

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 多尺寸填充工具 V4.6", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or st.sidebar.text_input("🔑 API Key", type="password")

# --- 2. 側邊欄：模板管理 ---
with st.sidebar:
    st.header("📂 模板配置")
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path): os.makedirs(t_path)
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇要填充的官方模板", all_tpls if all_tpls else ["請檢查 templates 文件夾"])

# --- 3. 核心函數 ---
def encode_img(file):
    return base64.b64encode(file.getvalue()).decode('utf-8')

def generate_parent_sku(image_skus):
    """根據圖片前綴生成父類名稱"""
    if not image_skus: return "PARENT-SKU"
    image_skus.sort()
    first, last = image_skus[0], image_skus[-1]
    prefix = re.match(r"(.*-)\d+", first).group(1) if re.match(r"(.*-)\d+", first) else "PARENT-"
    start_num = re.findall(r"\d+", first)[-1]
    end_num = re.findall(r"\d+", last)[-1]
    return f"{prefix}{start_num}-{end_num}"

def call_ai_vision(img_file, sku_prefix, instruction):
    client = OpenAI(api_key=api_key)
    b64 = encode_img(img_file)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"前綴SKU:{sku_prefix}。請分析圖片並返回JSON：{{'title':'', 'desc':'', 'bp':['','','','',''], 'keywords':'', 'color':''}}。要求：{instruction}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)

# --- 4. 主界面 ---
st.title("🤖 亞馬遜 AI 多尺寸變體填充系統")

# 新增尺寸自定義輸入框
st.subheader("📏 尺寸自定義配置")
size_input = st.text_input("輸入子變體尺寸 (多個請用英文逗號隔開)", value='16x24", 24x32", 24x48"')
size_list = [s.strip() for s in size_input.split(",") if s.strip()]

col_img, col_cmd = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("上傳圖案圖片 (文件名即為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_cmd:
    user_instruction = st.text_area("文案要求", value="請識別圖案元素，生成吸引人的標題、5點描述、Search Terms、以及圖案元素詞。")

if st.button("🚀 啟動 AI 批量生成並填充", use_container_width=True):
    if not uploaded_imgs or not selected_tpl or not size_list:
        st.error("請確認圖片、模板和尺寸列表已就位")
    else:
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
            "ColorMap": headers.get("Color Map"), # 您提到的額外欄位
            "Size": headers.get("Size"),
            "SizeMap": headers.get("Size Map"),
            "Price": headers.get("Sale Price"),
            "Start": headers.get("Sale Start Date"),
            "End": headers.get("Sale End Date")
        }

        # 1. 生成父類名稱
        img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
        parent_sku = generate_parent_sku(img_prefixes)
        
        # 2. 填充父類行 (第 4 行)
        p_row = 4
        if mapping["SKU"]: sheet.cell(row=p_row, column=mapping["SKU"]).value = parent_sku
        if mapping["Parentage"]: sheet.cell(row=p_row, column=mapping["Parentage"]).value = "parent"

        # 3. 填充子類行 (從第 5 行開始展開)
        current_fill_row = 5
        t = datetime.now()
        s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
        
        for img in uploaded_imgs:
            prefix = os.path.splitext(img.name)[0]
            st.write(f"正在分析圖案: **{prefix}**...")
            ai_data = call_ai_vision(img, prefix, user_instruction)
            
            for size in size_list:
                child_sku = f"{prefix}-{size}"
                st.write(f"  > 生成子體: {child_sku}")
                
                # 執行填充
                if mapping["SKU"]: sheet.cell(row=current_fill_row, column=mapping["SKU"]).value = child_sku
                if mapping["ParentSKU"]: sheet.cell(row=current_fill_row, column=mapping["ParentSKU"]).value = parent_sku
                if mapping["Parentage"]: sheet.cell(row=current_fill_row, column=mapping["Parentage"]).value = "child"
                if mapping["Size"]: sheet.cell(row=current_fill_row, column=mapping["Size"]).value = size
                
                # AI 文案填充
                if mapping["Title"]: sheet.cell(row=current_fill_row, column=mapping["Title"]).value = ai_data['title']
                if mapping["Desc"]: sheet.cell(row=current_fill_row, column=mapping["Desc"]).value = ai_data['desc']
                if mapping["Color"]: sheet.cell(row=current_fill_row, column=mapping["Color"]).value = ai_data['color']
                if mapping["KW"]: sheet.cell(row=current_fill_row, column=mapping["KW"]).value = ai_data['keywords']
                if mapping["Start"]: sheet.cell(row=current_fill_row, column=mapping["Start"]).value = s_start
                if mapping["End"]: sheet.cell(row=current_fill_row, column=mapping["End"]).value = s_end
                for i, bp_col in enumerate(mapping["BP"][:5]):
                    sheet.cell(row=current_fill_row, column=bp_col).value = ai_data['bp'][i]
                
                current_fill_row += 1

        output = io.BytesIO()
        wb.save(output)
        st.success(f"🎉 填充完畢！共生成 1 行父體與 {len(uploaded_imgs)*len(size_list)} 行子體。")
        st.download_button("💾 下載變體表格 (.xlsm)", output.getvalue(), file_name=f"Bulk_{parent_sku}.xlsm")
