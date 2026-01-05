import streamlit as st
import pandas as pd
import io, base64, json, re, openpyxl
from openai import OpenAI

# --- 1. 核心过滤工具 (物理剔除占位符) ---
def final_clean(text):
    if not text: return ""
    # 移除 JSON 括号和引号
    text = re.sub(r"[\[\]'\"']", "", str(text))
    # 物理过滤黑名单占位词
    blacklist = {'word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich'}
    words = text.split()
    return " ".join([w for w in words if w.lower() not in blacklist]).strip()

# --- 2. 页面配置 ---
st.set_page_config(page_title="亞馬遜 V12.0 穩定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 3. 规格配置 ---
with st.sidebar:
    brand = st.text_input("品牌", value="AMAZING WALL")
    s1, p1 = st.text_input("尺寸1", "16x24\""), st.text_input("价格1", "12.99")
    s2, p2 = st.text_input("尺寸2", "24x36\""), st.text_input("价格2", "16.99")
    s3, p3 = st.text_input("尺寸3", "32x48\""), st.text_input("价格3", "19.99")

# --- 4. 款式录入 ---
if 'rows' not in st.session_state: st.session_state.rows = 1
items = []
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
            u1, u2, u3 = st.text_input("S1图", key=f"u1_{i}"), st.text_input("S2图", key=f"u2_{i}"), st.text_input("S3图", key=f"u3_{i}")
        items.append({"pfx": pfx, "img": img, "main": m_u, "sz_urls": [u1, u2, u3]})

if st.button("➕ 增加款式"):
    st.session_state.rows += 1
    st.rerun()

user_kw = st.text_area("通用词库")
tpl_file = st.file_uploader("📂 上传模板", type=['xlsx', 'xlsm'], key="tpl_v12")

# --- 5. 核心逻辑：解决红框与空行 ---
if st.button("🚀 启动自动化填充", type="primary"):
    if not tpl_file or not api_key:
        st.error("请检查模板与 API 配置")
    else:
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            
            client = OpenAI(api_key=api_key)
            curr_row = 5 # 子体从第5行开始

            for idx, item in enumerate(items):
                if not item["pfx"] or not item["img"]: continue
                
                # 修复图 5c2b：文件流指针重置
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)

                # 规则锁定：Parent SKU 命名
                p_sku = f"{item['pfx']}" # 假设单款式
                
                # 写入 1父 + 3子
                data_map = [
                    {"type": "P", "sku": p_sku, "sz": "", "pr": ""},
                    {"type": "C", "sku": f"{item['pfx']}-{s1.replace('\"','')}", "sz": s1, "pr": p1, "id": 0},
                    {"type": "C", "sku": f"{item['pfx']}-{s2.replace('\"','')}", "sz": s2, "pr": p2, "id": 1},
                    {"type": "C", "sku": f"{item['pfx']}-{s3.replace('\"','')}", "sz": s3, "pr": p3, "id": 2}
                ]

                for row in data_map:
                    # 锁定：父体行强制写入 Row 4，解决红框缺失
                    target_row = 4 if row["type"] == "P" else curr_row
                    
                    def fill(k, v):
                        targets = [i for name, i in h.items() if k.lower().replace(" ", "") in name]
                        if targets: sheet.cell(row=target_row, column=targets[0], value=final_clean(v))

                    fill("sellersku", row["sku"])
                    fill("parentsku", p_sku)
                    
                    # 属性镜像同步 (Color = Color Map)
                    if row["type"] == "C":
                        full_color = f"{ai.get('color','')} {ai.get('elements','')}"
                        fill("color", full_color)
                        fill("colormap", full_color)
                        fill("size", row["sz"])
                        fill("sizemap", row["sz"])
                        fill("standardprice", row["pr"])

                    # 标题文案处理
                    title = f"{brand} {ai.get('title','')} {ai.get('elements','')}"
                    if row["type"] == "C": title += f" - {row['sz']}"
                    fill("productname", title[:199])
                    fill("generickeyword", final_clean(f"{ai.get('elements','')} {user_kw}"))

                    # 五点描述全覆盖
                    for b_i in range(5):
                        fill(f"keyproductfeatures{b_i+1}", ai['bp'][b_i] if b_i < len(ai['bp']) else "High-quality decor.")

                    if row["type"] == "C": curr_row += 1

            st.success("✅ 处理完成！")
            out = io.BytesIO()
            wb.save(out)
            st.download_button("💾 点击下载修复版表格", out.getvalue(), "Final_Locked_V12.xlsm")

        except Exception as e:
            st.error(f"严重报错：{e}")
