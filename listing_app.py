import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 自动日期逻辑 ---
today = datetime.now()
auto_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
auto_end_date = ((today - timedelta(days=1)) + timedelta(days=365)).strftime("%Y-%m-%d")

st.set_page_config(page_title="亚马逊 AI 专家 V9.7 - 深度对位版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心规则校验器 ---
class ListingValidator:
    @staticmethod
    def clean(text):
        if not text: return ""
        # 彻底清洗乱码并确保字符串格式
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_keywords(elements, pool):
        """规则：元素词+通用词，空格间隔"""
        combined = f"{elements} {pool}"
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', combined)
        return " ".join(clean.split())

# --- 3. 侧边栏：规格定义 ---
with st.sidebar:
    st.header("⚙️ 规格锁定")
    brand_name = st.text_input("品牌名称", "YourBrand")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板", tpl_list)
    
    st.divider()
    st.subheader("变体尺寸/定价/编号")
    # 编号用于 SKU 范围生成，例如 001, 002
    v1_s, v1_p, v1_n = st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99"), "001"
    v2_s, v2_p, v2_n = st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99"), "002"
    v3_s, v3_p, v3_n = st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99"), "003"

# --- 4. 款式对位录入 ---
st.header("🖼️ SKU 对位录入矩阵")
if 'rows' not in st.session_state: st.session_state.rows = 2
sku_list = []

for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1}", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            # 用户输入 SKU 前缀，如 SQDQ-BH-XFCT
            b_sku = st.text_input(f"SKU 前缀", key=f"bs_{i}", placeholder="例如: SQDQ-BH-XFCT")
            img_file = st.file_uploader(f"分析图", key=f"img_{i}")
        with c2:
            m_url = st.text_input(f"主图 URL", key=f"mu_{i}")
            o_urls = st.text_area(f"附图 URL 集", key=f"ou_{i}")
        with c3:
            z1 = st.text_input(f"{v1_s} 图片", key=f"z1_{i}")
            z2 = st.text_input(f"{v2_s} 图片", key=f"z2_{i}")
            z3 = st.text_input(f"{v3_s} 图片", key=f"z3_{i}")
        sku_list.append({"base": b_sku, "file": img_file, "main": m_url, "others": o_urls, "sz_urls": [z1, z2, z3]})

user_kw_pool = st.text_area("📝 通用关键词池")

# --- 5. 执行处理 ---
if st.button("🚀 启动自动化精准生成", use_container_width=True):
    if not selected_tpl: st.error("未选择模板")
    else:
        try:
            wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
            curr_row = 5
            client = OpenAI(api_key=api_key)

            for item in sku_list:
                if not item["base"] or not item["file"]: continue
                
                # AI 视觉分析 - 强化标题丰富度
                img_b64 = base64.b64encode(item["file"].read()).decode('utf-8')
                prompt = """Analyze art. Return JSON: {
                    'title': 'Rich title with style, material, and target room (max 150 chars)',
                    'elements': 'key pattern elements',
                    'color': 'primary color',
                    'bp': ['Header: detailed content', 'Header: detailed content', ... 5 items]
                }"""
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)

                # --- 规则核心：生成父子体数据 ---
                parent_range_sku = f"{item['base']}-{v1_n}-{v3_n}"
                
                # 变体列表：第一个元素设为 Parent 行
                # 逻辑：Parent行之后接三个子变体
                row_data = [
                    {"type": "Parent", "sku": parent_range_sku, "sz": "", "pr": "", "no": ""},
                    {"type": "Child", "sku": f"{item['base']}-{v1_n}", "sz": v1_s, "pr": v1_p, "idx": 0},
                    {"type": "Child", "sku": f"{item['base']}-{v2_n}", "sz": v2_s, "pr": v2_p, "idx": 1},
                    {"type": "Child", "sku": f"{item['base']}-{v3_n}", "sz": v3_s, "pr": v3_p, "idx": 2}
                ]

                for row in row_data:
                    def fill(k, v):
                        targets = [c_idx for c_name, c_idx in h.items() if k.lower() in c_name]
                        if targets:
                            sheet.cell(row=curr_row, column=targets[0], value=ListingValidator.clean(v))

                    # 1. SKU 逻辑锁定
                    fill("seller sku", row["sku"])
                    fill("parent sku", parent_range_sku) # 每一行（包括父行自己）的 Parent SKU 都是范围

                    # 2. 属性同步锁定
                    full_color = f"{ai['color']} {ai['elements']}"
                    fill("color", full_color)
                    fill("color map", full_color)
                    
                    if row["type"] == "Child":
                        fill("size", row["sz"])
                        fill("size map", row["sz"])
                        fill("sale price", row["pr"])

                    # 3. 五点描述锁定 (父类和子类全填)
                    ai_bps = ai.get('bp', [])
                    while len(ai_bps) < 5: ai_bps.append("Expertly designed with high-definition printing.")
                    for b_i in range(5):
                        fill(f"key product features{b_i+1}", ai_bps[b_i])

                    # 4. 标题增强 (品牌 + AI增强标题 + 元素词 + 尺寸)
                    full_title = f"{brand_name} {ai['title']} {ai['elements']}"
                    if row["type"] == "Child":
                        full_title += f" - {row['sz']}"
                    fill("product name", full_title[:199])

                    # 5. 关键词与基础信息
                    fill("generic keyword", ListingValidator.format_keywords(ai['elements'], user_kw_pool))
                    fill("main_image_url", item["main"])
                    fill("sale start date", auto_start_date)
                    fill("sale end date", auto_end_date)
                    
                    if row["type"] == "Child" and item["sz_urls"][row["idx"]]:
                        fill("other_image_url1", item["sz_urls"][row["idx"]])

                    curr_row += 1

            out = io.BytesIO()
            wb.save(out)
            st.success(f"✅ V9.7 规格锁定完成！Parent SKU 为: {parent_range_sku}")
            st.download_button("💾 下载最终锁定版 Excel", out.getvalue(), "Listing_V9.7_Locked.xlsm")

        except Exception as e:
            st.error(f"发生错误: {e}")
