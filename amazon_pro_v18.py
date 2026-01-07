import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI
from datetime import datetime, timedelta

# --- 1. 核心工具 ---
def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    return re.sub(r"[\[\]'\"']", "", str(text)).strip()

def format_amazon_kw(elements, global_kws):
    """關鍵詞邏輯：圖案元素詞 + 通用詞，空格分隔"""
    all_words = f"{elements} {global_kws}".replace(",", " ").replace(";", " ").split()
    seen = set()
    res = [w.lower() for w in all_words if not (w.lower() in seen or seen.add(w.lower()))]
    return " ".join(res)[:245]

# --- 2. 頁面配置 ---
st.set_page_config(page_title="亞馬遜專家 V39", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架系統 V39")
st.info("✅ 已優化列名匹配邏輯，解決『填寫空白』與『int 報錯』問題。")

# --- 3. 運營配置 (側邊欄) ---
with st.sidebar:
    st.header("📢 運營配置")
    global_kws = st.text_area("✨ 全局關鍵詞", "canvas art, wall decor")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 款式管理 ---
if 'v39_rows' not in st.session_state: st.session_state.v39_rows = 1
sku_items = []
for i in range(st.session_state.v39_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 1.5])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with c3: o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v39_rows += 1
    st.rerun()

tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行生成 ---
if st.button("🚀 執行合規填充", type="primary") and tpl_file and api_key:
    with st.spinner('正在分析並精準定位列名...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            
            # --- 強化的列名掃描 (解決空白問題) ---
            h = {}
            for r_idx in range(1, 6): # 掃描前5行
                for cell in sheet[r_idx]:
                    if cell.value:
                        # 將列名處理為純小寫字母，移除所有符號
                        clean_n = re.sub(r'[^a-z0-9]', '', str(cell.value).lower())
                        if clean_n: h[clean_n] = cell.column
            
            # 促銷時間
            start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            end_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            
            client = OpenAI(api_key=api_key)
            row_cursor = 4

            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                # Slot Plan Prompt
                prompt = f"""Act as Amazon SEO Expert. Keywords: [{global_kws}].
                Output JSON: {{ "title":"", "elements":"", "bp":["5 items"], "desc":"HTML" }}
                Narrative: Problem->Solution->Scene.
                """
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                p_sku = f"{item['pfx']}-P"
                rows_cfg = [
                    {"t":"P","s":p_sku,"sz":"","pr":""},
                    {"t":"C","s":f"{item['pfx']}-{s1}","sz":s1,"pr":p1},
                    {"t":"C","s":f"{item['pfx']}-{s2}","sz":s2,"pr":p2},
                    {"t":"C","s":f"{item['pfx']}-{s3}","sz":s3,"pr":p3}
                ]
                
                for r in rows_cfg:
                    def fill(k_list, v):
                        """嘗試多個可能的列名關鍵詞"""
                        for k in k_list:
                            c_idx = h.get(re.sub(r'[^a-z0-9]', '', k.lower()))
                            if c_idx: 
                                sheet.cell(row=row_cursor, column=c_idx, value=clean_text(v))
                                break

                    fill(["sellersku", "sku"], r["s"])
                    
                    if r["t"] == "C":
                        # 子體邏輯
                        fill(["parentsku"], p_sku) 
                        fill(["productname", "itemname"], f"{brand} {ai['title']} {ai['elements']} - {r['sz']}")
                        fill(["color", "colour"], ai['elements'])
                        fill(["colormap", "colourmap"], ai['elements'])
                        fill(["size", "itemsize"], r['sz'])
                        fill(["sizemap"], r['sz'])
                        fill(["standardprice"], r['pr'])
                        fill(["salestartdate"], start_date)
                        fill(["saleenddate"], end_date)
                        fill(["mainimageurl"], item["main"])
                        for idx, o_url in enumerate(item["others"].split('\n')[:8]):
                            fill([f"otherimageurl{idx+1}"], o_url.strip())
                    else:
                        # 父體行 Parent SKU 留空
                        fill(["productname", "itemname"], f"{brand} {ai['title']} {ai['elements']}")

                    # 填充五點
                    for bi, b_text in enumerate(ai.get('bp', [])):
                        fill([f"keyproductfeatures{bi+1}", f"bulletpoint{bi+1}"], b_text)
                    
                    fill(["productdescription", "description"], ai.get('desc', ''))
                    fill(["generickeywords", "searchterms"], format_amazon_kw(ai.get('elements', ''), global_kws))
                    row_cursor += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ 生成完成！")
            st.download_button("💾 下載修復版文件", out.getvalue(), "Amazon_V39_Fixed.xlsm")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
