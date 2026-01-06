import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI
from openpyxl.styles import Font

# --- 1. 核心工具：數據清洗 (解決圖 d7cb 佔位符問題) ---
def clean_text(text):
    """清除 JSON 符號、AI 佔位詞及多餘逗號"""
    if not text: return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = {'word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

def format_kw_strict(raw_text):
    """關鍵詞規則：僅空格分隔，限長 245 字符"""
    if not raw_text: return ""
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(raw_text).lower())
    seen, res = set(), []
    for w in clean.split():
        if w not in seen and len(w) > 1:
            res.append(w)
            seen.add(w)
    return " ".join(res)[:245]

# --- 2. 頁面配置與 Key 讀取 (解決圖 96b9 報錯) ---
st.set_page_config(page_title="亞馬遜全能工具 V20", layout="wide")

# 優先從終端 export 的環境變量讀取，解決 Codespaces Secret 報錯
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

if not api_key:
    st.warning("⚠️ 未檢測到 API Key。請在終端執行 export OPENAI_API_KEY='您的Key' 後重啟程序。")

# --- 3. 功能導航 ---
mode = st.sidebar.radio("功能導航", ["批量上架 (圖片分析)", "站點搬運 (US ➔ UK)"])

# ==========================================
# 模式一：批量上架 (鎖定 Row 4 父體)
# ==========================================
if mode == "批量上架 (圖片分析)":
    st.header("🎨 AI 視覺分析上架模塊")
    with st.sidebar:
        st.subheader("⚙️ 規格鎖定")
        brand = st.text_input("品牌名稱", "AMAZING WALL")
        s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
        s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
        s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

    pfx = st.text_input("SKU 前綴 (例: LMX-SDS-DRESS)")
    img_file = st.file_uploader("上傳分析圖", type=['jpg', 'jpeg', 'png'])
    tpl_file = st.file_uploader("上傳 Amazon 1.3MB 模板", type=['xlsx', 'xlsm'], key="tpl_us")

    if st.button("🚀 啟動 AI 填充", type="primary") and img_file and tpl_file and api_key:
        try:
            # 讀取圖片並調用 AI
            img_file.seek(0)
            b64 = base64.b64encode(img_file.read()).decode('utf-8')
            client = OpenAI(api_key=api_key)
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                response_format={"type":"json_object"}
            )
            ai = json.loads(res.choices[0].message.content)
            
            # 處理 Excel (解決圖 506e 內存報錯)
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb.active
            # 建立列名映射
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            
            # 核心邏輯：Row 4 鎖定為父體，解決圖 74ef 紅框缺失
            p_sku = f"{pfx}-001-003"
            rows_data = [
                {"type": "P", "sku": p_sku, "sz": "", "pr": ""},
                {"type": "C", "sku": f"{pfx}-001", "sz": s1, "pr": p1},
                {"type": "C", "sku": f"{pfx}-002", "sz": s2, "pr": p2},
                {"type": "C", "sku": f"{pfx}-003", "sz": s3, "pr": p3}
            ]

            curr_child_row = 5
            for r_info in rows_data:
                target_row = 4 if r_info["type"] == "P" else curr_child_row
                
                def fill(k, v):
                    col_indices = [idx for name, idx in h.items() if k.lower().replace(" ", "") in name]
                    if col_indices: sheet.cell(row=target_row, column=col_indices[0], value=clean_text(v))

                fill("sellersku", r_info["sku"])
                fill("parentsku", p_sku)
                
                if r_info["type"] == "C":
                    cv = f"{ai.get('color','')} {ai.get('elements','')}"
                    fill("color", cv)
                    fill("colormap", cv) # 鏡像同步
                    fill("size", r_info["sz"])
                    fill("sizemap", r_info["sz"])
                    fill("standardprice", r_info["pr"])
                    curr_child_row += 1

                fill("productname", f"{brand} {ai.get('title','')} {ai.get('elements','')}"[:199])
                fill("generickeyword", format_kw_strict(f"{ai.get('elements','')}"))
                for bi in range(5):
                    fill(f"keyproductfeatures{bi+1}", ai['bp'][bi] if bi < len(ai['bp']) else "")

            # 導出文件
            out = io.BytesIO()
            wb.save(out)
            st.success("✅ AI 填充完成！")
            st.download_button("💾 下載美國站上架文件", out.getvalue(), f"{pfx}_US.xlsm")
        except Exception as e:
            st.error(f"❌ 執行出錯: {e}")

# ==========================================
# 模式二：站點搬運 (極簡對位方案，解決圖 ba77 報錯)
# ==========================================
elif mode == "站點搬運 (US ➔ UK)":
    st.header("🌍 跨站點極簡搬運 (US ➔ UK)")
    st.info("系統會自動識別相同列名進行搬運，並適應英式拼寫。")
    
    us_data = st.file_uploader("📂 1. 上傳已填好的 US 文件")
    uk_tpl = st.file_uploader("📂 2. 上傳空白 UK 模板")

    if st.button("🚀 執行自動搬運", type="primary") and us_data and uk_tpl:
        try:
            us_df = pd.read_excel(us_data, header=2)
            uk_wb = openpyxl.load_workbook(uk_tpl, keep_vba=True)
            uk_sheet = uk_wb.active
            uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[3] if c.value}

            # 字段自動適配
            mapping = {"generickeywords": "searchterms", "productname": "itemname", "color": "colour", "colormap": "colourmap"}

            for col in us_df.columns:
                src_n = str(col).strip().lower().replace(" ", "")
                tgt_n = mapping.get(src_n, src_n)
                
                if tgt_n in uk_h:
                    col_idx = uk_h[tgt_n]
                    for r_idx, val in enumerate(us_df[col], start=4):
                        uk_sheet.cell(row=r_idx, column=col_idx, value=clean_text(val))

            out_uk = io.BytesIO()
            uk_wb.save(out_uk)
            st.success("✅ 站點搬運成功！")
            st.download_button("💾 下載英國站轉換文件", out_uk.getvalue(), "Amazon_UK_Result.xlsm")
        except Exception as e:
            st.error(f"❌ 搬運失敗: {e}")
