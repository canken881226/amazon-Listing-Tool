import streamlit as st
import pandas as pd
import io
import os
import base64
import json
import re
from datetime import datetime, timedelta
from openai import OpenAI
import openpyxl
from PIL import Image

# --- 1. 页面配置 ---
st.set_page_config(page_title="亚马逊 AI 精细化上架 V5.8", layout="wide")

api_key = st.secrets.get("OPENAI_API_KEY") or ""

# --- 2. 固化专业写作逻辑 (针对 A9/Rufus 深度优化) ---
SYSTEM_LOGIC = """
你是一位亚马逊精细化运营专家。请根据图片和关键词执行以下规则：
1. Title: 长度 120 字符左右的核心产品名。
2. Search Terms: 仅输出单个单词，空格隔开，无标点，去重，控制在 240 字符以内。
3. Bullets: 严格分 5 条，每条 20-30 单词，包含功能/材质/场景等关键词。
4. Description: 包含 <b>, <br> 标签。
"""

# --- 3. 侧边栏 ---
with st.sidebar:
    st.header("📂 系统配置")
    if api_key: st.success("✅ API Key 已就绪")
    t_path = os.path.join(os.getcwd(), "templates")
    all_tpls = [f for f in os.listdir(t_path) if f.endswith(('.xlsx', '.xlsm'))]
    selected_tpl = st.selectbox("选择模板", all_tpls if all_tpls else ["⚠️ 无模板"])

# --- 4. 辅助函数 ---
def process_img(file):
    img = Image.open(file)
    img.thumbnail((1000, 1000))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def call_ai(img_file, sku_prefix, keywords):
    client = OpenAI(api_key=api_key)
    b64 = process_img(img_file)
    prompt = f"{SYSTEM_LOGIC}\nSKU:{sku_prefix}\n关键词库:{keywords}\n返回JSON:{{'title':'','desc':'','bp':['','','','',''],'keywords':'','color':''}}"
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type":"json_object"},
            timeout=60
        )
        return json.loads(res.choices[0].message.content)
    except Exception:
        return None

# --- 5. 主界面 ---
st.title("🤖 亚马逊 AI 精细化填充 V5.8")

# 尺寸与价格动态配置
st.subheader("💰 尺寸与价格配置 (Price 将填入 Sale Price)")
default_sp = pd.DataFrame([
    {"Size": '16x24"', "Price": "9.99"},
    {"Size": '24x36"', "Price": "16.99"},
    {"Size": '32x48"', "Price": "18.99"}
])
size_price_data = st.data_editor(default_sp, num_rows="dynamic")

