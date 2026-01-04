import streamlit as st
import pandas as pd
import io, os, base64, json, re, openpyxl
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 自动计算促销时间逻辑 ---
today = datetime.now()
auto_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
auto_end_date = ((today - timedelta(days=1)) + timedelta(days=365)).strftime("%Y-%m-%d")

st.set_page_config(page_title="亚马逊 AI 专家 V10.5 稳定回溯版", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 核心清洗函数：解决乱码、占位符与关键词规则 ---
def strict_clean(text):
    if not text: return ""
    # 移除 JSON 占位符如 ['word1'] 等干扰
    text = re.sub(r"[\[\]'\"']", "", str(text))
    return text.encode('utf-8', 'ignore').decode('utf-8').strip()

def format_keywords(raw_text):
    if not raw_text: return ""
    # 物理剔除 AI 常见的占位词
    blacklist = ['word1', 'word2', 'fake', 'placeholder', 'rich', 'title']
    clean_text = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_text)
    words = [w for w in clean_text.split() if w.lower() not in blacklist]
    return " ".join(dict.fromkeys(words))[:245] # 严格限制在 250 字符以内

# --- 3. 侧边栏：还原 SIZE 自定义与价格界面 ---
with st.sidebar:
    st.header("⚙️ 基础规格配置")
    brand_name = st.text_input("品牌名称", "AMAZING WALL")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("变体尺寸、售价与编号")
    # 恢复 SIZE 自定义输入
    s1, p1, n1 = st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99"), "001"
    s2, p2, n2 = st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99"), "002"
    s3, p3, n3 = st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99"), "003"
    
    st.info(f"📅 促销自动设置：\n开始：{auto_start_date}\n结束：{auto_end_date}")

# --- 4. 款式录入：恢复多款式录入矩阵 ---
st.header("🖼️ SKU 精准对位矩阵")
if 'sku_rows' not in st.session_state: st.session_state.sku_rows = 1

sku_data = []
for i in range(st.session_state.sku_rows):
    with st.expander(f"款式 {i+1} 录入区", expanded=True):
        c1, c2, c3 = st.columns([1.5, 2, 2.5])
        with c1:
            # 修改为 SKU 前缀，方便生成范围
            sku_prefix = st.text_input(f"SKU 前缀 (例: SQDQ-BH-XFCT)", key=f"s_{i}")
            local_img = st.file_uploader(f"上传分析图", key=f"f_{i}")
        with c2:
            main_url = st.text_input(f"主图链接", key=f"m_{i}")
            others = st.text_area(f"附图链接集", key=f"o_{i}", height=80)
        with c3:
            s1_u = st.text_input(f"{s1} 图片", key=f"s1u_{i}")
            s2_u = st.text_input(f"{s2} 图片", key=f"s2u_{i}")
            s3_u = st.text_input(f"{s3} 图片", key=f"s3u_{i}")
        sku_data.append({"sku": sku_prefix, "img": local_img, "main": main_url, "others": others, "sz_urls": [s1_u, s2_u, s3_u]})

# 恢复“增加款式”按钮
if st.button("➕ 增加款式"):
    st.session_state.sku_rows += 1
    st.rerun()

user_kw_pool = st.text_area("📝 Search Terms 通用词库", height=80)

# --- 5. 执行生成：锁定核心业务逻辑 ---
if st.button("🚀 启动全自动化精准生成", use_container_width=True):
    if not selected_tpl: st.error("请在侧边栏选择模板")
    else:
        try:
            with st.status("正在严格按照 SOP 执行生成...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 获取表头映射
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                
                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_data:
                    if not item["sku"] or not item["img"]: continue
                    
                    # AI 视觉生成文案
                    img_file = item["img"]
                    img_b64 = base64.b64encode(img_file.read()).decode('utf-8')
                    prompt = "Describe art pattern. Return JSON: {'title':'detailed title','bp':['Header: content',...5],'color':'main color','elements':'keywords'}"
                    res = client.chat.completions.create(
                        model="gpt-4o-mini", 
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}], 
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)

                    # --- 规则锁定：Parent SKU 范围生成 ---
                    # 第一行的 Seller SKU 和 Parent SKU = 前缀-001-003
                    p_sku_val = f"{item['sku']}-{n1}-{n3}"
                    
                    # 定义写入序列：1行父体 + 3行子体，共 4 行，绝不多出
                    variants = [
                        {"type": "P", "sku": p_sku_val, "sz": "", "pr": "", "id": -1},
                        {"type": "C", "sku": f"{item['sku']}-{n1}", "sz": s1, "pr": p1, "id": 0},
                        {"type": "C", "sku": f"{item['sku']}-{n2}", "sz": s2, "pr": p2, "id": 1},
                        {"type": "C", "sku": f"{item['sku']}-{n3}", "sz": s3, "pr": p3, "id": 2},
                    ]

                    for r in variants:
                        def fill(key_word, value):
                            target_cols = [c_idx for c_name, c_idx in h.items() if key_word.lower().replace(" ", "") in c_name]
                            if target_cols:
                                sheet.cell(row=curr_row, column=target_cols[0], value=strict_clean(value))

                        # 1. SKU 逻辑锁定
                        fill("sellersku", r["sku"])
                        fill("parentsku", p_sku_val)

                        # 2. 属性镜像锁定 (ColorMap = Color, SizeMap = Size)
                        full_color = f"{ai['color']} {ai['elements']}"
                        fill("color", full_color)
                        fill("colormap", full_color)
                        
                        if r["type"] == "C":
                            fill("size", r["sz"])
                            fill("sizemap", r["sz"])
                            fill("standardprice", r["pr"])
                            fill("saleprice", r["pr"])

                        # 3. 五点描述锁定 (全填，防乱码)
                        bps = ai.get('bp', [])
                        while len(bps) < 5: bps.append("Expertly designed with high-definition printing.")
                        for b_idx in range(5):
                            fill(f"keyproductfeatures{b_idx+1}", bps[b_idx])

                        # 4. 标题丰富度与长度控制
                        title = f"{brand_name} {ai['title']} {ai['elements']}"
                        if r["type"] == "C": title += f" - {r['sz']}"
                        fill("productname", title[:199]) # 强制限制 200 字符

                        # 5. 关键词逻辑锁定 (剔除占位符)
                        fill("generickeyword", format_keywords(f"{ai['elements']} {user_kw_pool}"))
                        
                        # 基础信息填充
                        fill("mainimageurl", item["main"])
                        fill("salestartdate", auto_start_date)
                        fill("saleenddate", auto_end_date)
                        if r["type"] == "C" and item["sz_urls"][r["id"]]:
                            fill("otherimageurl1", item["sz_urls"][r["id"]])

                        curr_row += 1
                
                status.update(label="✅ 生成成功！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载稳定回溯版 Excel", output.getvalue(), f"Listing_Stable.xlsm")
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
