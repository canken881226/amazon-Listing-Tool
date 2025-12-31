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
st.set_page_config(page_title="亞馬遜 AI 模板自適應版 V7.1", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心 AI 指令 (深度視覺描述與關鍵詞權重版) ---
SYSTEM_LOGIC = """
You are an Amazon Listing Optimization Expert. All output in ENGLISH.
1. Title: [Brand] + [Main Category Phrase] + [Detailed Visual Elements: e.g., Sun-drenched Autumn Forest] + [Core Benefit]. Length: 130-150 chars. (NO 'Brand' word).
2. Search Terms: Individual words only. Logic: Pattern elements > AI keywords > Generic library. Max 240 chars.
3. Bullets: 5 points with bold headers. Vividly describe the 3D visual effect and material.
4. Description: HTML format (<b>, <br>). Focus on transformation and gift value.
5. Color/Color Map: IDENTIFY THE THEME WORD (e.g., ZenBamboo, OceanWave). Use this theme word for BOTH fields. NEVER use basic colors.
"""

# --- 3. 核心工具函數 ---
def generate_slim_parent_sku(prefixes):
    """實現精簡命名：SQDQ-082-087-P"""
    if not prefixes: return "PARENT-P"
    if len(prefixes) == 1: return f"{prefixes[0]}-P"
    s, e = prefixes[0], prefixes[-1]
    i = 0
    while i < min(len(s), len(e)) and s[i] == e[i]: i += 1
    last_dash = s[:i].rfind('-')
    return f"{s}-{e[last_dash+1:]}-P" if last_dash != -1 else f"{s}-{e}-P"

def safe_keyword_cut(raw_text, limit=245):
    """精確截斷關鍵詞，不截斷單個單詞"""
    words = re.findall(r'\b[a-z0-9]{2,}\b', raw_text.lower())
    unique, seen, cur_len = [], set(), 0
    for w in words:
        if w not in seen:
            new_len = cur_len + len(w) + (1 if cur_len > 0 else 0)
            if new_len <= limit:
                unique.append(w); seen.add(w); cur_len = new_len
            else: break
    return " ".join(unique)

def reset_cell(cell):
    """解決亂碼問題：強制重置字體與換行"""
    cell.font = Font(name='Arial', size=10)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

def process_img_fast(file):
    """預壓縮圖片提升並發速度"""
    img = Image.open(file)
    img.thumbnail((800, 800))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 4. 主界面 ---
st.title("🤖 亞馬遜 AI 模板自適應填充系統 V7.1")

col_cfg, col_sz = st.columns([1, 2])
with col_cfg:
    brand_name = st.text_input("Brand (僅填品牌名)", value="YourBrand")
with col_sz:
    st.write("💰 尺寸與價格配置 (將對應模板 Sale Price)")
    default_df = pd.DataFrame([{"Size": '16x24"', "Price": "12.99"},{"Size": '24x36"', "Price": "19.99"},{"Size": '32x48"', "Price": "29.99"}])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

uploaded_imgs = st.file_uploader("🖼️ 批量上傳主圖 (SKU前綴命名)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
user_all_kw = st.text_area("📝 基礎關鍵詞方案 (Ⅰ-Ⅴ類詞組與單詞)", height=150)

# --- 5. 執行邏輯 ---
if st.button("🚀 啟動自適應極速填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 請先上傳圖片")
    else:
        try:
            with st.status("🚄 並發分析中... 已開啟模板內容繼承模式") as status:
                # 排序與命名
                sku_prefixes = sorted([os.path.splitext(img.name)[0] for img in uploaded_imgs])
                parent_sku_final = generate_slim_parent_sku(sku_prefixes)
                
                # 併發任務
                def call_ai(img):
                    prefix = os.path.splitext(img.name)[0]
                    client = OpenAI(api_key=api_key)
                    b64 = process_img_fast(img)
                    prompt = f"{SYSTEM_LOGIC}\nSKU:{prefix}\nKeyword Pool:{user_all_kw}\nReturn JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','theme_word':''}}"
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}], response_format={"type":"json_object"})
                    return {"prefix": prefix, "data": json.loads(res.choices[0].message.content)}

                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(call_ai, uploaded_imgs))
                
                # 加載模板與掃描固定內容
                tpl_files = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
                wb = openpyxl.load_workbook(os.path.join("templates", tpl_files[0]), keep_vba=True)
                sheet = wb.active
                
                header_map = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "key product features" in str(c.value).lower()]
                
                # 核心：獲取模板第 4 列的固定內容
                template_defaults = {col_idx: sheet.cell(row=4, column=col_idx).value for col_idx in range(1, sheet.max_column + 1) if sheet.cell(row=4, column=col_idx).value}

                curr_row = 5
                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')

                for idx, res in enumerate(results):
                    prefix, data = res["prefix"], res["data"]
                    if not data: continue
                    theme = data.get('theme_word', 'PatternArt')
                    st_words = safe_keyword_cut(f"{theme} {data.get('keywords','')} {user_all_kw}")
                    bt = f"{brand_name} {data.get('title','')}"

                    # 子體填充
                    for _, s_row in size_price_data.iterrows():
                        # 1. 繼承模板固定值
                        for col_idx, def_val in template_defaults.items():
                            reset_cell(sheet.cell(row=curr_row, column=col_idx, value=def_val))
                        
                        # 2. 覆蓋 AI 動態值
                        def fill_c(name, val):
                            if name in header_map: reset_cell(sheet.cell(row=curr_row, column=header_map[name], value=str(val).strip()))
                        
                        fill_c("seller sku", f"{prefix}-{str(s_row['Size']).replace('\"','').replace(' ','')}")
                        fill_c("parent sku", parent_sku_final)
                        fill_c("parentage", "child")
                        fill_c("product name", f"{bt} - {s_row['Size']}"[:150])
                        fill_c("sale price", s_row['Price'])
                        fill_c("size", s_row['Size'])
                        fill_c("size map", s_row['Size'])
                        fill_c("sale start date", s_start)
                        fill_c("sale end date", s_end)
                        fill_c("product description", data.get('desc',''))
                        fill_c("generic keyword", st_words)
                        fill_c("color", theme)
                        fill_c("color map", theme)
                        for i, c_idx in enumerate(bp_cols[:5]):
                            if i < len(data.get('bp', [])): reset_cell(sheet.cell(row=curr_row, column=c_idx, value=data['bp'][i]))
                        curr_row += 1
                
                # 父體填充
                for col_idx, def_val in template_defaults.items():
                    reset_cell(sheet.cell(row=4, column=col_idx, value=def_val))
                def fill_p(name, val):
                    if name in header_map: reset_cell(sheet.cell(row=4, column=header_map[name], value=str(val).strip()))
                fill_p("seller sku", parent_sku_final)
                fill_p("parentage", "parent")
                fill_p("product name", bt)
                fill_p("color", "")
                fill_p("color map", "")

                status.update(label=f"✅ 完成！父體 SKU: {parent_sku_final}", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下載 V7.1 最終版表格", output.getvalue(), f"Listing_V7.1_{parent_sku_final}.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 錯誤: {e}")
