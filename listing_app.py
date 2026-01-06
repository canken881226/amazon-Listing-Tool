import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl
from openai import OpenAI

# --- 1. 核心工具：格式與清洗 ---
def clean_text(text):
    if not text: return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = {'word1', 'word2', 'fake', 'placeholder'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# --- 2. 頁面重置與導航 ---
st.set_page_config(page_title="亞馬遜極簡版 V17.0", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

mode = st.sidebar.radio("功能選擇", ["批量上架 (圖片分析)", "站點搬運 (US ➔ UK)"])

# ==========================================
# 模式一：批量上架 (保持所有確定好的規則)
# ==========================================
if mode == "批量上架 (圖片分析)":
    st.header("🎨 AI 視覺分析上架")
    with st.sidebar:
        brand = st.text_input("品牌", "AMAZING WALL")
        s1, p1 = st.text_input("尺寸1", "16x24\""), st.text_input("價格1", "12.99")
        s2, p2 = st.text_input("尺寸2", "24x36\""), st.text_input("價格2", "16.99")
        s3, p3 = st.text_input("尺寸3", "32x48\""), st.text_input("價格3", "19.99")

    pfx = st.text_input("SKU 前綴 (例: SQDQ-BH-087)")
    img = st.file_uploader("上傳分析圖")
    tpl = st.file_uploader("上傳 Amazon 模板", key="tpl_up")

    if st.button("🚀 啟動填充") and img and tpl and api_key:
        try:
            img.seek(0)
            b64 = base64.b64encode(img.read()).decode('utf-8')
            client = OpenAI(api_key=api_key)
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                response_format={"type":"json_object"}
            )
            ai = json.loads(res.choices[0].message.content)
            
            wb = openpyxl.load_workbook(tpl, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in sheet[3] if c.value}
            
            # 規則鎖定：Row 4 父體, Row 5-7 子體
            p_sku = f"{pfx}-001-003"
            rows = [
                {"t":"P", "s":p_sku, "sz":"", "pr":""},
                {"t":"C", "s":f"{pfx}-001", "sz":s1, "pr":p1},
                {"t":"C", "s":f"{pfx}-002", "sz":s2, "pr":p2},
                {"t":"C", "s":f"{pfx}-003", "sz":s3, "pr":p3}
            ]

            for i, r in enumerate(rows):
                target_row = 4 + i
                def fill(k, v):
                    col = h.get(k.lower().replace(" ", ""))
                    if col: sheet.cell(row=target_row, column=col, value=clean_text(v))

                fill("sellersku", r["s"])
                fill("parentsku", p_sku)
                if r["t"] == "C":
                    fill("color", f"{ai['color']} {ai['elements']}")
                    fill("colormap", f"{ai['color']} {ai['elements']}")
                    fill("size", r["sz"])
                    fill("sizemap", r["sz"])
                    fill("standardprice", r["pr"])
                fill("productname", f"{brand} {ai['title']} {ai['elements']}"[:199])
                for bi in range(5): fill(f"keyproductfeatures{bi+1}", ai['bp'][bi])

            out = io.BytesIO()
            wb.save(out)
            st.download_button("💾 下載上架文件", out.getvalue(), "Amazon_US.xlsm")
        except Exception as e: st.error(f"報錯: {e}")

# ==========================================
# 模式二：站點搬運 (極簡全表對位方案)
# ==========================================
elif mode == "站點搬運 (US ➔ UK)":
    st.header("🌍 跨站點極簡搬運")
    st.write("只要列名一致，數據就會自動對位搬運。")
    
    us_file = st.file_uploader("📂 1. 上傳已填好的 US 文件", type=['xlsx', 'xlsm'])
    uk_tpl = st.file_uploader("📂 2. 上傳空白 UK 模板", type=['xlsx', 'xlsm'])

    if st.button("🚀 執行自動搬運") and us_file and uk_tpl:
        try:
            # 使用 Pandas 讀取 US 數據
            us_df = pd.read_excel(us_file, header=2) # 假設第3行是表頭
            
            # 使用 openpyxl 保持 UK 模板格式和宏
            uk_wb = openpyxl.load_workbook(uk_tpl, keep_vba=True)
            uk_sheet = uk_wb.active
            uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[3] if c.value}

            # 核心簡潔邏輯：遍歷 US 的列名，如果在 UK 也能找到，就搬運
            for col_name in us_df.columns:
                clean_name = str(col_name).strip().lower().replace(" ", "")
                # 處理名字不完全一致但意思一樣的字段
                mapping = {"generickeywords": "searchterms", "productname": "itemname", "color": "colour"}
                target_name = mapping.get(clean_name, clean_name)
                
                if target_name in uk_h:
                    uk_col_idx = uk_h[target_name]
                    # 搬運該列所有數據
                    for row_idx, value in enumerate(us_df[col_name], start=4):
                        uk_sheet.cell(row=row_idx, column=uk_col_idx, value=clean_text(value))

            out_uk = io.BytesIO()
            uk_wb.save(out_uk)
            st.success("✅ 搬運完成！已自動適應 Search Terms 和 Colour 等拼寫。")
            st.download_button("💾 下載英國站文件", out_uk.getvalue(), "Amazon_UK.xlsm")
        except Exception as e: st.error(f"搬運出錯: {e}")
