import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# 1. 核心工具：極速清洗
def clean_text(text):
    if pd.isna(text) or text == "": return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = {'word1', 'word2', 'fake', 'placeholder'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# 2. 頁面配置 (優先讀取 Codespaces 注入的 Key)
st.set_page_config(page_title="亞馬遜全能工具 V22", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

mode = st.sidebar.radio("功能導航", ["批量上架 (圖片分析)", "站點搬運 (US ➔ UK)"])

if mode == "批量上架 (圖片分析)":
    st.header("🎨 AI 視覺分析上架")
    brand = st.sidebar.text_input("品牌", "AMAZING WALL")
    pfx = st.text_input("SKU 前綴")
    img_file = st.file_uploader("分析圖")
    tpl_file = st.file_uploader("Amazon 模板", key="tpl_us")

    if st.button("🚀 啟動填充", type="primary") and img_file and tpl_file and api_key:
        with st.spinner('AI 正在分析並寫入大模板...'):
            try:
                img_file.seek(0)
                b64 = base64.b64encode(img_file.read()).decode('utf-8')
                client = OpenAI(api_key=api_key)
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
                sheet = wb.active
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
                
                p_sku = f"{pfx}-001-003"
                rows = [{"t":"P","s":p_sku},{"t":"C","s":f"{pfx}-001"},{"t":"C","s":f"{pfx}-002"},{"t":"C","s":f"{pfx}-003"}]

                for i, r_d in enumerate(rows):
                    target_row = 4 + i
                    def fill(k, v):
                        col = [idx for name, idx in h.items() if k.lower().replace(" ", "") in name]
                        if col: sheet.cell(row=target_row, column=col[0], value=clean_text(v))
                    
                    fill("sellersku", r_d["s"])
                    fill("parentsku", p_sku)
                    if r_d["t"] == "C":
                        cv = f"{ai.get('color','')} {ai.get('elements','')}"
                        fill("color", cv); fill("colormap", cv)
                    fill("productname", f"{brand} {ai.get('title','')} {ai.get('elements','')}"[:199])
                    for bi in range(5): fill(f"keyproductfeatures{bi+1}", ai['bp'][bi] if bi < len(ai['bp']) else "")

                out = io.BytesIO()
                wb.save(out)
                st.success("✅ 填充完成！")
                st.download_button("💾 下載結果", out.getvalue(), f"{pfx}_Result.xlsm")
            except Exception as e: st.error(f"❌ 錯誤: {e}")

elif mode == "站點搬運 (US ➔ UK)":
    st.header("🌍 跨站點極簡搬運")
    us_data = st.file_uploader("📂 上傳 US 文件")
    uk_tpl = st.file_uploader("📂 上傳 UK 模板")

    if st.button("🚀 執行自動搬運", type="primary") and us_data and uk_tpl:
        with st.spinner('正在極速搬運數據...'):
            try:
                # 改用 pandas 引擎秒讀 1.4MB 文件
                us_df = pd.read_excel(us_data, header=2) 
                uk_wb = openpyxl.load_workbook(uk_tpl, keep_vba=True)
                uk_sheet = uk_wb.active
                uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[3] if c.value}
                
                mapping = {"generickeywords": "searchterms", "productname": "itemname", "color": "colour"}
                
                for col in us_df.columns:
                    src_n = str(col).strip().lower().replace(" ", "")
                    tgt_n = mapping.get(src_n, src_n)
                    if tgt_n in uk_h:
                        col_idx = uk_h[tgt_n]
                        data_to_write = us_df[col].tolist()
                        for r_idx, val in enumerate(data_to_write, start=4):
                            uk_sheet.cell(row=r_idx, column=col_idx, value=clean_text(val))

                out_uk = io.BytesIO()
                uk_wb.save(out_uk)
                st.success("✅ 搬運完成！")
                st.download_button("💾 下載英國站文件", out_uk.getvalue(), "Amazon_UK.xlsm")
            except Exception as e: st.error(f"❌ 失敗: {e}")
