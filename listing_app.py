import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl
from openai import OpenAI
from openpyxl.styles import Font

# --- 1. 核心安全工具 ---
def safe_clean(text):
    if not text: return ""
    # 物理剔除所有 AI 占位词及 JSON 符号
    text = re.sub(r"[\[\]'\"']", "", str(text))
    blacklist = ['word1', 'word2', 'fake', 'placeholder']
    words = text.split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# --- 2. 页面配置 ---
st.set_page_config(page_title="亞馬遜 V11.0 穩定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 3. 规格定义 (保持原有界面) ---
with st.sidebar:
    st.header("⚙️ 规格锁定")
    brand = st.text_input("品牌名称", value="AMAZING WALL")
    st.divider()
    s1, p1, n1 = st.text_input("尺寸1", "16x24\""), st.text_input("价格1", "12.99"), "001"
    s2, p2, n2 = st.text_input("尺寸2", "24x36\""), st.text_input("价格2", "19.99"), "002"
    s3, p3, n3 = st.text_input("尺寸3", "32x48\""), st.text_input("价格3", "29.99"), "003"

# --- 4. 款式录入 (强制使用独立 Key) ---
if 'rows' not in st.session_state: st.session_state.rows = 1
sku_data = []

for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1}", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            pfx = st.text_input("SKU前缀", key=f"pfx_{i}")
            img = st.file_uploader("分析图", key=f"img_{i}")
        with c2:
            m_u = st.text_input("主图URL", key=f"mu_{i}")
            o_u = st.text_area("附图集", key=f"ou_{i}")
        with c3:
            u1, u2, u3 = st.text_input(f"S1图", key=f"u1_{i}"), st.text_input(f"S2图", key=f"u2_{i}"), st.text_input(f"S3图", key=f"u3_{i}")
        sku_data.append({"pfx": pfx, "img": img, "main": m_u, "sz_u": [u1, u2, u3]})

if st.button("➕ 增加款式"):
    st.session_state.rows += 1
    st.rerun()

user_kw = st.text_area("通用词库")
uploaded_tpl = st.file_uploader("📂 上传模板", type=['xlsx', 'xlsm'], key="tpl_main")

# --- 5. 执行逻辑 (修复缩进与 Seller SKU 缺失) ---
if st.button("🚀 启动自动化填充", type="primary"):
    if not uploaded_tpl or not api_key:
        st.error("请确保模板已上传且 API Key 正确")
    else:
        try:
            # 解决截图中的空行问题，锁定写入起始行
            wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            
            client = OpenAI(api_key=api_key)
            curr_row = 5 # 子体起始行

            for item in sku_data:
                if not item["pfx"] or not item["img"]: continue
                
                # 图像处理并分析
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)

                # 规格：计算 Parent SKU
                p_sku = f"{item['pfx']}-{n1}-{n3}"
                
                # 填充序列：1父 + 3子
                rows = [
                    {"type": "P", "sku": p_sku, "sz": "", "pr": ""},
                    {"type": "C", "sku": f"{item['pfx']}-{n1}", "sz": s1, "pr": p1, "idx": 0},
                    {"type": "C", "sku": f"{item['pfx']}-{n2}", "sz": s2, "pr": p2, "idx": 1},
                    {"type": "C", "sku": f"{item['pfx']}-{n3}", "sz": s3, "pr": p3, "idx": 2}
                ]

                for r in rows:
                    target_row = 4 if r["type"] == "P" else curr_row
                    
                    def fill(k, v):
                        cols = [i for name, i in h.items() if k.lower().replace(" ", "") in name]
                        if cols: sheet.cell(row=target_row, column=cols[0], value=safe_clean(v))

                    # 1. 强制写入 SKU (解决截图红框)
                    fill("sellersku", r["sku"])
                    fill("parentsku", p_sku)
                    
                    # 2. 颜色与镜像 (仅子体填)
                    if r["type"] == "C":
                        fill("color", f"{ai['color']} {ai['elements']}")
                        fill("colormap", f"{ai['color']} {ai['elements']}")
                        fill("size", r["sz"])
                        fill("sizemap", r["sz"])
                        fill("standardprice", r["pr"])

                    # 3. 标题与五点 (全填)
                    title = f"{brand} {ai['title']} {ai['elements']}"
                    if r["type"] == "C": title += f" - {r['sz']}"
                    fill("productname", title[:199])
                    
                    for b_i in range(5):
                        fill(f"keyproductfeatures{b_i+1}", ai['bp'][b_i] if b_i < len(ai['bp']) else "")

                    if r["type"] == "C": curr_row += 1

            output = io.BytesIO()
            wb.save(output)
            st.success("✅ 处理完成！")
            st.download_button("💾 下载 Excel", output.getvalue(), "Amazon_V11_Stable.xlsm")

        except Exception as e:
            st.error(f"出错原因: {str(e)}")
