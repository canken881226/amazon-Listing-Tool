import streamlit as st
import pandas as pd
import io, os, re, base64, json
import openpyxl
from openai import OpenAI

# --- 1. 核心规格强制执行器 (SOP Validator) ---
class StrictSOP:
    @staticmethod
    def clean_text(text):
        """强制清理乱码"""
        if pd.isna(text) or str(text).strip() == "": return ""
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_kw(elements, pool):
        """规则：元素词+通用词，严禁标点，仅空格"""
        raw = f"{elements} {pool}"
        return " ".join(re.sub(r'[^a-zA-Z0-9\s]', ' ', raw).split())

# --- 2. 界面与配置 ---
st.set_page_config(page_title="亚马逊批量专家 V10.0", layout="wide")
st.title("🚀 亚马逊 Listing 规格终极锁定工具")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

with st.sidebar:
    st.header("⚙️ 规则锚点")
    brand = st.text_input("品牌", "AMAZING WALL")
    # 尺寸与价格锁定
    v1_s, v1_p, v1_n = st.text_input("尺寸1", "16x24\""), st.text_input("售价1", "12.99"), "001"
    v2_s, v2_p, v2_n = st.text_input("尺寸2", "24x36\""), st.text_input("售价2", "16.99"), "002"
    v3_s, v3_p, v3_n = st.text_input("尺寸3", "32x48\""), st.text_input("售价3", "19.99"), "003"

# --- 3. 核心功能：款式对位 ---
if 'rows' not in st.session_state: st.session_state.rows = 1
sku_data = []

for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1} 配置", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            prefix = st.text_input("SKU 前缀", key=f"p_{i}", placeholder="例: SQDQ-BH-XMT-XFWS-082")
            img = st.file_uploader("分析图", key=f"f_{i}")
        with c2:
            m_url = st.text_input("主图 URL", key=f"m_{i}")
            o_urls = st.text_area("附图集", key=f"o_{i}")
        with c3:
            u1 = st.text_input(f"{v1_s} 图片", key=f"u1_{i}")
            u2 = st.text_input(f"{v2_s} 图片", key=f"u2_{i}")
            u3 = st.text_input(f"{v3_s} 图片", key=f"u3_{i}")
        sku_data.append({"prefix": prefix, "img": img, "main": m_url, "others": o_urls, "sz_urls": [u1, u2, u3]})

if st.button("➕ 增加款式"):
    st.session_state.rows += 1
    st.rerun()

user_kw = st.text_area("Search Terms 词库")
uploaded_tpl = st.file_uploader("👉 最后一步：上传你的模板 Excel 文件", type=['xlsx', 'xlsm'])

# --- 4. 自动化生成逻辑 ---
if st.button("🚀 强制按规执行生成", use_container_width=True):
    if not uploaded_tpl or not api_key:
        st.error("请先上传模板并配置 API Key")
    else:
        try:
            with st.status("正在锁定规格写入...") as status:
                # 解决 FileNotFoundError：直接从内存读取上传的模板
                wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
                sheet = wb.active
                h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                
                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_data:
                    if not item["prefix"] or not item["img"]: continue
                    
                    # AI 分析
                    img_b64 = base64.b64encode(item["file"].read()).decode('utf-8')
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":"Analyze art. JSON: {'title':'Rich description','elements':'keywords','color':'color_name','bp':['bp1','bp2','bp3','bp4','bp5']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}],
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)

                    # 规格锁定：Parent SKU 范围
                    p_sku = f"{item['prefix']}-{v1_n}-{v3_n}"
                    
                    # 写入序列：1行父 + 3行子
                    data_rows = [
                        {"type": "Parent", "sku": p_sku, "sz": "", "pr": "", "id": -1},
                        {"type": "Child", "sku": f"{item['prefix']}-{v1_n}", "sz": v1_s, "pr": v1_p, "id": 0},
                        {"type": "Child", "sku": f"{item['prefix']}-{v2_n}", "sz": v2_s, "pr": v2_p, "id": 1},
                        {"type": "Child", "sku": f"{item['prefix']}-{v3_n}", "sz": v3_s, "pr": v3_p, "id": 2}
                    ]

                    for r in data_rows:
                        def fill(key, value):
                            targets = [c_idx for name, c_idx in h.items() if key.lower() in name]
                            if targets:
                                sheet.cell(row=curr_row, column=targets[0], value=StrictSOP.clean_text(value))

                        # 规则1：Seller/Parent SKU
                        fill("seller sku", r["sku"])
                        fill("parent sku", p_sku)

                        # 规则2：Color & Color Map 镜像同步 (解决截图红框)
                        full_color = f"{ai['color']} {ai['elements']}"
                        fill("color", full_color)
                        fill("color map", full_color)
                        
                        # 规则3：Size & Size Map 同步
                        if r["type"] == "Child":
                            fill("size", r["sz"])
                            fill("size map", r["sz"])
                            fill("sale price", r["pr"])

                        # 规则4：五点描述全覆盖 (解决截图空白)
                        bps = ai.get('bp', [])
                        while len(bps) < 5: bps.append("Quality art piece for modern decor.")
                        for b_i in range(5):
                            fill(f"key product features{b_i+1}", bps[b_i])

                        # 规则5：标题增强
                        title = f"{brand} {ai['title']} {ai['elements']}"
                        if r["type"] == "Child": title += f" - {r['sz']}"
                        fill("product name", title[:199])

                        # 规则6：关键词格式化
                        fill("generic keyword", StrictSOP.format_kw(ai['elements'], user_kw))

                        fill("main_image_url", item["main"])
                        curr_row += 1

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载修正版 Excel", output.getvalue(), "Listing_Final_SOP.xlsm")
        except Exception as e:
            st.error(f"出错原因: {e}")
