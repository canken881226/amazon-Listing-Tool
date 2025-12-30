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
from concurrent.futures import ThreadPoolExecutor

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 極速上架 V6.0", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 固化專業寫作邏輯 ---
SYSTEM_LOGIC = """
你是一位亞馬遜精細化運營專家。標題130字內。Search Terms僅輸出空格分隔的單詞(<240字)。BP分5條。Description含HTML。
"""

# --- 3. 側邊欄 ---
with st.sidebar:
    st.header("📂 系統狀態")
    if api_key: st.success("✅ API 已就緒")
    t_path = os.path.join(os.getcwd(), "templates")
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇模板", all_tpls if all_tpls else ["⚠️ 無模板"])

# --- 4. 輔助函數：圖片處理與 AI 調用 ---
def process_img(file):
    img = Image.open(file)
    img.thumbnail((800, 800)) # 進一步縮小尺寸提升速度
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=60) # 降低品質換取速度
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_task(img_file, sku_prefix, keywords):
    """併發任務單元"""
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img(img_file)
        prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\n關鍵詞:{keywords}\n返回JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
        res = client.chat.completions.create(
            model="gpt-4o-mini", # 改用 4o-mini 速度快 3 倍，成本更低，且足以處理文案
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=30
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except:
        return {"prefix": sku_prefix, "data": {}}

# --- 5. 主界面 ---
st.title("⚡ 亞馬遜 AI 極速填充系統 V6.0")

st.subheader("💰 尺寸價格配置")
default_sp = pd.DataFrame([{"Size": '16x24"', "Price": "9.99"},{"Size": '24x36"', "Price": "16.99"},{"Size": '32x48"', "Price": "18.99"}])
size_price_data = st.data_editor(default_sp, num_rows="dynamic")

col_img, col_kw = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上傳圖片 (SKU前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_kw:
    user_keywords = st.text_area("📝 關鍵詞庫", height=150)

# --- 6. 核心極速填充邏輯 ---
if st.button("🚀 啟動併發極速填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 請上傳圖片")
    else:
        try:
            with st.status("⚡ 正在併發分析圖片並填充...") as status:
                # 1. 併發獲取 AI 數據
                st.write("🏃 多線程同時啟動 AI 分析...")
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(call_ai_task, img, os.path.splitext(img.name)[0], user_keywords) for img in uploaded_imgs]
                    all_results = [f.result() for f in futures]
                
                # 2. 寫入 Excel
                st.write("✍️ 正在將數據同步至 Excel...")
                wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
                sheet = wb.active
                headers = {str(cell.value).strip().lower(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if "key product features" in str(cell.value).lower()]

                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                
                current_row = 5
                
                for idx, res in enumerate(all_results):
                    prefix = res["prefix"]
                    data = res["data"]
                    if not data: continue

                    # 填充父體 (Row 4, 僅限首張圖)
                    if idx == 0:
                        p_sku = f"{prefix}-P"
                        if "seller sku" in headers: sheet.cell(row=4, column=headers["seller sku"]).value = p_sku
                        if "parentage" in headers: sheet.cell(row=4, column=headers["parentage"]).value = "parent"
                        if "product name" in headers: sheet.cell(row=4, column=headers["product name"]).value = data.get('title','')
                        if "product description" in headers: sheet.cell(row=4, column=headers["product description"]).value = data.get('desc','')
                        if "generic keyword" in headers: sheet.cell(row=4, column=headers["generic keyword"]).value = data.get('keywords','')
                        if "color" in headers: sheet.cell(row=4, column=headers["color"]).value = data.get('color','')
                        for b_idx, c_idx in enumerate(bp_cols[:5]):
                            sheet.cell(row=4, column=c_idx).value = data.get('bp',['','','','',''])[b_idx]

                    # 填充子體
                    for _, row_data in size_price_data.iterrows():
                        sz, pr = str(row_data["Size"]), str(row_data["Price"])
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        if "seller sku" in headers: sheet.cell(row=current_row, column=headers["seller sku"]).value = c_sku
                        if "parent sku" in headers: sheet.cell(row=current_row, column=headers["parent sku"]).value = f"{all_results[0]['prefix']}-P"
                        if "parentage" in headers: sheet.cell(row=current_row, column=headers["parentage"]).value = "child"
                        if "product name" in headers: sheet.cell(row=current_row, column=headers["product name"]).value = f"{data.get('title','')} - {sz}"[:150]
                        if "sale price" in headers: sheet.cell(row=current_row, column=headers["sale price"]).value = pr
                        if "size" in headers: sheet.cell(row=current_row, column=headers["size"]).value = sz
                        if "size map" in headers: sheet.cell(row=current_row, column=headers["size map"]).value = sz
                        if "sale start date" in headers: sheet.cell(row=current_row, column=headers["sale start date"]).value = s_start
                        if "sale end date" in headers: sheet.cell(row=current_row, column=headers["sale end date"]).value = s_end
                        if "product description" in headers: sheet.cell(row=current_row, column=headers["product description"]).value = data.get('desc','')
                        if "generic keyword" in headers: sheet.cell(row=current_row, column=headers["generic keyword"]).value = data.get('keywords','')
                        if "color" in headers: sheet.cell(row=current_row, column=headers["color"]).value = data.get('color','')
                        for b_idx, c_idx in enumerate(bp_cols[:5]):
                            sheet.cell(row=current_row, column=c_idx).value = data.get('bp',['','','','',''])[b_idx]
                        current_row += 1
                
                status.update(label="⚡ 極速填充完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載極速生成的表格 (.xlsm)", output.getvalue(), f"Quick_{datetime.now().strftime('%m%d')}.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 錯誤: {e}")
