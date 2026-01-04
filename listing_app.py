import streamlit as st
import pandas as pd
import io, re, base64, json, openpyxl
from openai import OpenAI

# --- 核心规格锁定器 ---
class AmazonSOP:
    @staticmethod
    def fix_keywords(elements, user_pool):
        """规则：去占位符，严格空格分隔，限长200字符"""
        # 移除常见的 AI 占位词
        blacklist = ['word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich']
        raw = f"{elements} {user_pool}"
        words = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw).split()
        clean_words = [w for w in words if w.lower() not in blacklist]
        # 去重并拼接
        result = " ".join(dict.fromkeys(clean_words))
        return result[:200]

    @staticmethod
    def clean_title(text):
        """规则：确保标题不带特殊符号和占位符"""
        text = re.sub(r"[\['\]]", "", str(text)) # 移除 AI 可能返回的列表括号
        return text.strip()

# --- 界面 ---
st.set_page_config(page_title="亚马逊规格锁定器 V10.2", layout="wide")
st.title("🛡️ 亚马逊规格终极锁定 (防乱套版)")

with st.sidebar:
    st.header("⚙️ 规格定义")
    brand = st.text_input("品牌", "AMAZING WALL")
    # 锁定 001, 002, 003 规格
    v_map = [("16x24\"", "12.99", "001"), ("24x36\"", "16.99", "002"), ("32x48\"", "19.99", "003")]

if 'rows' not in st.session_state: st.session_state.rows = 1
sku_configs = []

for i in range(st.session_state.rows):
    with st.expander(f"款式 {i+1}", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            pfx = st.text_input("SKU 前缀", key=f"p_{i}", placeholder="SQDQ-BH-XMT-082")
            img = st.file_uploader("分析图", key=f"f_{i}")
        with c2:
            m_url = st.text_input("主图 URL", key=f"m_{i}")
            o_url = st.text_area("附图集", key=f"o_{i}")
        with c3:
            u_imgs = [st.text_input(f"尺寸{j+1}图", key=f"u{j}_{i}") for j in range(3)]
        sku_configs.append({"pfx": pfx, "file": img, "main": m_url, "sz_urls": u_imgs})

user_pool = st.text_area("通用关键词库")
tpl_file = st.file_uploader("上传模板", type=['xlsx', 'xlsm'])

# --- 执行生成 ---
if st.button("🚀 强制锁定生成 (修正 SKU 与关键词)"):
    if not tpl_file or not st.secrets.get("OPENAI_API_KEY"):
        st.error("请检查模板和 API 配置")
    else:
        try:
            wb = openpyxl.load_workbook(tpl_file, keep_vba=True)
            sheet = wb.active
            h = {str(c.value).strip().lower().replace(" ", ""): c.column for r in sheet.iter_rows(max_row=3) for c in r if c.value}
            
            curr_row = 5
            client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

            for item in sku_configs:
                if not item["pfx"] or not item["file"]: continue
                
                # AI 分析
                img_b64 = base64.b64encode(item["file"].read()).decode('utf-8')
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":[{"type":"text","text":"Analyze art. JSON: {'title':'rich title','elements':'elements','color':'color','bp':['bp1','bp2','bp3','bp4','bp5']}"},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}],
                    response_format={"type":"json_object"}
                )
                ai = json.loads(res.choices[0].message.content)

                # 规则：每一组只生成 4 行（1父3子）
                p_sku = f"{item['pfx']}-001-003"
                
                data_rows = [
                    {"type": "P", "sku": p_sku, "sz": "", "pr": "", "id": -1},
                    {"type": "C", "sku": f"{item['pfx']}-001", "sz": v_map[0][0], "pr": v_map[0][1], "id": 0},
                    {"type": "C", "sku": f"{item['pfx']}-002", "sz": v_map[1][0], "pr": v_map[1][1], "id": 1},
                    {"type": "C", "sku": f"{item['pfx']}-003", "sz": v_map[2][0], "pr": v_map[2][1], "id": 2},
                ]

                for r in data_rows:
                    def fill(k, v):
                        cols = [idx for name, idx in h.items() if k.lower().replace(" ", "") in name]
                        if cols: sheet.cell(row=curr_row, column=cols[0], value=str(v).strip())

                    # 1. SKU 逻辑修正 (Seller SKU 第一行 = Parent SKU)
                    fill("sellersku", r["sku"])
                    fill("parentsku", p_sku)

                    # 2. 颜色与镜像
                    color_val = f"{ai['color']} {ai['elements']}"
                    fill("color", color_val)
                    fill("colormap", color_val)

                    # 3. 五点描述 (全填)
                    bps = ai.get('bp', [])
                    while len(bps) < 5: bps.append("High-quality nature landscape art.")
                    for b_i in range(5): fill(f"keyproductfeatures{b_i+1}", bps[b_i])

                    # 4. 标题修正 (品牌在前，清理占位符)
                    t_clean = AmazonSOP.clean_title(ai['title'])
                    full_title = f"{brand} {t_clean} {ai['elements']}"
                    if r["type"] == "C": full_title += f" - {r['sz']}"
                    fill("productname", full_title[:195])

                    # 5. 关键词修正 (防超长，去套用词)
                    fill("generickeyword", AmazonSOP.fix_keywords(ai['elements'], user_pool))

                    if r["type"] == "C":
                        fill("size", r["sz"])
                        fill("sizemap", r["sz"])
                        fill("standardprice", r["pr"])
                        if item["sz_urls"][r["id"]]: fill("otherimageurl1", item["sz_urls"][r["id"]])
                    
                    fill("mainimageurl", item["main"])
                    curr_row += 1

            # 导出
            out = io.BytesIO()
            wb.save(out)
            st.download_button("💾 下载修正版 Excel (已锁定 SKU 4行逻辑)", out.getvalue(), "Listing_Fixed.xlsm")
            
        except Exception as e:
            st.error(f"出错原因: {e}")
