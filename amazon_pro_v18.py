import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：格式與數據清洗 ---
def clean_text(text):
    """徹底清除雜質，確保數據乾淨"""
    if pd.isna(text) or text == "": return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = {'word1', 'word2', 'fake', 'placeholder'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# --- 2. 智能表頭定位工具 ---
def find_header_row(file, sheet_name='Template'):
    """自動掃描前 10 行，尋找包含 'sku' 或 'item' 的表頭行"""
    df_preview = pd.read_excel(file, sheet_name=sheet_name, nrows=10, header=None)
    for i, row in df_preview.iterrows():
        row_str = " ".join([str(x).lower() for x in row.values])
        if 'sku' in row_str or 'item' in row_str or 'product' in row_str:
            return i
    return 2 # 默認第 3 行

# --- 3. 頁面配置 ---
st.set_page_config(page_title="亞馬遜全能工具 V25.0", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

mode = st.sidebar.radio("功能選擇", ["批量上架 (圖片分析)", "站點搬運 (US ➔ UK)"])

# ==========================================
# 模式一：批量上架 (核心邏輯不變)
# ==========================================
if mode == "批量上架 (圖片分析)":
    st.header("🎨 AI 視覺分析上架")
    brand = st.sidebar.text_input("品牌名稱", "AMAZING WALL")
    pfx = st.text_input("SKU 前綴")
    img_file = st.file_uploader("上傳分析圖")
    tpl_file = st.file_uploader("上傳模板", key="tpl_us")

    if st.button("🚀 啟動 AI 填充") and img_file and tpl_file and api_key:
        with st.spinner('正在分析並寫入...'):
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
                sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
                
                # 自動找表頭行
                header_idx = 3 # 默認 openpyxl 從 1 開始計數
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in sheet[header_idx] if c.value}
                
                p_sku = f"{pfx}-001-003"
                rows = [{"t":"P","s":p_sku},{"t":"C","s":f"{pfx}-001"},{"t":"C","s":f"{pfx}-002"},{"t":"C","s":f"{pfx}-003"}]
                for i, r in enumerate(rows):
                    target_row = header_idx + 1 + i
                    def fill(k, v):
                        col = [idx for name, idx in h.items() if k.lower().replace(" ", "") in name]
                        if col: sheet.cell(row=target_row, column=col[0], value=clean_text(v))
                    fill("sellersku", r["s"])
                    fill("parentsku", p_sku)
                    fill("productname", f"{brand} {ai.get('title','')} {ai.get('elements','')}"[:199])
                
                out = io.BytesIO()
                wb.save(out)
                st.download_button("💾 下載結果", out.getvalue(), "Amazon_US_Result.xlsm")
            except Exception as e: st.error(f"❌ 錯誤: {e}")

# ==========================================
# 模式二：站點搬運 (智能對位版)
# ==========================================
elif mode == "站點搬運 (US ➔ UK)":
    st.header("🌍 跨站點智能搬運 (US ➔ UK)")
    us_data = st.file_uploader("📂 1. 上傳 US 文件")
    uk_tpl = st.file_uploader("📂 2. 上傳 UK 模板")

    if st.button("🚀 執行智能搬運") and us_data and uk_tpl:
        with st.spinner('正在同步數據...'):
            try:
                # 1. 讀取 US 的 Template 數據 (自動找表頭)
                us_xl = pd.ExcelFile(us_data)
                us_sheet = 'Template' if 'Template' in us_xl.sheet_names else us_xl.sheet_names[0]
                us_header_row = find_header_row(us_data, us_sheet)
                us_df = pd.read_excel(us_data, sheet_name=us_sheet, header=us_header_row) 

                # 2. 定位 UK 模板的 Template 表
                uk_wb = openpyxl.load_workbook(uk_tpl, keep_vba=True)
                uk_sheet = uk_wb['Template'] if 'Template' in uk_wb.sheetnames else uk_wb.active
                
                # 3. 獲取 UK 模板表頭
                uk_header_row_idx = us_header_row + 1 # 假設 UK 模板結構與 US 類似
                uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[uk_header_row_idx] if c.value}

                # 4. 強制映射關鍵字段
                mapping = {
                    "productname": "itemname", 
                    "generickeywords": "searchterms",
                    "color": "colour", 
                    "colormap": "colourmap"
                }

                # 5. 執行對位搬運
                for col in us_df.columns:
                    src_n = str(col).strip().lower().replace(" ", "")
                    tgt_n = mapping.get(src_n, src_n)
                    
                    if tgt_n in uk_h:
                        col_idx = uk_h[tgt_n]
                        vals = us_df[col].tolist()
                        for r_idx, val in enumerate(vals, start=uk_header_row_idx + 1):
                            uk_sheet.cell(row=r_idx, column=col_idx, value=clean_text(val))

                out_uk = io.BytesIO()
                uk_wb.save(out_uk)
                st.success("✅ 搬運成功！數據已精準填入 UK Template 表。")
                st.download_button("💾 下載 UK 表格", out_uk.getvalue(), "Amazon_UK_Final.xlsm")
            except Exception as e: st.error(f"❌ 失敗: {e}")
