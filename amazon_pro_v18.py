import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：格式與數據清洗 (解決圖 d7cb 佔位符) ---
def clean_text(text):
    """徹底清除 JSON 符號、AI 佔位詞及雜質"""
    if pd.isna(text) or str(text).strip() == "": return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    # 過濾常見 AI 廢話
    blacklist = {'word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

def format_kw(raw_text):
    """關鍵詞規則：僅空格分隔，限長 245 字符"""
    if not raw_text: return ""
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(raw_text).lower())
    seen, res = set(), []
    for w in clean.split():
        if w not in seen and len(w) > 1:
            res.append(w); seen.add(w)
    return " ".join(res)[:245]

# --- 2. 頁面配置與 Key 讀取 (解決圖 96b9 報錯) ---
st.set_page_config(page_title="亞馬遜 AI 上架助手 V29", layout="wide")

# 優先讀取 Codespaces 終端注入的環境變量
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🎨 亞馬遜 AI 批量上架系統")
st.info("💡 當前版本：專注於美國站圖片分析與 Template 自動填充。搬運任務請交由 ChatGPT 處理。")

# --- 3. 側邊欄：規格鎖定 ---
with st.sidebar:
    st.header("⚙️ 規格鎖定")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 主界面：數據輸入 (優化佈局) ---
c1, c2 = st.columns(2)
with c1:
    pfx = st.text_input("SKU 前綴 (例如: LMX-SDS-01)")
    img_file = st.file_uploader("🖼️ 上傳分析圖 (AI 將根據此圖生成描述)", type=['jpg', 'png', 'jpeg'])
with c2:
    tpl_file = st.file_uploader("📂 上傳 Amazon 美國站模板 (1.4MB 限制已優化)", type=['xlsx', 'xlsm'])

# --- 5. 核心執行邏輯 ---
if st.button("🚀 啟動 AI 分析並填充表格", type="primary"):
    if not (pfx and img_file and tpl_file and api_key):
        st.error("❌ 請檢查：SKU 前綴、圖片、模板文件以及 API Key 是否都已準備就緒。")
    else:
        # 使用 spinner 提示用戶程序正在運行，防止點擊沒反應
        with st.spinner('AI 正在分析圖片並寫入 Template 子表...'):
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
                
                # 加載 Excel 並鎖定 Template 子表
                wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
                sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
                
                # 智能列名對位 (自動掃描前 5 行)
                h = {}
                for r in range(1, 6):
                    for c in range(1, sheet.max_column + 1):
                        v = str(sheet.cell(row=r, column=c).value).lower().replace(" ", "").replace("_", "")
                        if v and v != "none": h[v] = c
                
                # 1父 3子數據準備：鎖定 Row 4 為父體
                p_sku = f"{pfx}-001-003"
                rows_config = [
                    {"t":"P", "s":p_sku, "sz":"", "pr":""},
                    {"t":"C", "s":f"{pfx}-001", "sz":s1, "pr":p1},
                    {"t":"C", "s":f"{pfx}-002", "sz":s2, "pr":p2},
                    {"t":"C", "s":f"{pfx}-003", "sz":s3, "pr":p3}
                ]

                # 循環寫入數據
                for i, r_info in enumerate(rows_config):
                    curr_row = 4 + i
                    def fill(key, value):
                        # 模糊匹配列名
                        col_idx = [idx for name, idx in h.items() if key.lower().replace(" ", "").replace("_", "") in name]
                        if col_idx: sheet.cell(row=curr_row, column=col_idx[0], value=clean_text(value))

                    fill("sellersku", r_info["s"])
                    fill("parentsku", p_sku)
                    if r_info["t"] == "C":
                        fill("standardprice", r_info["pr"])
                        fill("size", r_info["sz"])
                        color_val = f"{ai.get('color','')} {ai.get('elements','')}"
                        fill("color", color_val)
                        fill("colormap", color_val)
                    
                    fill("productname", f"{brand} {ai.get('title','')} {ai.get('elements','')}"[:199])
                    fill("generickeyword", format_kw(ai.get('elements','')))
                    for bi in range(5):
                        fill(f"keyproductfeatures{bi+1}", ai['bp'][bi] if bi < len(ai['bp']) else "")

                # 導出文件
                out = io.BytesIO()
                wb.save(out)
                st.success("✅ AI 填充完成！")
                st.download_button("💾 下載美國站上架文件", out.getvalue(), f"{pfx}_US_Upload.xlsm")
                
            except Exception as e:
                st.error(f"❌ 執行出錯：{str(e)}")
