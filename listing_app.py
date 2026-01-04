import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 日期逻辑 (促销开始/结束) ---
today = datetime.now()
auto_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
auto_end_date = ((today - timedelta(days=1)) + timedelta(days=365)).strftime("%Y-%m-%d")

st.set_page_config(page_title="亚马逊 AI 专家 V9.8 - 逻辑锁定版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心规则校验与处理函数 ---
def clean_strict(text):
    """强制清理乱码"""
    if not text: return ""
    return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

def format_st(elements, pool):
    """关键词格式：元素词 + 通用词，空格间隔"""
    combined = f"{elements} {pool}"
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', combined)
    return " ".join(clean.split())

# --- 3. 侧边栏：规则定义 ---
with st.sidebar:
    st.header("⚙️ 规则锚定中心")
    brand_name = st.text_input("品牌名称", "YourBrand")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板", tpl_list)
    
    st.divider()
    st.subheader("变体编号与规格")
    # 定义子变体的编号、尺寸和价格
    v1_n, v1_s, v1_p = "001", st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99")
    v2_n, v2_s, v2_p = "002", st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99")
    v3_n, v3_s, v3_p = "003", st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99")

# --- 4. 款式录入 ---
st.header("🖼️ SKU 对位录入矩阵")
if 'sku_rows' not in st.session_state: st.session_state.sku_rows = 1

sku_list = []
for i in range(st.session_state.sku_rows):
    with st.expander(f"款式 {i+1} 核心配置", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            # 基础前缀：如 SQDQ-BH-XFCT
            b_sku = st.text_input(f"SKU 前缀", key=f"base_{i}", placeholder="例: SQDQ-BH-XFCT")
            img_file = st.file_uploader(f"分析图", key=f"f_{i}")
        with c2:
            m_url = st.text_input(f"主图 URL", key=f"m_{i}")
            o_urls = st.text_area(f"附图集", key=f"o_{i}")
        with c3:
            z1 = st.text_input(f"{v1_s} 图片", key=f"z1_{i}")
            z2 = st.text_input(f"{v2_s} 图片", key=f"z2_{i}")
            z3 = st.text_input(f"{v3_s} 图片", key=f"z3_{i}")
        sku_list.append({"base": b_sku, "file": img_file, "main": m_url, "others": o_urls, "sz_urls": [z1, z2, z3]})

if st.button("➕ 增加款式"):
    st.session_state.sku_rows += 1
    st.rerun()

user_kw_pool = st.text_area("📝 通用关键词池")

# --- 5. 执行核心逻辑 ---
if st.button("🚀 启动全自动化生成", use_container_width=True):
    if not selected_tpl or not api_key:
        st.error("❌ 请确保选择了模板并配置了 API Key")
    else:
        try:
            with st.status("正在按照 SOP 执行生成...") as status:
                # 加载模板
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 表头映射映射 (统一转小写进行匹配)
                h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                
                curr_row = 5 # 假设从第5行开始写入
                client = OpenAI(api_key=api_key)

                for item in sku_list:
                    if not item["base"] or not item["file"]: continue
                    
                    # AI 视觉生成文案 (强化标题丰富度规则)
                    img_b64 = base64.b64encode(item["file"].read()).decode('utf-8')
                    prompt = """Analyze the art pattern. Return JSON: {
                        'rich_title': 'Detailed title including art style, theme, and room suitability (approx 100-150 chars)',
                        'elements': '3-5 key visual elements words',
                        'color': 'primary color name',
                        'bp': ['Header: detailed sellpoint 1', ... 5 items]
                    }"""
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}],
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)

                    # --- 规则核心：Parent SKU 范围生成 ---
                    # 按照你的规则：第一行的 Seller SKU 和 Parent SKU = 前缀-001-003
                    p_sku = f"{item['base']}-{v1_n}-{v3_n}"
                    
                    # 变体数据表（包含第一行的父体）
                    rows = [
                        {"type": "Parent", "sku": p_sku, "s_name": "", "s_price": "", "idx": -1},
                        {"type": "Child", "sku": f"{item['base']}-{v1_n}", "s_name": v1_s, "s_price": v1_p, "idx": 0},
                        {"type": "Child", "sku": f"{item['base']}-{v2_n}", "s_name": v2_s, "s_price": v2_p, "idx": 1},
                        {"type": "Child", "sku": f"{item['base']}-{v3_n}", "s_name": v3_s, "s_price": v3_p, "idx": 2},
                    ]

                    for r_data in rows:
                        def fill(key_word, value):
                            # 模糊匹配表头
                            target_cols = [c_idx for c_name, c_idx in h.items() if key_word.lower() in c_name]
                            if target_cols:
                                # 规则：写入前必须清理乱码
                                final_val = clean_strict(value)
                                sheet.cell(row=curr_row, column=target_cols[0], value=final_val)

                        # 规则 1: SKU 逻辑
                        fill("seller sku", r_data["sku"])
                        fill("parent sku", p_sku)
                        
                        # 规则 2: Color/Size 镜像同步 (必填)
                        full_color = f"{ai['color']} {ai['elements']}"
                        fill("color", full_color)
                        fill("color map", full_color)
                        
                        if r_data["type"] == "Child":
                            fill("size", r_data["s_name"])
                            fill("size map", r_data["s_name"])
                            fill("sale price", r_data["s_price"])

                        # 规则 3: 五点描述全填 (含父类)
                        ai_bps = ai.get('bp', [])
                        while len(ai_bps) < 5: ai_bps.append("Premium quality art for modern home decor.")
                        for b_i in range(5):
                            fill(f"key product features{b_i+1}", ai_bps[b_i])

                        # 规则 4: 标题丰富度
                        title = f"{brand_name} {ai['rich_title']} {ai['elements']}"
                        if r_data["type"] == "Child":
                            title += f" - {r_data['s_name']}"
                        fill("product name", title[:199]) # 强制限制 200 字符

                        # 规则 5: 关键词格式化
                        fill("generic keyword", format_st(ai['elements'], user_kw_pool))
                        
                        # 基础信息
                        fill("main_image_url", item["main"])
                        fill("sale start date", auto_start_date)
                        fill("sale end date", auto_end_date)
                        if r_data["type"] == "Child" and item["sz_urls"][r_data["idx"]]:
                            fill("other_image_url1", item["sz_urls"][r_data["idx"]])

                        curr_row += 1

                status.update(label="✅ 生成成功！", state="complete")
            
            # 保存
            out = io.BytesIO()
            wb.save(out)
            st.download_button("💾 点击下载锁定版 Excel", out.getvalue(), f"Listing_{datetime.now().strftime('%m%d_%H%M')}.xlsm")
            
        except Exception as e:
            st.error(f"❌ 运行中出错: {str(e)}")
