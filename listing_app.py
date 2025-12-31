import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import openpyxl
from openpyxl.styles import Font
from openai import OpenAI
from PIL import Image
from datetime import datetime, timedelta

# --- 1. 自动计算促销时间逻辑 ---
today = datetime.now()
auto_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
auto_end_date = ((today - timedelta(days=1)) + timedelta(days=365) - timedelta(days=1)).strftime("%Y-%m-%d")

st.set_page_config(page_title="亚马逊 AI 专家 V9.4", layout="wide")
api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 侧边栏：仅保留必要配置 ---
with st.sidebar:
    st.header("⚙️ 基础配置")
    brand_name = st.text_input("品牌名称", "YourBrand")
    tpl_list = [f for f in os.listdir("templates") if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板", tpl_list) if tpl_list else None
    
    st.divider()
    st.subheader("变体尺寸与售价")
    s1, p1 = st.text_input("尺寸 1", "16x24\""), st.text_input("售价 1", "12.99")
    s2, p2 = st.text_input("尺寸 2", "24x36\""), st.text_input("售价 2", "16.99")
    s3, p3 = st.text_input("尺寸 3", "32x48\""), st.text_input("售价 3", "19.99")
    
    st.info(f"📅 促销自动设置：\n开始：{auto_start_date}\n结束：{auto_end_date}")

# --- 3. SKU 对位矩阵 ---
st.header("🖼️ SKU 精准对位矩阵")
if 'sku_rows' not in st.session_state: st.session_state.sku_rows = 3

sku_data = []
for i in range(st.session_state.sku_rows):
    with st.expander(f"款式 {i+1} 录入区", expanded=True):
        c1, c2, c3 = st.columns([1.5, 2, 2.5])
        with c1:
            sku_name = st.text_input(f"SKU 名称", key=f"s_{i}")
            local_img = st.file_uploader(f"上传分析图", key=f"f_{i}")
        with c2:
            main_url = st.text_input(f"主图链接", key=f"m_{i}")
            others = st.text_area(f"附图链接集", key=f"o_{i}", height=80)
        with c3:
            s1_u = st.text_input(f"{s1} 图片", key=f"s1u_{i}")
            s2_u = st.text_input(f"{s2} 图片", key=f"s2u_{i}")
            s3_u = st.text_input(f"{s3} 图片", key=f"s3u_{i}")
        sku_data.append({"sku": sku_name, "img": local_img, "main": main_url, "others": others, "sz_urls": [s1_u, s2_u, s3_u]})

if st.button("➕ 增加款式"):
    st.session_state.sku_rows += 1
    st.rerun()

user_kw_pool = st.text_area("📝 Search Terms 词库", height=80)

# --- 4. 执行生成 ---
if st.button("🚀 启动全自动化精准生成", use_container_width=True):
    if not selected_tpl: st.error("请选择模板")
    else:
        try:
            with st.status("正在处理...") as status:
                wb = openpyxl.load_workbook(os.path.join("templates", selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 获取表头映射及第四行默认值
                h = {str(c.value).strip().lower(): c.column for r in sheet.iter_rows(min_row=1, max_row=3) for c in r if c.value}
                defaults = {col: sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column+1) if sheet.cell(row=4, column=col).value is not None}

                curr_row = 5
                client = OpenAI(api_key=api_key)

                for item in sku_data:
                    if not item["sku"] or not item["img"]: continue
                    
                    # AI 视觉生成文案
                    img_file = item["img"]
                    img_b64 = base64.b64encode(img_file.read()).decode('utf-8')
                    prompt = f"Describe this art pattern. Return JSON: {{'title':'(detailed pattern title)','bp':['Header: content',...5],'theme':'color_name','kw':'short_keywords'}}"
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}], response_format={"type":"json_object"})
                    ai = json.loads(res.choices[0].message.content)

                    # 写入 3 个变体
                    for idx, (sz_name, sz_price) in enumerate([(s1, p1), (s2, p2), (s3, p3)]):
                        # 继承第四行属性
                        for col, val in defaults.items():
                            sheet.cell(row=curr_row, column=col, value=val)
                        
                        def fill_col(k, v):
                            target = [c for c in h if k.lower() in c]
                            if target: sheet.cell(row=curr_row, column=h[target[0]], value=str(v))

                        # 规则 1 & 4: SKU 与 Parent SKU
                        sz_tag = sz_name.replace('"', '').replace(' ', '')
                        fill_col("seller sku", f"{item['sku']}-{sz_tag}")
                        fill_col("parent sku", f"{item['sku']}-P")
                        
                        # 规则 2: 标题关联图案 + 尺寸
                        fill_col("product name", f"{brand_name} {ai['title']} - {sz_name}")
                        
                        # 规则 1 & 2: 价格与自动促销时间
                        fill_col("sale price", sz_price)
                        fill_col("sale start date", auto_start_date)
                        fill_col("sale end date", auto_end_date)
                        
                        # 规则 5: 核心字段
                        fill_col("color", ai['theme'])
                        fill_col("color map", ai['theme'])
                        fill_col("size", sz_name)
                        fill_col("size map", sz_name)
                        fill_col("generic keyword", f"{ai['kw']} {user_kw_pool}")
                        
                        # 规则 4: 五点描述
                        bp_cols = [c for c in h if "key product features" in c]
                        for j, c_name in enumerate(bp_cols[:5]):
                            fill_col(c_name, ai['bp'][j])
                            
                        # 图片对位
                        fill_col("main_image_url", item["main"])
                        if item["sz_urls"][idx]: fill_col("other_image_url1", item["sz_urls"][idx])
                        
                        curr_row += 1
                
                status.update(label="✅ 生成成功！", state="complete")
            
            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载 V9.4 锁定版", output.getvalue(), f"Listing_{item['sku']}.xlsm")
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
