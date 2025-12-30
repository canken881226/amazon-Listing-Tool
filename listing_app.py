import streamlit as st
import pandas as pd
import io
import os
import base64
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. 页面基础配置 ---
st.set_page_config(page_title="亚马逊 AI 智能上架系统 V4.1", layout="wide")

# 安全读取 Secrets 中的 OpenAI Key
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = st.sidebar.text_input("🔑 填入 API Key (若 Secrets 未配置)", type="password")

# --- 2. 侧边栏：模板管理 (兼容 .xlsm) ---
with st.sidebar:
    st.header("📂 官方模板配置")
    
    # 动态获取当前目录下 templates 文件夹路径
    t_path = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(t_path):
        os.makedirs(t_path)
    
    # 读取所有 .xlsx 和 .xlsm 文件
    all_tpls = [f for f in os.listdir(t_path) if f.endswith('.xlsx') or f.endswith('.xlsm')]
    
    if all_tpls:
        selected_tpl = st.selectbox("选择当前上架类目模板", all_tpls)
        st.success(f"✅ 已加载 {len(all_tpls)} 个模板")
    else:
        st.error("⚠️ 未在 templates 文件夹发现模板")
        selected_tpl = st.selectbox("状态", ["请检查 GitHub 仓库路径"])

    # 备用手动上传
    st.divider()
    manual_tpl = st.file_uploader("📤 或在此直接上传备用模板", type=["xlsx", "xlsm"])

# --- 3. 辅助函数：图片编码与 AI 调用 ---
def encode_img(file):
    """将图片文件转换为 Base64 字符串"""
    return base64.b64encode(file.getvalue()).decode('utf-8')

def call_ai_vision(img_file, sku, instruction):
    """调用 GPT-4o 进行视觉识别"""
    client = OpenAI(api_key=api_key)
    b64 = encode_img(img_file)
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"SKU: {sku}. 指令: {instruction}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }],
        max_tokens=800
    )
    return response.choices[0].message.content

# --- 4. 主界面布局 ---
st.title("🤖 亚马逊智能 AI 视觉填充系统")

col_img, col_cmd = st.columns([1, 1])

with col_img:
    st.subheader("🖼️ 1. 上传图片 (AI 识别图案)")
    uploaded_imgs = st.file_uploader("文件名即为 SKU", 
                                     type=["jpg", "png", "jpeg"], accept_multiple_files=True)

with col_cmd:
    st.subheader("💬 2. ChatGPT 视觉指令")
    user_instruction = st.text_area("文案要求", 
                                    value="请识别图中的图案元素和风格。写出吸引人的标题、5点描述、Search Terms、以及用于Color栏位的图案词。",
                                    height=150)

# --- 5. 核心逻辑执行 ---
if st.button("🚀 启动 AI 视觉分析并填充表格", use_container_width=True):
    if not uploaded_imgs:
        st.error("请先上传产品图片")
    elif not api_key:
        st.error("缺少 API Key，请在 Secrets 或侧边栏配置")
    else:
        results = []
        progress = st.progress(0)
        
        # 促销时间计算 (昨天到一年后)
        today = datetime.now()
        s_start = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        s_end = (today - timedelta(days=1) + timedelta(days=364)).strftime('%Y-%m-%d')

        for idx, img in enumerate(uploaded_imgs):
            sku = os.path.splitext(img.name)[0]
            st.write(f"正在分析 SKU: **{sku}**...")
            
            try:
                ai_text = call_ai_vision(img, sku, user_instruction)
                results.append({
                    "item_sku": sku,
                    "AI 分析结果 (请复制填入官方表)": ai_text,
                    "sale_start_date": s_start,
                    "sale_end_date": s_end
                })
            except Exception as e:
                st.error(f"SKU {sku} 分析失败: {e}")
                
            progress.progress((idx + 1) / len(uploaded_imgs))

        # 结果预览与导出
        st.divider()
        st.subheader("📊 3. 填充结果预览")
        final_df = pd.DataFrame(results)
        st.dataframe(final_df, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            final_df.to_excel(writer, index=False, sheet_name='Sheet1')
        
        st.download_button("💾 下载分析好的数据 (Excel)", output.getvalue(), 
                           file_name=f"Amazon_Listing_{today.strftime('%m%d')}.xlsx")
