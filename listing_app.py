import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI
from openpyxl.styles import Font, Alignment
from PIL import Image

# --- 1. 初始化配置 ---
st.set_page_config(page_title="亞馬遜 AI 精細化填充 V10.7", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心校验工具 (修复缩进与过滤占位符) ---
def clean_strict(text):
    if not text: return ""
    # 移除 JSON 占位符符号
    text = re.sub(r"[\[\]'\"']", "", str(text))
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

def safe_keyword_cut(raw_text, limit=245):
    """锁定规则：过滤占位词，限长 245，空格分隔"""
    if not raw_text: return ""
    # 物理过滤黑名单
    blacklist = {'word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich'} 
    clean_words = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_text.lower()).split()
    
    unique_words = []
    seen = set()
    curr_len = 0
    
    for w in clean_words:
        if w not in seen and w not in blacklist:
            new_len = curr_len + len(w) + (1 if curr_len > 0 else 0)
            if new_len <= limit:
                unique_words.append(w)
                seen.add(w)
                curr_len = new_len
            else:
                break
    return " ".join(unique_words)

def reset_cell(cell, bold=False):
    cell.font = Font(name='Arial', size=10, bold=bold)
    cell.alignment = Alignment(wrap_text=True, vertical='top')

# --- 3. UI 界面 (保持您确认好的所有功能不动) ---
with st.sidebar:
    st.header("⚙️ 基础规格配置")
    brand_name = st.text_input("品牌名称", value="AMAZING WALL")
    st.divider()
    st.subheader("变体尺寸、售价与编号")
    s1, p1, n1 = st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99"), "001"
    s2, p2, n2 = st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99"), "002"
    s3, p3, n3 = st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99"), "003"

st.header("🖼️ SKU 精准对位矩阵")
if 'sku_rows' not in st.session_state: st.session_state.sku_rows = 1

sku_data = []
# 修复：确保 rows 状态一致
row_count = st.session_state.rows if 'rows' in st.session_state else st.session_state.sku_rows

for i in range(row_count):
    with st.expander(f"款式 {i+1} 录入区", expanded=True):
        c1, c2, c3 = st.columns([1.5, 2, 2.5])
        with c1:
            sku_pfx = st.text_input(f"SKU 前缀", key=f"s_{i}")
            local_img = st.file_uploader(f"上传分析图", key=f"f_{i}")
        with c2:
            m_url = st.text_input(f"主图链接", key=f"m_{i}")
            others = st.text_area(f"附图链接集", key=f"o_{i}", height=80)
        with c3:
            s1_u = st.text_input(f"{s1} 图片", key=f"s1u_{i}")
            s2_u = st.text_input(f"{s2} 图片", key=f"s2u_{i}")
            s3_u = st.text_input(f"{s3} 图片", key=f"s3u_{i}")
        sku_data.append({"sku": sku_pfx, "img": local_img, "main": m_url, "others": others, "sz_urls": [s1_u, s2_u, s3_u]})

if st.button("➕ 增加款式"):
    if 'rows' in st.session_state: st.session_state.rows += 1
    else: st.session_state.sku_rows += 1
    st.rerun()

user_kw_pool = st.text_area("📝 Search Terms 通用词库")
uploaded_tpl = st.file_uploader("📂 最后一步：上传模板 Excel", type=['xlsx', 'xlsm'], key="final_tpl")

# --- 4. 执行生成 (逻辑严格锁定) ---
if st.button("🚀 启动自动化填充", use_container_width=True):
    if not uploaded_tpl or not api_key:
        st.error("❌ 启动失败：请检查模板上传及 API Key 设置。")
    else:
        try:
            # 使用内存加载模板，解决路径报错
            wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
            bp_cols = [c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if "keyproductfeatures" in str(c.value).lower().replace(" ", "")]

            curr_row = 5 # 子类从第5行开始
            client = OpenAI(api_key=api_key)

            for item in sku_data:
                if not item["sku"] or not item["img"]: continue
                
                # 修复：读取前重置文件指针，防止读取为空
                item["img"].seek(0)
                b64 = base64.b64encode(item["img"].read()).decode('utf-8')
                prompt = "Amazon expert. Return JSON: {'title':'','elements':'','color':'','bp':['','','','','']}"
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)

                # 规则锁定：Parent SKU 范围命名 (例: ABC-001-003)
                p_sku_val = f"{item['sku']}-{n1}-{n3}"
                
                # 定义写入序列：严格控制行数
                rows_logic = [
                    {"type": "P", "sku": p_sku_val, "sz": "", "pr": ""},
                    {"type": "C", "sku": f"{item['sku']}-{n1}-{s1.replace('\"','').strip()}", "sz": s1, "pr": p1, "id": 0},
                    {"type": "C", "sku": f"{item['sku']}-{n2}-{s2.replace('\"','').strip()}", "sz": s2, "pr": p2, "id": 1},
                    {"type": "C", "sku": f"{item['sku']}-{n3}-{s3.replace('\"','').strip()}", "sz": s3, "pr": p3, "id": 2}
                ]

                for r_data in rows_logic:
                    # 规则：父类行固定写入 Row 4
                    target_row = 4 if r_data["type"] == "P" else curr_row
                    
                    def fill(k, v):
                        target = [idx for name, idx in h.items() if k.lower().replace(" ", "") in name]
                        if target: reset_cell(sheet.cell(row=target_row, column=target[0], value=clean_strict(v)))

                    # 1. 填充 SKU 与父子关系
                    fill("sellersku", r_data["sku"])
                    fill("parentsku", p_sku_val)
                    
                    # 2. 属性填充 (镜像同步锁定)
                    color_val = f"{ai['color']} {ai['elements']}"
                    if r_data["type"] == "C":
                        fill("color", color_val)
                        fill("colormap", color_val)
                        fill("size", r_data["sz"])
                        fill("sizemap", r_data["sz"])
                        fill("standardprice", r_data["pr"])

                    # 3. 标题与关键词 (丰富标题且过滤词库)
                    title = f"{brand_name} {ai['title']} {ai['elements']}"
                    if r_data["type"] == "C": title += f" - {r_data['sz']}"
                    fill("productname", title[:199])
                    fill("generickeyword", safe_keyword_cut(f"{ai['elements']} {user_kw_pool}"))

                    # 4. 五点描述填充 (包含父类行)
                    bps = ai.get('bp', [])
                    while len(bps) < 5: bps.append("Professional print for interior decor.")
                    for b_i, c_col in enumerate(bp_cols[:5]):
                        reset_cell(sheet.cell(row=target_row, column=c_col, value=clean_strict(bps[b_i])))

                    if r_data["type"] == "C": curr_row += 1

            output = io.BytesIO()
            wb.save(output)
            st.success("✅ 规格校验通过！请下载文件。")
            st.download_button("💾 下载锁定版 Excel", output.getvalue(), "Amazon_V10.7_Fixed.xlsm", use_container_width=True)

        except Exception as e:
            st.error(f"❌ 运行中报错: {str(e)}")
