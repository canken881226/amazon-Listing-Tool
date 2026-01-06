import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl
from openai import OpenAI

# --- 1. 核心工具：格式與清洗 ---
def clean_text(text):
    """规则：彻底清除乱码与 AI 占位词"""
    if not text: return ""
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = {'word1', 'word2', 'fake', 'placeholder'}
    words = str(text).split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# --- 2. 頁面配置 ---
st.set_page_config(page_title="亞馬遜全能工具 V18", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# 侧边栏导航：物理隔离功能
mode = st.sidebar.radio("功能導航", ["批量上架 (圖片分析)", "站點搬運 (US ➔ UK)"])

# ==========================================
# 模式一：批量上架 (規格鎖定版)
# ==========================================
if mode == "批量上架 (圖片分析)":
    st.header("🎨 AI 視覺分析上架")
    with st.sidebar:
        st.subheader("⚙️ 規格鎖定")
        brand = st.text_input("品牌名稱", "AMAZING WALL")
        s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("價格 1", "12.99")
        s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("價格 2", "16.99")
        s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("價格 3", "19.99")

    pfx = st.text_input("SKU 前綴 (例: SQDQ-BH-087)")
    img_file = st.file_uploader("上傳分析圖")
    tpl_file = st.file_uploader("上傳 Amazon 模板", key="tpl_us")

    if st.button("🚀 啟動填充", type="primary") and img_file and tpl_file and api_key:
        try:
            # 重置指针防止读取失败
            img_file.seek(0)
            b64 = base64.b64encode(img_file.read()).decode('utf-8')
            client = OpenAI(api_key=api_key)
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                response_format={"type":"json_object"}
            )
            ai = json.loads(res.choices[0].message.content)
            
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            
            # 规则：Row 4 锁定为父体，解决红框缺失
            p_sku = f"{pfx}-001-003"
            rows = [
                {"t":"P", "s":p_sku, "sz":"", "pr":""},
                {"t":"C", "s":f"{pfx}-001", "sz":s1, "pr":p1},
                {"t":"C", "s":f"{pfx}-002", "sz":s2, "pr":p2},
                {"t":"C", "s":f"{pfx}-003", "sz":s3, "pr":p3}
            ]

            for i, r_data in enumerate(rows):
                target_row = 4 + i
                def fill(k, v):
                    col = [idx for name, idx in h.items() if k.lower().replace(" ", "") in name]
                    if col: sheet.cell(row=target_row, column=col[0], value=clean_text(v))

                fill("sellersku", r_data["s"])
                fill("parentsku", p_sku)
                if r_data["t"] == "C":
                    color_v = f"{ai.get('color','')} {ai.get('elements','')}"
                    fill("color", color_v)
                    fill("colormap", color_v) # 镜像同步
                    fill("size", r_data["sz"])
                    fill("sizemap", r_data["sz"])
                    fill("standardprice", r_data["pr"])
                fill("productname", f"{brand} {ai.get('title','')} {ai.get('elements','')}"[:199])
                for bi in range(5):
                    fill(f"keyproductfeatures{bi+1}", ai['bp'][bi] if bi < len(ai['bp']) else "")

            out = io.BytesIO()
            wb.save(out)
            st.success("✅ AI 填充完成！")
            st.download_button("💾 下載上架文件", out.getvalue(), f"{pfx}_US.xlsm")
        except Exception as e:
            st.error(f"❌ 報錯: {e}")

# ==========================================
# 模式二：站點搬運 (極簡全表對位方案)
# ==========================================
elif mode == "站點搬運 (US ➔ UK)":
    st.header("🌍 跨站點極簡搬運")
    st.info("系統會自動對位搬運相同列名的數據，並轉換 Colour 等拼寫。")
    
    us_data = st.file_uploader("📂 1. 上傳已填好的 US 文件")
    uk_tpl = st.file_uploader("📂 2. 上傳空白 UK 模板")

    if st.button("🚀 執行自動搬運", type="primary") and us_data and uk_tpl:
        try:
            # 基于 Pandas 的高效搬运
            us_df = pd.read_excel(us_data, header=2)
            uk_wb = openpyxl.load_workbook(uk_tpl, keep_vba=True)
            uk_sheet = uk_wb.active
            uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[3] if c.value}

            # 字段自动适配映射
            mapping = {"generickeywords": "searchterms", "productname": "itemname", "color": "colour", "colormap": "colourmap"}

            for col in us_df.columns:
                src_name = str(col).strip().lower().replace(" ", "")
                tgt_name = mapping.get(src_name, src_name)
                
                if tgt_name in uk_h:
                    col_idx = uk_h[tgt_name]
                    for r_idx, val in enumerate(us_df[col], start=4):
                        uk_sheet.cell(row=r_idx, column=col_idx, value=clean_text(val))

            out_uk = io.BytesIO()
            uk_wb.save(out_uk)
            st.success("✅ 站點搬運完成！")
            st.download_button("💾 下載英國站文件", out_uk.getvalue(), "Amazon_UK.xlsm")
        except Exception as e:
            st.error(f"❌ 搬運失敗: {e}")
