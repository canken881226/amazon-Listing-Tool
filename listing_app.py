import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI
from openpyxl.styles import Font, Alignment
from PIL import Image

# --- 1. 基础环境配置 ---
st.set_page_config(page_title="亞馬遜 V10.8 終極穩定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心规格校验器 (SOP) ---
class SOP_Guard:
    @staticmethod
    def clean(text):
        """防止乱码及JSON残留"""
        if not text: return ""
        text = re.sub(r"[\[\]'\"']", "", str(text))
        return text.encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_kw(elements, pool):
        """规则：元素词+通用词，严禁标点，仅空格，限245字符"""
        raw = f"{elements} {pool}"
        # 物理剔除占位符
        blacklist = {'word1', 'word2', 'fake', 'placeholder', 'rich'}
        words = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw.lower()).split()
        res = []
        seen = set()
        for w in words:
            if w not in seen and w not in blacklist and len(w) > 1:
                res.append(w)
                seen.add(w)
        return " ".join(res)[:245]

# --- 3. UI 界面 (保持您确认的所有功能) ---
with st.sidebar:
    st.header("⚙️ 规格锁定配置")
    brand = st.text_input("品牌", value="AMAZING WALL")
    st.divider()
    st.subheader("变体定义")
    v1_s, v1_p, v1_n = st.text_input("尺寸1", "16x24\""), st.text_input("售价1", "12.99"), "001"
    v2_s, v2_p, v2_n = st.text_input("尺寸2", "24x36\""), st.text_input("售价2", "19.99"), "002"
    v3_s, v3_p, v3_n = st.text_input("尺寸3", "32x48\""), st.text_input("售价3", "19.99"), "003"

st.header("🖼️ 款式录入矩阵")
if 'num_styles' not in st.session_state: st.session_state.num_styles = 1

sku_inputs = []
for i in range(st.session_state.num_styles):
    with st.expander(f"款式 {i+1}", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            prefix = st.text_input("SKU 前缀", key=f"prefix_{i}")
            img_file = st.file_uploader("分析图", key=f"file_{i}")
        with c2:
            m_url = st.text_input("主图 URL", key=f"main_{i}")
            o_urls = st.text_area("附图集", key=f"others_{i}")
        with c3:
            u1 = st.text_input(f"{v1_s} 图", key=f"u1_{i}")
            u2 = st.text_input(f"{v2_s} 图", key=f"u2_{i}")
            u3 = st.text_input(f"{v3_s} 图", key=f"u3_{i}")
        sku_inputs.append({"pfx": prefix, "file": img_file, "main": m_url, "others": o_urls, "sz_urls": [u1, u2, u3]})

if st.button("➕ 增加款式"):
    st.session_state.num_styles += 1
    st.rerun()

user_kw = st.text_area(" Search Terms 词库")
tpl_file = st.file_uploader("📂 最后一步：上传 Amazon 模板", type=['xlsx', 'xlsm'], key="tpl_upload")

# --- 4. 自动化生成 (逻辑闭环) ---
if st.button("🚀 启动自动化填充", use_container_width=True, type="primary"):
    if not tpl_file or not api_key:
        st.error("❌ 错误：必须上传模板并确保 API Key 已配置。")
    else:
        try:
            # 解决静默停止：引入状态监控
            status_area = st.empty()
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            bp_cols = [c.column for r in sheet.iter_rows(max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]
            
            client = OpenAI(api_key=api_key)
            curr_row = 5 # 子类从第5行开始

            for idx, item in enumerate(sku_inputs):
                if not item["pfx"] or not item["file"]: continue
                
                status_area.info(f"正在处理款式 ({idx+1}/{len(sku_inputs)}): {item['pfx']}")
                
                # 核心：复位图片指针
                item["file"].seek(0)
                b64 = base64.b64encode(item["file"].read()).decode('utf-8')
                prompt = "Analyze art. JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)

                # 规则锁定：Parent SKU 范围命名
                p_sku = f"{item['pfx']}-{v1_n}-{v3_n}"
                
                # 严格行逻辑：1父 + 3子
                rows_data = [
                    {"type": "P", "sku": p_sku, "sz": "", "pr": "", "id": -1},
                    {"type": "C", "sku": f"{item['pfx']}-{v1_n}-{v1_s.replace('\"','').strip()}", "sz": v1_s, "pr": v1_p, "id": 0},
                    {"type": "C", "sku": f"{item['pfx']}-{v2_n}-{v2_s.replace('\"','').strip()}", "sz": v2_s, "pr": v2_p, "id": 1},
                    {"type": "C", "sku": f"{item['pfx']}-{v3_n}-{v3_s.replace('\"','').strip()}", "sz": v3_s, "pr": v3_p, "id": 2}
                ]

                for row in rows_data:
                    # 第一行(父体)固定 Row 4
                    target_row = 4 if row["type"] == "P" else curr_row
                    
                    def fill(k, v):
                        cols = [i for name, i in h.items() if k.lower().replace(" ", "") in name]
                        if cols:
                            cell = sheet.cell(row=target_row, column=cols[0], value=SOP_Guard.clean(v))
                            cell.font = Font(name='Arial', size=10)
                            cell.alignment = Alignment(wrap_text=True, vertical='top')

                    # 1. SKU 对位
                    fill("sellersku", row["sku"])
                    fill("parentsku", p_sku)

                    # 2. 属性同步 (镜像锁定)
                    color_val = f"{ai['color']} {ai['elements']}"
                    if row["type"] == "C":
                        fill("color", color_val)
                        fill("colormap", color_val) # 强制一致
                        fill("size", row["sz"])
                        fill("sizemap", row["sz"])
                        fill("standardprice", row["pr"])

                    # 3. 标题与关键词
                    title = f"{brand} {ai['title']} {ai['elements']}"
                    if row["type"] == "C": title += f" - {row['sz']}"
                    fill("productname", title[:199])
                    fill("generickeyword", SOP_Guard.format_kw(ai['elements'], user_kw))

                    # 4. 五点描述 (所有行必填)
                    bps = ai.get('bp', [])
                    while len(bps) < 5: bps.append("Standard high-quality product feature.")
                    for b_i, c_col in enumerate(bp_cols[:5]):
                        sheet.cell(row=target_row, column=c_col, value=SOP_Guard.clean(bps[b_i]))

                    if row["type"] == "C": curr_row += 1

            status_area.success("✅ 处理成功！请下载。")
            out = io.BytesIO()
            wb.save(out)
            st.download_button("💾 下载最终规格锁定版", out.getvalue(), "Amazon_Locked_SOP.xlsm")

        except Exception as e:
            st.error(f"❌ 运行报错: {str(e)}")
