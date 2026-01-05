import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl
from openai import OpenAI
from openpyxl.styles import Font, Alignment

# --- 1. 核心安全工具 (物理隔離佔位詞，解決圖 7d03/7b01 問題) ---
def safe_clean_final(text):
    if not text: return ""
    # 物理剔除 JSON 符號和 AI 佔位詞
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = ['word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich', 'title']
    words = text.split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# --- 2. 頁面強制重置配置 ---
st.set_page_config(page_title="亞馬遜 V11.8 終極穩定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 3. 側邊欄：規格鎖定 ---
with st.sidebar:
    st.header("⚙️ 規格鎖定配置")
    brand = st.text_input("品牌名稱", value="AMAZING WALL")
    st.divider()
    # 恢復您確認的尺寸與價格介面
    s1, p1, n1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99"), "001"
    s2, p2, n2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99"), "002"
    s3, p3, n3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99"), "003"

# --- 4. 款式錄入 (使用唯一 Key 解決圖 f201 死鎖) ---
st.header("🖼️ 款式錄入矩陣 (V11.8)")
if 'total_rows' not in st.session_state: st.session_state.total_rows = 1

sku_data_list = []
for i in range(st.session_state.total_rows):
    with st.expander(f"款式 {i+1}", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            pfx = st.text_input("SKU 前綴", key=f"pfx_v118_{i}") # 使用新 Key 强制重置组件
            img = st.file_uploader("分析圖 (必傳)", key=f"img_v118_{i}")
        with c2:
            m_u = st.text_input("主圖 URL", key=f"mu_v118_{i}")
            o_u = st.text_area("附圖集 (一行一個)", key=f"ou_v118_{i}")
        with c3:
            u1 = st.text_input(f"{s1} 圖片", key=f"u1_v118_{i}")
            u2 = st.text_input(f"{s2} 圖片", key=f"u2_v118_{i}")
            u3 = st.text_input(f"{s3} 圖片", key=f"u3_v118_{i}")
        sku_data_list.append({"pfx": pfx, "img": img, "main": m_u, "sz_urls": [u1, u2, u3]})

if st.button("➕ 增加新款式"):
    st.session_state.total_rows += 1
    st.rerun()

user_keywords = st.text_area("通用詞庫 (Search Terms)")
# 增加 Key，防止模板讀取死鎖
uploaded_template = st.file_uploader("📂 第一步：上傳 Amazon 模板", type=['xlsx', 'xlsm'], key="tpl_v118")

# --- 5. 核心執行邏輯 (鎖定第一行與子類 SKU) ---
if st.button("🚀 啟動自動化填充 (物理重置版)", type="primary", key="run_v118"):
    if not uploaded_template or not api_key:
        st.error("❌ 啟動失敗：請確保已上傳模板並配置 API Key")
    else:
        try:
            status_log = st.empty()
            status_log.info("⏳ 正在讀取模板表頭...")
            
            # 解決 FileNotFoundError：直接從內存加載
            wb = openpyxl.load_workbook(uploaded_template, keep_vba=True)
            sheet = wb.active
            # 建立表頭索引
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            bp_cols = [c.column for r in sheet.iter_rows(max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]
            
            client = OpenAI(api_key=api_key)
            current_write_row = 5 # 子類從第 5 行開始

            for idx, item in enumerate(sku_data_list):
                if not item["pfx"] or not item["img"]:
                    continue
                
                status_log.info(f"⏳ 正在分析款式 {idx+1}: {item['pfx']}...")
                
                # 圖像重置指針，解決圖 5c2b 的 'file' 報錯
                item["img"].seek(0)
                b64_img = base64.b64encode(item["img"].read()).decode('utf-8')
                
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64_img}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai_data = json.loads(res.choices[0].message.content)

                # 規則鎖定：Parent SKU 範圍命名
                parent_sku = f"{item['pfx']}-{n1}-{n3}"
                
                # 定義 1 父 + 3 子 結構，解決圖 c9d4/0976 SKU 混亂
                rows_to_process = [
                    {"type": "P", "sku": parent_sku, "sz": "", "pr": "", "id": -1},
                    {"type": "C", "sku": f"{item['pfx']}-{n1}", "sz": s1, "pr": p1, "id": 0},
                    {"type": "C", "sku": f"{item['pfx']}-{n2}", "sz": s2, "pr": p2, "id": 1},
                    {"type": "C", "sku": f"{item['pfx']}-{n3}", "sz": s3, "pr": p3, "id": 2}
                ]

                for r in rows_to_process:
                    # 鎖定：父體行永遠寫在第 4 行 (Row 4)，解決圖 c9d4 紅框缺失
                    target_row = 4 if r["type"] == "P" else current_write_row
                    
                    def fill_sheet(key_name, val_content):
                        match_cols = [col_idx for name, col_idx in h.items() if key_name.lower().replace(" ", "") in name]
                        if match_cols:
                            cell = sheet.cell(row=target_row, column=match_cols[0], value=safe_clean_final(val_content))
                            cell.font = Font(name='Arial', size=10)
                            cell.alignment = Alignment(wrap_text=True, vertical='top')

                    # 1. 強制寫入 Seller SKU
                    fill_sheet("sellersku", r["sku"])
                    fill_sheet("parentsku", parent_sku)
                    
                    # 2. 屬性鏡像鎖定 (ColorMap = Color)，解決圖 71d5 缺失
                    if r["type"] == "C":
                        full_color_desc = f"{ai_data.get('color','')} {ai_data.get('elements','')}"
                        fill_sheet("color", full_color_desc)
                        fill_sheet("colormap", full_color_desc)
                        fill_sheet("size", r["sz"])
                        fill_sheet("sizemap", r["sz"])
                        fill_sheet("standardprice", r["pr"])

                    # 3. 標題與文案 (自動補齊 5 點，解決圖 285b 缺失)
                    title_full = f"{brand} {ai_data.get('title','')} {ai_data.get('elements','')}"
                    if r["type"] == "C": title_full += f" - {r['sz']}"
                    fill_sheet("productname", title_full[:199])
                    
                    # 4. 關鍵詞格式化，解決圖 7d03 佔位詞
                    fill_sheet("generickeyword", safe_clean_final(f"{ai_data.get('elements','')} {user_keywords}"))

                    # 5. 五點描述 (所有行必填)
                    ai_bps = ai_data.get('bp', [])
                    while len(ai_bps) < 5: ai_bps.append("High-quality professional print.")
                    for b_i, b_col in enumerate(bp_cols[:5]):
                        sheet.cell(row=target_row, column=b_col, value=safe_clean_final(ai_bps[b_i]))

                    if r["type"] == "C": current_write_row += 1

            status_log.success("✅ 全部處理完成！請下載文件。")
            output_stream = io.BytesIO()
            wb.save(output_stream)
            st.download_button("💾 下載 V11.8 終極鎖定版", output_stream.getvalue(), "Amazon_V11.8_Final.xlsm")

        except Exception as e:
            st.error(f"❌ 程序報錯：{str(e)}")
