import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI
from openpyxl.styles import Font, Alignment
from PIL import Image

# --- 1. 基础配置 ---
st.set_page_config(page_title="亞馬遜 V7.2 終極穩定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心逻辑工具 ---
class SOP_Manager:
    @staticmethod
    def clean(text):
        if not text: return ""
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_st(raw, pool):
        """关键词规则：仅空格分隔，不含标点"""
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', f"{raw} {pool}".lower())
        words = []
        seen = set()
        for w in clean.split():
            if w not in seen and len(w) > 1:
                words.append(w)
                seen.add(w)
        return " ".join(words)[:245]

    @staticmethod
    def process_img(file):
        """压缩图片减少传输压力"""
        img = Image.open(file)
        img.thumbnail((500, 500))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 3. 界面布局 ---
st.title("🛡️ 亞馬遜規格終極鎖定 V7.2")

with st.sidebar:
    brand = st.text_input("Brand Name", value="AMAZING WALL")
    st.divider()
    st.subheader("尺寸與定價配置")
    default_df = pd.DataFrame([
        {"Size": '16x24"', "Price": "12.99"},
        {"Size": '24x36"', "Price": "19.99"},
        {"Size": '32x48"', "Price": "29.99"}
    ])
    size_price_data = st.data_editor(default_df, num_rows="dynamic")

# 关键改动：给 file_uploader 增加唯一的 key，防止组件状态死锁
uploaded_imgs = st.file_uploader("🖼️ 上传图片", type=["jpg", "png", "jpeg"], accept_multiple_files=True, key="img_uploader")
user_kw = st.text_area("📝 关键词词库", height=100)
uploaded_tpl = st.file_uploader("📂 上传模板", type=['xlsx', 'xlsm'], key="tpl_uploader")

# --- 4. 核心处理逻辑 ---
if st.button("🚀 启动自动化填充", use_container_width=True, key="start_btn"):
    if not uploaded_imgs or not uploaded_tpl or not api_key:
        st.error("❌ 启动失败：请确保图片、模板已上传，且 API Key 已配置。")
    else:
        try:
            status = st.empty()
            progress = st.progress(0)
            
            # 1. 初始化模板
            wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            bp_cols = [c.column for r in sheet.iter_rows(max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]
            
            client = OpenAI(api_key=api_key)
            all_results = []
            
            # 2. 串行 AI 分析
            for i, img_file in enumerate(uploaded_imgs):
                prefix = os.path.splitext(img_file.name)[0]
                status.info(f"正在分析款式 ({i+1}/{len(uploaded_imgs)}): {prefix}")
                
                # 图片指针重置，防止读取为空
                img_file.seek(0)
                b64 = SOP_Manager.process_img(img_file)
                
                prompt = "Analyze art. JSON: {'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}"
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                all_results.append({"prefix": prefix, "data": json.loads(res.choices[0].message.content)})
                progress.progress((i + 1) / len(uploaded_imgs))

            # 3. 计算父类 SKU 范围
            pfx_list = [r["prefix"] for r in all_results]
            if len(pfx_list) > 1:
                nums = [int(re.findall(r'\d+', p)[-1]) for p in pfx_list if re.findall(r'\d+', p)]
                base = pfx_list[0].rsplit('-', 1)[0] if '-' in pfx_list[0] else pfx_list[0]
                p_sku_total = f"{base}-{min(nums):02d}-{max(nums):02d}" if nums else pfx_list[0]
            else:
                p_sku_total = pfx_list[0]

            # 4. 写入数据
            status.info("📝 正在按照规格写入 Excel...")
            curr_row = 5
            parent_row = 4
            t = datetime.now()
            s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=365)).strftime('%Y-%m-%d')

            def fill(r, k, v):
                target = k.lower().replace(" ", "")
                if target in h:
                    cell = sheet.cell(row=r, column=h[target], value=SOP_Manager.clean(v))
                    cell.font = Font(name='Arial', size=10)
                    cell.alignment = Alignment(wrap_text=True, vertical='top')

            # --- A. 填充第一行 (父类行) ---
            first = all_results[0]["data"]
            fill(parent_row, "sellersku", p_sku_total)
            fill(parent_row, "parentage", "parent")
            fill(parent_row, "productname", f"{brand} {first.get('title','')}"[:199])
            fill(parent_row, "generickeyword", SOP_Manager.format_st(f"{first.get('color','')} {first.get('keywords','')}", user_kw))
            fill(parent_row, "productdescription", first.get('desc',''))
            # 规格：第一行 Parent SKU, Color, Color Map 必填为空
            fill(parent_row, "parentsku", "")
            fill(parent_row, "color", "")
            fill(parent_row, "colormap", "")
            for b_idx, c_col in enumerate(bp_cols[:5]):
                fill(parent_row, f"bullet_{b_idx}", first['bp'][b_idx] if b_idx < len(first['bp']) else "")

            # --- B. 填充子类行 ---
            for res in all_results:
                pfx, data = res["prefix"], res["data"]
                st_val = SOP_Manager.format_st(f"{data.get('color','')} {data.get('keywords','')}", user_kw)
                
                for _, s_row in size_price_data.iterrows():
                    sz = str(s_row["Size"])
                    pr = str(s_row["Price"])
                    sz_tag = sz.replace('"', '').replace(' ', '')
                    c_sku = f"{pfx}-{sz_tag}" # 规格：前缀-尺寸
                    
                    fill(curr_row, "sellersku", c_sku)
                    fill(curr_row, "parentsku", p_sku_total)
                    fill(curr_row, "parentage", "child")
                    fill(curr_row, "productname", f"{brand} {data.get('title','')} - {sz}"[:199])
                    fill(curr_row, "size", sz)
                    fill(curr_row, "sizemap", sz)
                    fill(curr_row, "color", f"{data.get('color','')} {data.get('keywords','')}")
                    fill(curr_row, "colormap", f"{data.get('color','')} {data.get('keywords','')}")
                    fill(curr_row, "standardprice", pr)
                    fill(curr_row, "salestartdate", s_start)
                    fill(curr_row, "saleenddate", s_end)
                    fill(curr_row, "generickeyword", st_val)
                    
                    for b_idx, c_col in enumerate(bp_cols[:5]):
                        if b_idx < len(data['bp']):
                            sheet.cell(row=curr_row, column=c_col, value=SOP_Manager.clean(data['bp'][b_idx]))
                    curr_row += 1

            status.success("✅ 处理完成！")
            out = io.BytesIO()
            wb.save(out)
            st.download_button("💾 点击下载 V7.2 锁定版", out.getvalue(), "Amazon_V7.2_Fixed.xlsm", use_container_width=True)

        except Exception as e:
            st.error(f"❌ 运行报错: {str(e)}")
