import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI
from openpyxl.styles import Font, Alignment
from PIL import Image

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 規格鎖定 V7.1", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心工具函數 ---
def clean_text(text):
    if not text: return ""
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

def safe_keyword_cut(raw_text, limit=245):
    clean_words = re.findall(r'\b[a-z0-9]{2,}\b', raw_text.lower())
    unique_words = []
    seen = set()
    current_length = 0
    for w in clean_words:
        if w not in seen:
            new_len = current_length + len(w) + (1 if current_length > 0 else 0)
            if new_len <= limit:
                unique_words.append(w)
                seen.add(w)
                current_length = new_len
            else:
                break
    return " ".join(unique_words)

def reset_cell(cell, bold=False):
    cell.font = Font(name='Arial', size=10, bold=bold)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    img = Image.open(file)
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=65)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 3. 主界面 ---
st.title("⚡ 亞馬遜 AI 精細化填充 V7.1 (穩定加固版)")

with st.sidebar:
    brand_name = st.text_input("Brand Name", value="AMAZING WALL")
    st.divider()
    st.subheader("變體尺寸與定價")
    default_df = pd.DataFrame([
        {"Size": '16x24"', "Price": "12.99"},
        {"Size": '24x36"', "Price": "19.99"},
        {"Size": '32x48"', "Price": "29.99"}
    ])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批量圖片 (檔名為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 關鍵詞庫 (Search Terms Pool)", height=150)
uploaded_tpl = st.file_uploader("📂 上傳模板 Excel", type=['xlsx', 'xlsm'])

# --- 4. 執行處理 (優化為更穩定的循環邏輯) ---
if st.button("🚀 啟動優化填充", use_container_width=True):
    if not uploaded_imgs or not uploaded_tpl or not api_key:
        st.error("❌ 缺失必要條件：請檢查圖片、模板或 API Key。")
    else:
        try:
            # 初始化數據
            all_results = []
            wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
            bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]
            
            curr_row = 5
            parent_row = 4
            t = datetime.now()
            s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=365)).strftime('%Y-%m-%d')
            client = OpenAI(api_key=api_key)

            # --- 第一階段：逐一分析圖片 (串行處理更穩定) ---
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, img_file in enumerate(uploaded_imgs):
                prefix = os.path.splitext(img_file.name)[0]
                status_text.text(f"正在分析款式 ({i+1}/{len(uploaded_imgs)}): {prefix}")
                
                try:
                    b64 = process_img_fast(img_file)
                    prompt = f"Amazon Listing Expert. Analyze art pattern. Return JSON: {{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}. Pool: {user_all_kw}"
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                        response_format={"type":"json_object"},
                        timeout=30
                    )
                    data = json.loads(res.choices[0].message.content)
                    all_results.append({"prefix": prefix, "data": data})
                except Exception as ai_err:
                    st.warning(f"⚠️ 款式 {prefix} 分析失敗，已跳過。錯誤: {ai_err}")
                
                progress_bar.progress((i + 1) / len(uploaded_imgs))

            # --- 第二階段：計算父類 SKU 範圍 ---
            valid_pfxs = [r["prefix"] for r in all_results if r["data"]]
            if not valid_pfxs:
                st.error("❌ 所有圖片分析均失敗，請檢查網路或 API。")
                st.stop()

            if len(valid_pfxs) > 1:
                nums = [int(re.findall(r'\d+', p)[-1]) for p in valid_pfxs if re.findall(r'\d+', p)]
                base_part = valid_pfxs[0].rsplit('-', 1)[0] if '-' in valid_pfxs[0] else valid_pfxs[0]
                p_sku_total = f"{base_part}-{min(nums):02d}-{max(nums):02d}" if nums else valid_pfxs[0]
            else:
                p_sku_total = valid_pfxs[0]

            # --- 第三階段：寫入 Excel ---
            status_text.text("正在將數據寫入表格...")
            
            # 1. 填充父體行
            first_data = all_results[0]["data"]
            def fill_row(r_idx, k, v):
                target = k.lower().replace(" ", "")
                if target in h: reset_cell(sheet.cell(row=r_idx, column=h[target], value=clean_text(v)))

            fill_row(parent_row, "sellersku", p_sku_total)
            fill_row(parent_row, "parentage", "parent")
            fill_row(parent_row, "productname", f"{brand_name} {first_data.get('title','')}"[:199])
            fill_row(parent_row, "generickeyword", safe_keyword_cut(f"{first_data.get('color','')} {first_data.get('keywords','')} {user_all_kw}"))
            fill_row(parent_row, "productdescription", first_data.get('desc',''))
            # 第一行 (父體) 鎖定不填：Parent SKU, Color, Color Map
            fill_row(parent_row, "parentsku", "")
            fill_row(parent_row, "color", "")
            fill_row(parent_row, "colormap", "")
            for b_i, c_idx in enumerate(bp_cols[:5]):
                if b_i < len(first_data.get('bp', [])):
                    reset_cell(sheet.cell(row=parent_row, column=c_idx, value=clean_text(first_data['bp'][b_i])))

            # 2. 循環填充子體
            for res in all_results:
                pfx, data = res["prefix"], res["data"]
                pattern = data.get('color', 'Modern')
                st_val = safe_keyword_cut(f"{pattern} {data.get('keywords','')} {user_all_kw}")
                bt = f"{brand_name} {data.get('title','')}"
                full_color = f"{pattern} {data.get('keywords','')}"

                for _, s_row in size_price_data.iterrows():
                    sz, pr = str(s_row["Size"]), str(s_row["Price"])
                    sz_tag = sz.replace('"', '').replace(' ', '')
                    c_sku = f"{pfx}-{sz_tag}"
                    
                    fill_row(curr_row, "sellersku", c_sku)
                    fill_row(curr_row, "parentsku", p_sku_total)
                    fill_row(curr_row, "parentage", "child")
                    fill_row(curr_row, "productname", f"{bt} - {sz}"[:199])
                    fill_row(curr_row, "size", sz)
                    fill_row(curr_row, "sizemap", sz)
                    fill_row(curr_row, "color", full_color)
                    fill_row(curr_row, "colormap", full_color)
                    fill_row(curr_row, "standardprice", pr)
                    fill_row(curr_row, "saleprice", pr)
                    fill_row(curr_row, "salestartdate", s_start)
                    fill_row(curr_row, "saleenddate", s_end)
                    fill_row(curr_row, "generickeyword", st_val)
                    fill_row(curr_row, "productdescription", data.get('desc',''))
                    
                    for b_i, c_idx in enumerate(bp_cols[:5]):
                        if b_i < len(data.get('bp', [])):
                            reset_cell(sheet.cell(row=curr_row, column=c_idx, value=clean_text(data['bp'][b_i])))
                    curr_row += 1

            status_text.text("✅ 处理完成！")
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載 V7.1 穩定版", output.getvalue(), "Amazon_V7.1_Fixed.xlsm", use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ 程序崩潰: {e}")
