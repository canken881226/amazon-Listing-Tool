import streamlit as st
import pandas as pd
import io, re, base64, json
import openpyxl
from openai import OpenAI

# --- 1. 核心清洗与规格逻辑 ---
class FinalValidator:
    @staticmethod
    def clean(text):
        if pd.isna(text) or str(text).strip() == "": return ""
        # 强制清理乱码，确保 ASCII/UTF-8 兼容
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_st(elements, pool):
        """规则：元素词 + 通用词，空格间隔"""
        combined = f"{elements} {pool}"
        # 正则：只保留字母数字和空格
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', combined)
        return " ".join(clean.split())

# --- 2. 界面配置 ---
st.set_page_config(page_title="Amazon Listing Optimizer V10.1", layout="wide")
st.title("🚀 亚马逊 Listing 规格终极锁定工具")
st.warning("⚠️ 请先在侧边栏配置品牌和规格，最后上传模板并点击生成。")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

with st.sidebar:
    st.header("⚙️ 规则锚点")
    brand = st.text_input("品牌名称", "AMAZING WALL")
    st.divider()
    st.subheader("变体定义 (用于 Parent SKU 范围)")
    v1_s, v1_p, v1_n = st.text_input("尺寸1", "16x24\""), st.text_input("售价1", "12.99"), "001"
    v2_s, v2_p, v2_n = st.text_input("尺寸2", "24x36\""), st.text_input("售价2", "16.99"), "002"
    v3_s, v3_p, v3_n = st.text_input("尺寸3", "32x48\""), st.text_input("售价3", "19.99"), "003"

# --- 3. SKU 对位矩阵 ---
if 'rows' not in st.session_state: st.session_state.rows = 1
sku_inputs = []

for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1} 配置区", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            prefix = st.text_input("SKU 前缀", key=f"p_{i}", placeholder="例: SQDQ-BH-XMT-082")
            img_obj = st.file_uploader("分析图 (必传)", key=f"f_{i}")
        with c2:
            m_url = st.text_input("主图链接", key=f"m_{i}")
            o_urls = st.text_area("附图集", key=f"o_{i}")
        with c3:
            u1 = st.text_input(f"{v1_s} 图片", key=f"u1_{i}")
            u2 = st.text_input(f"{v2_s} 图片", key=f"u2_{i}")
            u3 = st.text_input(f"{v3_s} 图片", key=f"u3_{i}")
        # 注意：这里修正了变量名不一致导致的 KeyError: 'file'
        sku_inputs.append({"prefix": prefix, "img_file": img_obj, "main": m_url, "others": o_urls, "sz_urls": [u1, u2, u3]})

if st.button("➕ 增加款式"):
    st.session_state.rows += 1
    st.rerun()

user_kw = st.text_area("📝 Search Terms 词库")
# 解决 FileNotFoundError：让用户上传模板，不走服务器路径
uploaded_tpl = st.file_uploader("📂 最后一步：上传 Amazon 空白模板 (XLSX/XLSM)", type=['xlsx', 'xlsm'])

# --- 4. 生成逻辑 ---
if st.button("🚀 强制按规执行生成", use_container_width=True):
    if not uploaded_tpl or not api_key:
        st.error("❌ 错误：必须上传模板文件并确保 API Key 已配置。")
    else:
        try:
            with st.status("正在锁定规格写入...") as status:
                # 内存直接读取模板，彻底修复 FileNotFoundError
                wb = openpyxl.load_workbook(uploaded_tpl, keep_vba=True)
                sheet = wb.active
                
                # 模糊匹配表头映射
                h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                
                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_inputs:
                    # 严谨检查
                    if not item["prefix"] or not item["img_file"]:
                        continue
                    
                    # AI 视觉分析
                    img_data = item["img_file"].read()
                    img_b64 = base64.b64encode(img_data).decode('utf-8')
                    prompt = "Analyze art. JSON: {'title':'Rich Title','elements':'word1 word2','color':'main_color','bp':['BP1','BP2','BP3','BP4','BP5']}"
                    
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}],
                        response_format={"type":"json_object"}
                    )
                    ai = json.loads(res.choices[0].message.content)

                    # 规格锁定：Parent SKU 范围 (如 082-001-003)
                    p_sku_val = f"{item['prefix']}-{v1_n}-{v3_n}"
                    
                    # 定义写入序列：1行父 + 3行子 (保证第一行 Seller SKU 不为空)
                    rows_logic = [
                        {"type": "Parent", "sku": p_sku_val, "sz": "", "pr": "", "id": -1},
                        {"type": "Child", "sku": f"{item['prefix']}-{v1_n}", "sz": v1_s, "pr": v1_p, "id": 0},
                        {"type": "Child", "sku": f"{item['prefix']}-{v2_n}", "sz": v2_s, "pr": v2_p, "id": 1},
                        {"type": "Child", "sku": f"{item['prefix']}-{v3_n}", "sz": v3_s, "pr": v3_p, "id": 2}
                    ]

                    for r in rows_logic:
                        def fill(key_pattern, value):
                            # 强化对位逻辑
                            targets = [c_idx for name, c_idx in h.items() if key_pattern.lower().replace(" ", "") in name]
                            if targets:
                                sheet.cell(row=curr_row, column=targets[0], value=FinalValidator.clean(value))

                        # 规格1：SKU 必填 (解决红框1)
                        fill("sellersku", r["sku"])
                        fill("parentsku", p_sku_val)

                        # 规格2：Color & Color Map 镜像强制填充 (解决红框2)
                        full_color = f"{ai['color']} {ai['elements']}"
                        fill("color", full_color)
                        fill("colormap", full_color) # 强制一致
                        
                        # 规格3：Size 同步
                        if r["type"] == "Child":
                            fill("size", r["sz"])
                            fill("sizemap", r["sz"])
                            fill("standardprice", r["pr"])

                        # 规格4：五点描述 (所有行必填，解决红框3)
                        bps = ai.get('bp', [])
                        while len(bps) < 5: bps.append("High-definition giclee print on premium material.")
                        for b_i in range(5):
                            # 适配不同模板表头
                            fill(f"keyproductfeatures{b_i+1}", bps[b_i])
                            fill(f"bulletpoint{b_i+1}", bps[b_i])

                        # 规格5：标题增强 (200字符内)
                        rich_title = f"{brand} {ai['title']} {ai['elements']}"
                        if r["type"] == "Child": rich_title += f" - {r['sz']}"
                        fill("itemname", rich_title[:199])
                        fill("productname", rich_title[:199])

                        # 规格6：关键词 (正则去标点)
                        fill("generickeyword", FinalValidator.format_st(ai['elements'], user_kw))
                        fill("searchterms", FinalValidator.format_st(ai['elements'], user_kw))

                        # 图片对位
                        fill("mainimageurl", item["main"])
                        if r["type"] == "Child" and item["sz_urls"][r["id"]]:
                            fill("otherimageurl1", item["sz_urls"][r["id"]])

                        curr_row += 1

            status.update(label="✅ 规格已锁定！请下载检查。", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V10.1 最终锁定版", output.getvalue(), "Amazon_Listing_Final.xlsm")
            
        except Exception as e:
            st.error(f"❌ 生成失败，技术原因: {str(e)}")
