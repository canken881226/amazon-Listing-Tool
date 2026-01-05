import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import re
from datetime import datetime, timedelta
from openai import OpenAI
import openpyxl
from openpyxl.styles import Font, Alignment
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

# --- 1. 頁面配置 ---
st.set_page_config(page_title="亞馬遜 AI 規格鎖定版 V6.8", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心工具函數 ---
def clean_text(text):
    """防止亂碼：強制轉換為字串並清理非法字符"""
    if not text: return ""
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

def safe_keyword_cut(raw_text, limit=245):
    """關鍵詞規則：元素詞+通用詞，空格間隔，不截斷單詞，限長 245"""
    # 移除標點符號，只留字母數字
    clean_words = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_text.lower())
    words = clean_words.split()
    unique_words = []
    seen = set()
    current_length = 0
    
    for w in words:
        if w not in seen and len(w) > 1:
            # 檢查加上單詞和空格後的長度
            new_len = current_length + len(w) + (1 if current_length > 0 else 0)
            if new_len <= limit:
                unique_words.append(w)
                seen.add(w)
                current_length = new_len
            else:
                break
    return " ".join(unique_words)

def reset_cell(cell, bold=False):
    """重置字體防止亂碼"""
    cell.font = Font(name='Arial', size=10, bold=bold)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    """修復圖片處理邏輯：確保圖片對象正確讀取"""
    img = Image.open(file)
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=65)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai_parallel(img_file, sku_prefix, user_kw):
    """AI 任務處理：鎖定 JSON 返回格式"""
    try:
        client = OpenAI(api_key=api_key)
        b64 = process_img_fast(img_file)
        prompt = f"""You are an Amazon Listing Expert. Analyze art pattern. SKU:{sku_prefix}.
        Return JSON format:
        {{
            "title": "rich descriptive title 130-150 chars",
            "desc": "HTML format description",
            "bp": ["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4", "Bullet 5"],
            "keywords": "individual pattern element words",
            "color": "main theme color"
        }}
        User Keyword Pool: {user_kw}"""
        
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=30
        )
        return {"prefix": sku_prefix, "data": json.loads(res.choices[0].message.content)}
    except Exception as e:
        return {"prefix": sku_prefix, "data": {}, "error": str(e)}

# --- 3. 主界面 ---
st.title("⚡ 亞馬遜 AI 規格鎖定系統 V6.8")

with st.sidebar:
    st.header("⚙️ 規格鎖定中心")
    brand_name = st.text_input("Brand Name", value="AMAZING WALL")
    
    st.divider()
    st.subheader("變體規格與價格")
    default_df = pd.DataFrame([
        {"Size": '16x24"', "Price": "12.99", "No": "001"},
        {"Size": '24x36"', "Price": "19.99", "No": "002"},
        {"Size": '32x48"', "Price": "29.99", "No": "003"}
    ])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批次上傳圖片 (檔名將作為 SKU 前綴)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 通用關鍵詞庫 (Search Terms Pool)", height=150)
# 修正 FileNotFoundError: 讓用戶上傳模板，不再依賴路徑
uploaded_tpl = st.file_uploader("📂 上傳亞馬遜空白模板 (XLSX/XLSM)", type=['xlsx', 'xlsm'])

# --- 4. 執行處理 ---
if st.button("🚀 啟動優化填充", use_container_width=True):
    if not uploaded_imgs or not uploaded_tpl:
        st.error("❌ 請上傳圖片及 Excel 模板文件")
    else:
        try:
            with st.status("🚄 AI 視覺分析中...") as status:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    results = list(executor.map(lambda img: call_ai_parallel(img, os.path.splitext(img.name)[0], user_all_kw), uploaded_imgs))

                # 讀取模板
                wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
                sheet = wb.active
                
                # 建立表頭映射
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]

                curr_row = 5
                t = datetime.now()
                s_start = (t - timedelta(days=1)).strftime('%Y-%m-%d')
                s_end = (t + timedelta(days=365)).strftime('%Y-%m-%d')
                
                for idx, res in enumerate(results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue

                    pattern = data.get('color', 'Modern')
                    final_st = safe_keyword_cut(f"{pattern} {data.get('keywords','')} {user_all_kw}")
                    bt = f"{brand_name} {data.get('title','')}"

                    # 規則：Parent SKU 範圍命名 (001-003)
                    first_no = size_price_data.iloc[0]['No']
                    last_no = size_price_data.iloc[-1]['No']
                    parent_sku_val = f"{prefix}-{first_no}-{last_no}"

                    # --- 填充邏輯：1行父體 + N行子體 ---
                    # 1. 填充父體
                    def fill_row(row_idx, k, v, is_bold=False):
                        target_key = k.lower().replace(" ", "")
                        if target_key in h:
                            reset_cell(sheet.cell(row=row_idx, column=h[target_key], value=clean_text(v)), bold=is_bold)

                    # 父體行 Seller SKU 與 Parent SKU 必須一致
                    fill_row(curr_row, "sellersku", parent_sku_val)
                    fill_row(curr_row, "parentsku", parent_sku_val)
                    fill_row(curr_row, "parentage", "parent")
                    fill_row(curr_row, "productname", bt[:199])
                    fill_row(curr_row, "generickeyword", final_st)
                    
                    # 鎖定：Color 與 Color Map 鏡像同步
                    full_color = f"{pattern} {data.get('keywords','')}"
                    fill_row(curr_row, "color", full_color)
                    fill_row(curr_row, "colormap", full_color)

                    # 鎖定：五點描述必填 (含父類)
                    ai_bps = data.get('bp', [])
                    while len(ai_bps) < 5: ai_bps.append("High-quality nature landscape art piece.")
                    for b_i, c_idx in enumerate(bp_cols[:5]):
                        reset_cell(sheet.cell(row=curr_row, column=c_idx, value=clean_text(ai_bps[b_i])))
                    
                    curr_row += 1

                    # 2. 填充子體
                    for _, s_row in size_price_data.iterrows():
                        sz, pr, no = str(s_row["Size"]), str(s_row["Price"]), str(s_row["No"])
                        c_sku = f"{prefix}-{no}"
                        
                        fill_row(curr_row, "sellersku", c_sku)
                        fill_row(curr_row, "parentsku", parent_sku_val)
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
                        fill_row(curr_row, "generickeyword", final_st)
                        fill_row(curr_row, "productdescription", data.get('desc',''))
                        
                        for b_i, c_idx in enumerate(bp_cols[:5]):
                            reset_cell(sheet.cell(row=curr_row, column=c_idx, value=clean_text(ai_bps[b_i])))
                        
                        curr_row += 1

                status.update(label="✅ 優化填充完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載修正版表格", output.getvalue(), f"Amazon_V6.8_Fixed.xlsm", use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ 嚴重錯誤: {e}")
