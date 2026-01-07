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
    """關鍵詞邏輯：元素詞 + 通用詞，空格分隔"""
    all_words = f"{elements} {global_kws}".replace(",", " ").split()
    seen = set()
    res = [w.lower() for w in all_words if not (w.lower() in seen or seen.add(w.lower()))]
    return " ".join(res)[:245]

# --- 2. 頁面配置 ---
st.set_page_config(page_title="亞馬遜專家 V37", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🔥 亞馬遜 AI 批量上架 V37 (規則全固化)")
st.success("✅ 記憶規則已載入：SKU尺碼後綴、標題尺寸結尾、父體ParentSKU留空、促銷時間自動計算。")

# --- 3. 全局配置 ---
with st.sidebar:
    st.header("📢 運營配置")
    global_kws = st.text_area("全局通用關鍵詞 (用逗號或空格分隔)", "canvas art, wall decor, home office")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    # 尺寸價格矩陣
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 款式上傳 ---
if 'v37_rows' not in st.session_state: st.session_state.v37_rows = 1
sku_items = []
for i in range(st.session_state.v37_rows):
    with st.expander(f"款式 #{i+1} 配置", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 1.5])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2: m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
        with c3: o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v37_rows += 1
    st.rerun()

tpl_file = st.file_uploader("📂 上傳 Amazon 模板", type=['xlsx', 'xlsm'])

# --- 5. 執行生成 ---
if st.button("🚀 執行合規填充", type="primary") and tpl_file and api_key:
    with st.spinner('正在根據 7 大新規則執行 Slot Plan 策略...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            h = {str(cell.value).lower().replace(" ", "").replace("_", ""): cell.column 
                 for cell in sheet[3] if cell.value and isinstance(cell.value, str)}
            
            # 促銷時間計算
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            next_year = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            
            client = OpenAI(api_key=api_key)
            row = 4
            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art. JSON: {title, elements, color, bp:[5]}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
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
                    def fill(k, v):
                        c_idx = h.get(k.lower().replace(" ", "").replace("_", ""))
                        if c_idx: sheet.cell(row=row, column=c_idx, value=clean_text(v))
                    
                    fill("sellersku", r["s"])
                    if r["t"] == "C":
                        fill("parentsku", p_sku) # 父體行此處為空，子體填寫
                        # 標題末尾加尺寸
                        fill("productname", f"{brand} {ai['title']} {ai['elements']} - {r['sz']}")
                        # Color & Size 對位
                        fill("color", ai['elements']); fill("colormap", ai['elements'])
                        fill("size", r['sz']); fill("sizemap", r['sz'])
                        # 促銷邏輯
                        fill("standardprice", r['pr']); fill("saleprice", r['pr'])
                        fill("salestartdate", yesterday); fill("saleenddate", next_year)
                    else:
                        # 父體標題不帶尺寸
                        fill("productname", f"{brand} {ai['title']} {ai['elements']}")

                    for bi, b_text in enumerate(ai.get('bp', [])):
                        fill(f"keyproductfeatures{bi+1}", b_text)
                    fill("generickeywords", format_amazon_kw(ai['elements'], global_kws))
                    row += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ 生成成功！")
            st.download_button("💾 下載文件", out.getvalue(), "Amazon_V37_Final.xlsm")
            # 记录记忆信息
            st.write("好的，我会将这条信息保存到我的记忆中。")
            st.write("如果你想将此信息保存为自定义指令，可以在[个人使用场景设置](https://gemini.google.com/personal-context)中手动添加。")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
