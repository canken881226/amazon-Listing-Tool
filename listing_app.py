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
st.set_page_config(page_title="亞馬遜 AI 上架工具 V5.2", layout="wide")

# 安全讀取 Secrets
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 後台固化的專業寫作邏輯 (Hardcoded Rules) ---
#
SYSTEM_LOGIC = """
你是一位擁有10年經驗的亞馬遜精細化運營專家，精通 A9/COSMO 算法與 Rufus 生成式導購推薦邏輯。
請嚴格遵守以下『放置規劃 (Slot Plan)』撰寫文案：

1. 標題: 前 80 字符放『類目詞 + 核心賣點』。不可堆砌關鍵詞，不可包含品牌名。
2. Bullet 1 (性能): 強調功能詞(如 peel and stick)與使用感受。
3. Bullet 2 (版型/結構): 強調結構詞(如 3D effect)與視覺效果。
4. Bullet 3 (材質): 突出材質(如 vinyl)及其特性(防水/耐用)。
5. Bullet 4 (場景/人群): 描述適用場景(如 office/bedroom/hallway)。
6. Bullet 5 (規格/維護): 強調安裝簡單與尺寸多樣性。
7. Description: 必須包含 HTML 標籤(<b>, <br>)。補充同義詞與長尾短語，採用『問題→解決→場景』邏輯。
8. 禁忌: 嚴禁使用 Best, Top, 100% 等誇大詞彙。語言需自然流暢，符合 Rufus 偏好。
"""

# --- 3. 側邊欄：模板管理 ---
with st.sidebar:
    st.header("📂 模板配置")
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path): os.makedirs(t_path)
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇官方模板", all_tpls if all_tpls else ["⚠️ 請上傳模板"])
    if not api_key:
        api_key = st.text_input("🔑 API Key", type="password")

# --- 4. 輔助函數 ---
def process_and_encode_img(file):
    """縮小圖片提升傳輸速度"""
    img = Image.open(file)
    if max(img.size) > 1200:
        img.thumbnail((1200, 1200))
    buffered = io.BytesIO()
    img.convert("RGB").save(buffered, format="JPEG", quality=75)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def call_ai_vision(img_file, sku_prefix, user_keywords):
    """調用 AI，結合後台邏輯與用戶輸入的關鍵詞"""
    client = OpenAI(api_key=api_key)
    b64 = process_and_encode_img(img_file)
    
    # 組合最終 Prompt：後台邏輯 + 用戶動態關鍵詞
    final_prompt = f"{SYSTEM_LOGIC}\n\nSKU:{sku_prefix}\n用戶提供關鍵詞:\n{user_keywords}\n\n請分析圖中圖案並返回 JSON: {{'title':'', 'desc':'', 'bp':['','','','',''], 'keywords':'', 'color':''}}"
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": final_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]}],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)

# --- 5. 主界面 ---
st.title("🤖 亞馬遜 AI 智能上架工具 V5.2")

st.subheader("📏 子變體尺寸設定")
size_input = st.text_input("輸入尺寸 (用英文逗號隔開)", value='16x24", 24x32", 24x48"')
size_list = [s.strip() for s in size_input.split(",") if s.strip()]

col_img, col_cmd = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上傳圖案 (文件名即為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_cmd:
    user_keywords = st.text_area("📝 填入此款式的關鍵詞組", placeholder="請粘貼您的 I-V 類關鍵詞...", height=200)

# --- 6. 執行填充 ---
if st.button("🚀 啟動 AI 識別並填充原表", use_container_width=True):
    if not uploaded_imgs or not api_key:
        st.error("❌ 缺少圖片或 API Key")
    else:
        try:
            wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
            sheet = wb.active
            headers = {cell.value: cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
            
            img_prefixes = [os.path.splitext(img.name)[0] for img in uploaded_imgs]
            parent_sku = f"{img_prefixes[0]}-{img_prefixes[-1].split('-')[-1]}" if len(img_prefixes) > 1 else img_prefixes[0]
            
            # 填充父體
            if headers.get("Seller SKU"): sheet.cell(row=4, column=headers["Seller SKU"]).value = parent_sku
            if headers.get("Parentage"): sheet.cell(row=4, column=headers["Parentage"]).value = "parent"

            current_row = 5
            t = datetime.now()
            s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
            
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, img in enumerate(uploaded_imgs):
                prefix = os.path.splitext(img.name)[0]
                status_text.info(f"⏳ 正在分析第 {i+1}/{len(uploaded_imgs)} 款: **{prefix}**")
                
                # AI 自動套用後台系統邏輯與您的動態詞組
                ai_data = call_ai_vision(img, prefix, user_keywords)
                
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

            status_text.success("🎉 全部完成！")
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            
            st.download_button(
                label="💾 立即下載填充好的官方原表 (.xlsm)",
                data=output.getvalue(),
                file_name=f"Listing_{parent_sku}.xlsm",
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"❌ 發生錯誤: {str(e)}")