col_img, col_kw = st.columns([1, 1])
with col_img:
    uploaded_imgs = st.file_uploader("🖼️ 上传图片", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
with col_kw:
    user_keywords = st.text_area("📝 关键词组", height=200, placeholder="粘贴 I-V 类关键词...")

# --- 6. 执行填充 ---
if st.button("🚀 启动精细化填充", use_container_width=True):
    if not uploaded_imgs: st.error("❌ 请上传图片")
    else:
        try:
            with st.status("🔄 正在执行精细化填充...") as status:
                wb = openpyxl.load_workbook(os.path.join(t_path, selected_tpl), keep_vba=True)
                sheet = wb.active
                
                # 扫描标题列映射
                headers = {str(cell.value).strip(): cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value}
                bp_cols = [cell.column for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if str(cell.value).strip() == "Key Product Features"]

                t = datetime.now()
                s_start, s_end = (t-timedelta(days=1)).strftime('%Y-%m-%d'), (t+timedelta(days=364)).strftime('%Y-%m-%d')
                
                # 父体固定在 Row 4
                parent_row = 4
                current_row = 5 # 子体从 Row 5 开始
                
                for idx, img in enumerate(uploaded_imgs):
                    prefix = os.path.splitext(img.name)[0]
                    st.write(f"⏳ 正在分析图案并生成文案: **{prefix}**...")
                    ai_data = call_ai(img, prefix, user_keywords)
                    
                    if not ai_data:
                        st.warning(f"⚠️ {prefix} 分析超时，已跳过。")
                        continue

                    # --- 1. 如果是第一张图，填充父体 (Row 4) ---
                    if idx == 0:
                        parent_sku = f"{prefix}-P"
                        if "Seller SKU" in headers: sheet.cell(row=parent_row, column=headers["Seller SKU"]).value = parent_sku
                        if "Parentage" in headers: sheet.cell(row=parent_row, column=headers["Parentage"]).value = "parent"
                        if "Product Name" in headers: sheet.cell(row=parent_row, column=headers["Product Name"]).value = ai_data['title']
                        if "Product Description" in headers: sheet.cell(row=parent_row, column=headers["Product Description"]).value = ai_data['desc']
                        if "Generic Keyword" in headers: sheet.cell(row=parent_row, column=headers["Generic Keyword"]).value = ai_data['keywords']
                        if "Color" in headers: sheet.cell(row=parent_row, column=headers["Color"]).value = ai_data['color']
                        for bp_idx, col_idx in enumerate(bp_cols[:5]):
                            sheet.cell(row=parent_row, column=col_idx).value = ai_data['bp'][bp_idx]

                    # --- 2. 填充子体 (从 Row 5 开始) ---
                    for _, row_data in size_price_data.iterrows():
                        sz = str(row_data["Size"])
                        pr = str(row_data["Price"])
                        c_sku = f"{prefix}-{sz.replace('\"','').replace(' ', '')}"
                        
                        if "Seller SKU" in headers: sheet.cell(row=current_row, column=headers["Seller SKU"]).value = c_sku
                        if "Parent SKU" in headers: sheet.cell(row=current_row, column=headers["Parent SKU"]).value = f"{prefix}-P"
                        if "Parentage" in headers: sheet.cell(row=current_row, column=headers["Parentage"]).value = "child"
                        
                        # 标题 = 产品名 + 尺寸 (150字符限额)
                        full_title = f"{ai_data['title']} - {sz}"
                        if "Product Name" in headers: sheet.cell(row=current_row, column=headers["Product Name"]).value = full_title[:150]
                        
                        # 价格与尺寸映射
                        if "Sale Price" in headers: sheet.cell(row=current_row, column=headers["Sale Price"]).value = pr
                        if "Size" in headers: sheet.cell(row=current_row, column=headers["Size"]).value = sz
                        if "Size Map" in headers: sheet.cell(row=current_row, column=headers["Size Map"]).value = sz
                        
                        # 促销日期
                        if "Sale Start Date" in headers: sheet.cell(row=current_row, column=headers["Sale Start Date"]).value = s_start
                        if "Sale End Date" in headers: sheet.cell(row=current_row, column=headers["Sale End Date"]).value = s_end

                        # 内容同步
                        if "Product Description" in headers: sheet.cell(row=current_row, column=headers["Product Description"]).value = ai_data['desc']
                        if "Generic Keyword" in headers: sheet.cell(row=current_row, column=headers["Generic Keyword"]).value = ai_data['keywords']
                        if "Color" in headers: sheet.cell(row=current_row, column=headers["Color"]).value = ai_data['color']
                        
                        # 五点顺序填充
                        for bp_idx, col_idx in enumerate(bp_cols[:5]):
                            sheet.cell(row=current_row, column=col_idx).value = ai_data['bp'][bp_idx]
                        
                        current_row += 1
                
                status.update(label="✅ 精细化填充完成！", state="complete")

            output = io.BytesIO()
            wb.save(output)
            st.download_button("💾 下载最终成品表格 (.xlsm)", output.getvalue(), f"Filled_{prefix}.xlsm", use_container_width=True)
        except Exception as e:
            st.error(f"❌ 运行错误: {str(e)}")
