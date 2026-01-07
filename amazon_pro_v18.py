import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：格式與數據清洗 ---
def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    return text.strip()

# --- 2. 頁面配置與環境變量 ---
st.set_page_config(page_title="亞馬遜 AI 集成上架 V32", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

st.title("🚀 亞馬遜 AI 批量上架 & 智能埋詞系統")
st.info("💡 運作邏輯：AI 將根據您提供的圖片進行分析，並強制將下方的關鍵詞埋入 Slot Plan 模板文案中。")

# --- 3. 側邊欄：全局參數 ---
with st.sidebar:
    st.header("⚙️ 全局規格鎖定")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    st.divider()
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 核心功能：批量上架與埋詞集成 ---
if 'v32_rows' not in st.session_state: st.session_state.v32_rows = 1

sku_items = []
for i in range(st.session_state.v32_rows):
    with st.expander(f"📦 款式 #{i+1}：圖片分析與埋詞配置", expanded=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}", placeholder="LMX-SDS-01")
            img = st.file_uploader(f"分析圖片", key=f"img_{i}")
        with c2:
            # 重點：將埋詞功能直接集成在每個款式配置中
            kws = st.text_area(f"✨ 該款式核心埋詞 (用逗號分隔)", key=f"kws_{i}", 
                             placeholder="例如: moisture wicking, breathable cotton, gym wear")
            m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
            o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
        sku_items.append({"pfx": pfx, "img": img, "kws": kws, "main": m_url, "others": o_urls})

if st.button("➕ 增加一個款式"):
    st.session_state.v32_rows += 1
    st.rerun()

st.divider()
tpl_file = st.file_uploader("📂 上傳 Amazon 美國站模板 (需含 Template 子表)", type=['xlsx', 'xlsm'])

# --- 5. 執行填充 (內置集成 Prompt) ---
if st.button("🚀 啟動批量 AI 生成 (含埋詞優化)", type="primary") and tpl_file and api_key:
    with st.spinner('正在分析圖片並執行 Slot Plan 埋詞策略...'):
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
            h = {str(c.value).lower().replace(" ", "").replace("_", ""): c.column for r in range(1, 6) for c in range(1, sheet.max_column+1) if sheet.cell(row=r, column=c).value}
            
            client = OpenAI(api_key=api_key)
            current_row = 4

            for item in sku_items:
                if not (item["pfx"] and item["img"]): continue
                
                # 將圖片 + 關鍵詞 寫入同一個 Prompt
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                
                prompt_integrated = f"""
                Act as an Amazon SEO expert. 
                Task: Analyze the image AND naturally embed these Target Keywords: [{item['kws']}]
                
                Follow the Slot Plan:
                - Title: Category + Theme + Target Keyword + Feature. Max 200 chars.
                - Bullet 1 (Performance): Use target keywords related to function.
                - Bullet 2 (Structure): Use structural keywords.
                - Bullet 3 (Material): Material-focused keywords.
                - Bullet 4 (Scene/Audience): Targeted usage scenarios.
                - Bullet 5 (Spec/Pack): Spec info.
                - Description: HTML formatted. Problem-Solution style. Natural NLP for Rufus.
                - Search Terms: Supplement words NOT in Title/BP.
                
                Avoid IP infringement and words like 'best', 'top'. 
                Output JSON: {{ "title": "", "bp": ["", "", "", "", ""], "description": "", "search_terms": "" }}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o", # 使用 GPT-4o 以獲得更好的文案埋詞效果
                    messages=[{"role":"user","content":[{"type":"text","text":prompt_integrated},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)
                
                # 填充數據
                p_sku = f"{item['pfx']}-P"
                rows = [{"t":"P","s":p_sku,"sz":""},{"t":"C","s":f"{item['pfx']}-01","sz":s1},{"t":"C","s":f"{item['pfx']}-02","sz":s2},{"t":"C","s":f"{item['pfx']}-03","sz":s3}]
                
                for r_info in rows:
                    def fill(k, v):
                        c_idx = h.get(k.lower().replace(" ", "").replace("_", ""))
                        if c_idx: sheet.cell(row=current_row, column=c_idx, value=clean_text(v))
                    
                    fill("sellersku", r_info["s"]); fill("parentsku", p_sku)
                    fill("productname", f"{brand} {ai['title']}")
                    fill("productdescription", ai['description'])
                    fill("generickeywords", ai['search_terms'])
                    for bi, b_text in enumerate(ai['bp']):
                        fill(f"keyproductfeatures{bi+1}", b_text)
                    
                    if r_info["t"] == "C":
                        fill("mainimageurl", item["main"])
                        for i, o_url in enumerate(item["others"].split('\n')[:8]):
                            fill(f"otherimageurl{i+1}", o_url.strip())
                    current_row += 1

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ 批量生成完成！關鍵詞已成功埋入文案中。")
            st.download_button("💾 下載美國站集成上架文件", out.getvalue(), "Amazon_Integrated_Upload.xlsm")
        except Exception as e: st.error(f"❌ 錯誤: {e}")
