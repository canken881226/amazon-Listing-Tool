import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 自动计算促销时间 ---
today = datetime.now()
auto_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
auto_end_date = ((today - timedelta(days=1)) + timedelta(days=365)).strftime("%Y-%m-%d")

st.set_page_config(page_title="亚马逊 AI 专家 V10.0 - 终极锁定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心校验逻辑 (SOP) ---
class ListingValidator:
    @staticmethod
    def clean(text):
        if not text: return ""
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_kw(elements, pool):
        combined = f"{elements} {pool}"
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', combined)
        return " ".join(clean.split())

# --- 3. 侧边栏：规格固定 ---
with st.sidebar:
    st.header("⚙️ 规格锁定中心")
    brand_name = st.text_input("品牌名称", "YourBrand")
    
    # 允许上传模板文件到 templates 文件夹
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板文件", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("变体规格定义")
    v1_s, v1_p, v1_n = st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99"), "001"
    v2_s, v2_p, v2_n = st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99"), "002"
    v3_s, v3_p, v3_n = st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99"), "003"

# --- 4. 核心功能：款式对位矩阵 ---
st.header("🖼️ SKU 视觉对位矩阵 (全功能版)")
if 'rows' not in st.session_state: st.session_state.rows = 1

sku_data = []
for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1} 配置区", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            b_sku = st.text_input(f"SKU 前缀 (例: SQDQ-BH-XFCT)", key=f"bs_{i}")
            img_file = st.file_uploader(f"上传分析图 (AI 识别用)", key=f"f_{i}")
        with c2:
            m_url = st.text_input(f"主图链接", key=f"mu_{i}")
            o_urls = st.text_area(f"附图链接集", key=f"ou_{i}")
        with c3:
            z1 = st.text_input(f"{v1_s} 图片链接", key=f"z1_{i}")
            z2 = st.text_input(f"{v2_s} 图片链接", key=f"z2_{i}")
            z3 = st.text_input(f"{v3_s} 图片链接", key=f"z3_{i}")
        sku_data.append({"base": b_sku, "file": img_file, "main": m_url, "others": o_urls, "sz_urls": [z1, z2, z3]})

if st.button("➕ 增加款式"):
    st.session_state.rows += 1
    st.rerun()

user_kw_pool = st.text_area("📝 通用关键词池 (Search Terms)")

# --- 5. 执行处理 (融合 V9.7 逻辑与 V9.9 稳定性) ---
if st.button("🚀 启动自动化生成 (锁定规则)", use_container_width=True):
    if not selected_tpl or not api_key:
        st.error("请检查模板选择和 API Key 配置")
    else:
        try:
            with st.status("正在执行 AI 分析与规格校验...") as status:
                # 修复路径问题：使用 BytesIO 读取
                with open(os.path.join("templates", selected_tpl), "rb") as f:
                    template_data = f.read()
                wb = openpyxl.load_workbook(io.BytesIO(template_data), keep_vba=True)
                sheet = wb.active
                
                h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_data:
                    if not item["base"] or not item["file"]: continue
                    
                    # AI 视觉分析
                    img_b64 = base64.b64encode(item["file"].read()).decode('utf-8')
                    prompt = "Analyze art pattern. JSON: {'title':'Rich title with style/theme/material','elements':'pattern element words','color':'main color','bp':['Header: content',...5 items]}"
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}],
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)

                    # --- 核心规则执行 ---
                    parent_range_sku = f"{item['base']}-{v1_n}-{v3_n}"
                    
                    # 定义四行数据：1行父体 + 3行子体
                    rows_to_fill = [
                        {"type": "Parent", "sku": parent_range_sku, "size": "", "price": "", "idx": -1},
                        {"type": "Child", "sku": f"{item['base']}-{v1_n}", "size": v1_s, "price": v1_p, "idx": 0},
                        {"type": "Child", "sku": f"{item['base']}-{v2_n}", "size": v2_s, "price": v2_p, "idx": 1},
                        {"type": "Child", "sku": f"{item['base']}-{v3_n}", "size": v3_s, "price": v3_p, "idx": 2}
                    ]

                    for r in rows_to_fill:
                        def fill(key, value):
                            targets = [c_idx for c_name, c_idx in h.items() if key.lower() in c_name]
                            if targets:
                                sheet.cell(row=curr_row, column=targets[0], value=ListingValidator.clean(value))

                        # 1. SKU 逻辑锁定 (第一行 Seller=Parent)
                        fill("seller sku", r["sku"])
                        fill("parent sku", parent_range_sku)

                        # 2. 镜像必填项同步
                        full_color = f"{ai['color']} {ai['elements']}"
                        fill("color", full_color)
                        fill("color map", full_color)
                        
                        if r["type"] == "Child":
                            fill("size", r["size"])
                            fill("size map", r["size"])
                            fill("sale price", r["price"])

                        # 3. 五点描述锁定 (所有行必填且防乱码)
                        bps = ai.get('bp', [])
                        while len(bps) < 5: bps.append("High-quality design with premium materials.")
                        for b_i in range(5):
                            fill(f"key product features{b_i+1}", bps[b_i])

                        # 4. 标题丰富度控制
                        title_base = f"{brand_name} {ai['title']} {ai['elements']}"
                        final_title = f"{title_base} - {r['size']}" if r["type"] == "Child" else title_base
                        fill("product name", final_title[:199])

                        # 5. 关键词格式化
                        fill("generic keyword", ListingValidator.format_kw(ai['elements'], user_kw_pool))
                        
                        # 基础字段
                        fill("main_image_url", item["main"])
                        fill("sale start date", auto_start_date)
                        fill("sale end date", auto_end_date)
                        if r["type"] == "Child" and item["sz_urls"][r["idx"]]:
                            fill("other_image_url1", item["sz_urls"][r["idx"]])

                        curr_row += 1

                status.update(label="✅ 处理成功！规格已锚定。", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载最终规格锁定版表格", output.getvalue(), f"Listing_Fixed_{datetime.now().strftime('%m%d%H%M')}.xlsm")
            
        except Exception as e:
            st.error(f"❌ 运行失败: {str(e)}")
