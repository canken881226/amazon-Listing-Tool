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
st.set_page_config(page_title="亞馬遜 AI 原表填充工具 V4.9", layout="wide")

# 安全讀取 Secrets
api_key = st.secrets.get("OPENAI_API_KEY") or st.sidebar.text_input("🔑 API Key", type="password")

# --- 2. 側邊欄：模板管理 ---
with st.sidebar:
    st.header("📂 模板配置")
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path): os.makedirs(t_path)
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇要填充的官方模板", all_tpls if all_tpls else ["⚠️ 請上傳模板"])

# --- 3. 核心函數 ---
def encode_img(file):
    return base64.b64encode(file.getvalue()).decode('utf-8')

def call_ai_vision(img_file, sku_prefix, instruction):
    """調用 GPT-4o 視覺模型並強制返回結構化 JSON"""
    client = OpenAI(api_key=api_key)
    b64 = encode_img(img_file)
    
    prompt_text = f"""
    你是一個資深亞馬遜運營。產品前綴SKU是: {sku_prefix}。
    請識別圖中的圖案元素、色彩、風格，並嚴格按照以下 JSON 格式返回數據：
    {{
      "title": "標題",
      "desc": "產品描述",
      "bp": ["五點1", "五點2", "五點3", "五點4", "五點5"],
      "keywords": "關鍵詞",
      "color": "圖案詞"
    }}
    要求: {instruction}
    """
    
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
st.title("🤖 亞馬遜 AI 多尺寸填充系統 (V4.9 直下版)")

st.subheader("📏 尺寸配置")
size_input = st.text_input("輸入子變體尺寸 (英文逗號隔開)", value='16x24", 24x32", 24x48"')
size_list = [s.strip() for s in size_input.split(",") if s.strip()]

col_img, col_cmd = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("上傳圖片 (文件名為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_cmd:
    user_instruction = st.text_area("給 AI 的指令", value="請識別圖案元素，生成專業標題、五點、關鍵詞和 Color 圖案詞。", height=150)

# --- 5. 啟動與下載按鈕顯示邏輯 ---
if st.button("🚀 啟動分析並填充模板", use_container_width=True):
    if not uploaded_imgs or not api_key or "請上傳" in selected_tpl:
        st.error("❌ 請檢查配置（圖片、API Key 或模板）")
    else:
        try:
            # 1. 加載模板
            template_full_path = os.path.join(t_path, selected_tpl)
            wb = openpyxl.load_workbook(template_full_path, keep_vba=True)
            sheet = wb.active
            
            # 2. 掃描標題列
            headers = {cell.value: cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
            
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

            # 3. 填充父體行
            img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
            parent_sku = f"{img_prefixes[0]}-{img_prefixes[-1].split('-')[-1]}" if len(img_prefixes) > 1 else img_prefixes[0]
            if mapping["SKU"]: sheet.cell(row=4, column=mapping["SKU"]).value = parent_sku
            if mapping["Parentage"]: sheet.cell(row=4, column=mapping["Parentage"]).value = "parent"

            # 4. 循環 AI 分析與填充
            current_row = 5
            t = datetime.now()
            s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
            
            progress = st.progress(0)
            for i, img in enumerate(uploaded_imgs):
                prefix = os.path.splitext(img.name)[0]
                st.write(f"正在 AI 分析: {prefix}...")
                
                ai_data = call_ai_vision(img, prefix, user_instruction)
                
                for size in size_list:
                    c_sku = f"{prefix}-{size}"
                    # 精確寫入單元格
                    if mapping["SKU"]: sheet.cell(row=current_row, column=mapping["SKU"]).value = c_sku
                    if mapping["ParentSKU"]: sheet.cell(row=current_row, column=mapping["ParentSKU"]).value = parent_sku
                    if mapping["Parentage"]: sheet.cell(row=current_row, column=mapping["Parentage"]).value = "child"
                    if mapping["Size"]: sheet.cell(row=current_row, column=mapping["Size"]).value = size
                    if mapping["Title"]: sheet.cell(row=current_row, column=mapping["Title"]).value = ai_data['title']
                    if mapping["Desc"]: sheet.cell(row=current_row, column=mapping["Desc"]).value = ai_data['desc']
                    if mapping["Color"]: sheet.cell(row=current_row, column=mapping["Color"]).value = ai_data['color']
                    if mapping["KW"]: sheet.cell(row=current_row, column=mapping["KW"]).value = ai_data['keywords']
                    if mapping["Start"]: sheet.cell(row=current_row, column=mapping["Start"]).value = s_start
                    if mapping["End"]: sheet.cell(row=current_row, column=mapping["End"]).value = s_end
                    for bp_idx, bp_col in enumerate(mapping["BP"][:5]):
                        if bp_idx < len(ai_data['bp']):
                            sheet.cell(row=current_row, column=bp_col).value = ai_data['bp'][bp_idx]
                    current_row += 1
                progress.progress((i + 1) / len(uploaded_imgs))

            # 5. 輸出下載按鈕
            output = io.BytesIO()
            wb.save(output)
            output.seek(0) # 關鍵：將指針移回起點確保可讀取數據
            
            st.success("🎉 分析填充完成！文件已準備就緒。")
            st.download_button(
                label="💾 點此立即下載填充好的官方原表 (.xlsm)",
                data=output.getvalue(),
                file_name=f"Bulk_Variation_{parent_sku}.xlsm",
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                use_container_width=True
            )
            # 預覽數據供確認
            st.info("💡 如果下載沒反應，請檢查瀏覽器是否攔截了彈窗。")
            
        except Exception as e:
            st.error(f"❌ 嚴重錯誤: {str(e)}")
