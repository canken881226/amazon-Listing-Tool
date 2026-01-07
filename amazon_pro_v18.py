import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl, os
from openai import OpenAI

# --- 1. 核心工具：數據清洗與格式化 ---
def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    return text.strip()

# --- 2. 頁面配置與環境變量 ---
st.set_page_config(page_title="亞馬遜 AI 運營工具 V31", layout="wide")
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY") or ""

# --- 3. 側邊欄：功能選擇與 AI 運營助手 ---
with st.sidebar:
    st.header("🤖 功能導航")
    mode = st.radio("切換模式", ["批量分析上架", "AI 文案埋詞助手"])
    
    st.divider()
    st.header("⚙️ 規格鎖定 (上架用)")
    brand = st.text_input("品牌名稱", "AMAZING WALL")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 4. 模式一：批量分析上架 (嵌入 Slot Plan 模板) ---
if mode == "批量分析上架":
    st.header("🎨 AI 視覺分析上架 (內置 Slot Plan 模板)")
    
    # 款式管理
    if 'v31_rows' not in st.session_state: st.session_state.v31_rows = 1
    sku_items = []
    for i in range(st.session_state.v31_rows):
        with st.expander(f"款式 #{i+1} 配置", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                pfx = st.text_input(f"SKU 前綴", key=f"pfx_{i}")
                img = st.file_uploader(f"分析圖片", key=f"img_{i}")
            with c2:
                m_url = st.text_input(f"主圖 URL", key=f"m_url_{i}")
                o_urls = st.text_area(f"附圖 URLs (每行一個)", key=f"o_urls_{i}")
            sku_items.append({"pfx": pfx, "img": img, "main": m_url, "others": o_urls})
    
    if st.button("➕ 增加一個款式"):
        st.session_state.v31_rows += 1
        st.rerun()

    tpl_file = st.file_uploader("📂 上傳 Amazon 美國站模板", type=['xlsx', 'xlsm'])

    if st.button("🚀 啟動 AI 批量填充", type="primary") and tpl_file and api_key:
        with st.spinner('AI 正在根據 Slot Plan 模板生成文案...'):
            try:
                wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
                sheet = wb['Template'] if 'Template' in wb.sheetnames else wb.active
                h = {str(c.value).lower().replace(" ", "").replace("_", ""): c.column for r in range(1, 6) for c in range(1, sheet.max_column+1) if sheet.cell(row=r, column=c).value}
                
                client = OpenAI(api_key=api_key)
                current_row = 4

                for item in sku_items:
                    if not (item["pfx"] and item["img"]): continue
                    
                    # 嵌入 Slot Plan 的 Prompt 指令
                    item["img"].seek(0)
                    b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                    prompt = """
                    Act as an Amazon Expert. Analyze image and output JSON:
                    {
                      "title": "Category + 1-2 Themes + 1 Feature (Keep under 200 chars)",
                      "bp": [
                        "Bullet 1 (Performance): Function words + Feeling",
                        "Bullet 2 (Fit/Structure): Structural words",
                        "Bullet 3 (Material/Craft): Material words",
                        "Bullet 4 (Scene/Audience): Target audience/Usage scene",
                        "Bullet 5 (Spec/Pack): Multi-pack/Maintenance info"
                      ],
                      "description": "HTML formatted text. Use <p><b> etc. Focus on Problem-Solution-Scene. Avoid repeating Title words.",
                      "search_terms": "Related keywords not mentioned in Title/BP (Space separated, no repeat)"
                    }
                    """
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)
                    
                    # 填充 1 父 3 子
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
                st.download_button("💾 下載美國站上架文件", out.getvalue(), "Amazon_Bulk_SlotPlan.xlsm")
            except Exception as e: st.error(f"❌ 錯誤: {e}")

# --- 5. 模式二：AI 文案埋詞助手 (對接 ChatGPT) ---
elif mode == "AI 文案埋詞助手":
    st.header("🚀 AI 智能埋詞優化助手")
    st.markdown("""
    **功能說明：** 在下方輸入您從廣告或競爭對手處挖掘的關鍵詞，AI 會自動將其埋入符合 **Rufus 自然語言偏好** 的文案中。
    """)
    
    target_kw = st.text_area("✍️ 請輸入要埋入的關鍵詞 (詞組或單詞，用逗號分隔)", placeholder="例如：moisture wicking, gym wear, high waist yoga pants")
    current_copy = st.text_area("📝 粘貼現有文案 (標題或五點描述)", height=200)
    
    if st.button("✨ 執行 AI 埋詞優化", type="primary") and api_key:
        with st.spinner('正在優化文案並排除侵權詞...'):
            try:
                client = OpenAI(api_key=api_key)
                prompt_assist = f"""
                Optimize the following Amazon copy. 
                1. Embed these keywords naturally: {target_kw}.
                2. Follow Slot Plan rules: Miss-over with Title, natural language for Rufus.
                3. Avoid IP infringement and sensitive words like 'best', 'top', '100%'.
                4. Use HTML for description if needed.
                Current Copy: {current_copy}
                Output format: Optimized Title, Optimized Bullets, Optimized Description.
                """
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"system","content":"You are a senior Amazon SEO expert."},{"role":"user","content":prompt_assist}]
                )
                st.subheader("✅ 優化後的文案內容")
                st.write(res.choices[0].message.content)
            except Exception as e: st.error(f"❌ 優化出錯: {e}")
