import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import openpyxl
from openpyxl.styles import Font, Alignment
from openai import OpenAI
from PIL import Image

# --- 1. 頁面配置與側邊欄指令 ---
st.set_page_config(page_title="亞馬遜 AI 專家 V8.9", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

with st.sidebar:
    st.header("⚙️ AI 指令與配置")
    brand_name = st.text_input("品牌名稱", "YourBrand")
    # 指令窗口回歸
    system_logic = st.text_area("AI 寫作指令窗口", height=200, value="Title: [Brand] + Category + Pattern Details (180 chars). Bullets: 5 points with Headers (40 words each).")
    
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("選擇 Amazon 模板", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("定義固定尺寸與價格")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

# --- 2. 核心 AI 工具函數 ---
def process_img_for_ai(file):
    img = Image.open(file)
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 3. 核心布局：SKU 視覺分析矩陣 ---
st.header("🖼️ SKU 視覺分析與連結精確矩陣")
st.info("💡 每行代表一個款式：上傳圖片供 AI 分析，並填入對應連結。")

if 'rows' not in st.session_state: st.session_state.rows = 3

sku_data = []
for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1} 配置區", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 3, 3, 4])
        with c1:
            local_img = st.file_uploader(f"分析圖片 {i+1}", key=f"img_{i}")
            sku_name = st.text_input(f"SKU 名稱 {i+1}", key=f"sku_{i}")
        with c2:
            main_url = st.text_input(f"主圖直連連結 {i+1}", key=f"main_{i}")
            others = st.text_area(f"其他圖連結集 (每行一個) {i+1}", key=f"others_{i}", height=100)
        with c3:
            s1_url = st.text_input(f"{s1} 特有連結 {i+1}", key=f"s1u_{i}")
            s2_url = st.text_input(f"{s2} 特有連結 {i+1}", key=f"s2u_{i}")
            s3_url = st.text_input(f"{s3} 特有連結 {i+1}", key=f"s3u_{i}")
        with c4:
            st.write("📝 AI 文案預覽 (自動生成)")
            # 這裡預留 AI 反饋顯示
        sku_data.append({"sku": sku_name, "img": local_img, "main": main_url, "others": others, "size_urls": [s1_url, s2_url, s3_url]})

if st.button("➕ 增加款式行"): 
    st.session_state.rows += 1
    st.rerun()

# --- 4. 關鍵詞與生成 ---
user_kw = st.text_area("📝 Search Terms 關鍵詞方案", height=100)

if st.button("🚀 啟動 AI 分析與精確填充", use_container_width=True):
    if not selected_tpl: st.error("❌ 請選擇模板")
    else:
        try:
            with st.status("🚄 AI 正在逐行分析圖案並對位連結...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                h = {str(c.value).lower().strip(): c.column for c in sheet[3] if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value}

                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_data:
                    if not item["sku"] or not item["img"]: continue
                    
                    # 1. AI 視覺分析
                    b64 = process_img_for_ai(item["img"])
                    prompt = f"{system_logic}\nSKU:{item['sku']}\nKW:{user_kw}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','theme':''}}"
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}], response_format={"type":"json_object"})
                    data = json.loads(res.choices[0].message.content)

                    # 2. 變體循環填充
                    for idx, (sz_name, sz_price) in enumerate([(s1, p1), (s2, p2), (s3, p3)]):
                        for col, val in defaults.items():
                            cell = sheet.cell(row=curr_row, column=col, value=val)
                            cell.font = Font(name='Arial', size=10)
                        
                        def fill(name, val):
                            if name in h:
                                cell = sheet.cell(row=curr_row, column=h[name], value=str(val))
                                cell.font = Font(name='Arial', size=10)
                        
                        fill("seller sku", f"{item['sku']}-{sz_name.replace('\"','')}")
                        fill("parent sku", f"{item['sku']}-P")
                        fill("product name", f"{brand_name} {data.get('title','')} - {sz_name}")
                        fill("main_image_url", item["main"])
                        fill("other_image_url1", item["size_urls"][idx]) # 精確對位尺寸圖
                        fill("generic keyword", data.get('keywords',''))
                        # ... 其餘五點填充 ...
                        curr_row += 1
                
                status.update(label="✅ 分析與填充完成！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載 V8.9 終極對位版", output.getvalue(), "Listing_Final_AI.xlsm")
        except Exception as e:
            st.error(f"❌ 錯誤: {e}")
