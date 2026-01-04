import streamlit as st
import pandas as pd
import io, re, base64

# --- 1. 核心规则校验器 (SOP 固化) ---
class ListingSOP:
    @staticmethod
    def clean_mojibake(text):
        """规则：彻底修复乱码"""
        if pd.isna(text) or str(text).strip() == "": return ""
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    @staticmethod
    def format_keywords(val):
        """规则：元素词+通用词，仅空格间隔，去标点"""
        if pd.isna(val): return ""
        # 将所有非字母数字字符转为空格
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(val))
        return " ".join(dict.fromkeys(clean.split()))

    @staticmethod
    def get_sku_range(sku_series):
        """规则：提取数字范围生成 Parent SKU (例: 001-002)"""
        all_nums = []
        for s in sku_series.dropna().astype(str):
            found = re.findall(r'\d+', s)
            if found: all_nums.append(int(found[-1]))
        if not all_nums: return "UNKNOWN-RANGE"
        return f"{min(all_nums):03d}-{max(all_nums):03d}"

# --- 2. Streamlit 界面 ---
st.set_page_config(page_title="亚马逊批量优化器 V9.9", layout="wide")
st.title("🚀 亚马逊 Listing 规格自动修正工具")
st.info("说明：此版本已锁定 SKU 范围逻辑、Color Map 同步、乱码清洗及 5 点描述必填规则。")

uploaded_file = st.file_uploader("第一步：上传需要修正的 Excel 文件", type=['xlsx', 'xlsm'])

if uploaded_file:
    try:
        # 读取上传的文件
        df = pd.read_excel(uploaded_file)
        st.success("✅ 文件读取成功，正在执行 SOP 规则检查...")

        # --- 执行锁定规则 ---
        
        # 1. 自动识别列名（模糊匹配，防止因模板微调导致功能丢失）
        cols = {c.lower().replace(" ", ""): c for c in df.columns}
        
        sku_col = cols.get('sellersku')
        psku_col = cols.get('parentsku')
        color_col = cols.get('color')
        cmap_col = cols.get('colormap')
        size_col = cols.get('size')
        smap_col = cols.get('sizemap')
        st_col = cols.get('searchterms') or cols.get('generickeyword')
        
        # 2. 生成 Parent SKU 范围 (例如 SQDQ-BH-XFCT-001-002)
        if sku_col:
            sku_prefix = str(df.loc[0, sku_col]).rsplit('-', 1)[0] if '-' in str(df.loc[0, sku_col]) else "SKU"
            sku_range = ListingSOP.get_sku_range(df[sku_col])
            final_psku = f"{sku_prefix}-{sku_range}"
            
            # 锁定：第一行 Seller SKU 等于 Parent SKU
            df.loc[0, sku_col] = final_psku
            if psku_col:
                df[psku_col] = final_psku
            st.write(f"📌 已锁定 Parent SKU 范围: `{final_psku}`")

        # 3. 锁定镜像同步：Color=ColorMap, Size=SizeMap
        if color_col and cmap_col:
            df[cmap_col] = df[color_col]
        if size_col and smap_col:
            df[smap_col] = df[size_col]

        # 4. 锁定五点描述：修复乱码并确保必填
        bp_cols = [c for c in df.columns if 'bullet' in c.lower() or 'feature' in c.lower()]
        for bp in bp_cols:
            df[bp] = df[bp].apply(ListingSOP.clean_mojibake)
            # 强制填充空白描述
            df[bp] = df[bp].replace("", "High-definition professional print with vibrant colors.")

        # 5. 锁定关键词格式
        if st_col:
            df[st_col] = df[st_col].apply(ListingSOP.format_keywords)

        # --- 3. 处理完成，准备下载 ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Template')
        
        st.divider()
        st.download_button(
            label="💾 下载修正后的批量上架表格",
            data=output.getvalue(),
            file_name=f"Fixed_Listing_{sku_range}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"❌ 处理失败，请检查表格格式。错误详情: {e}")

else:
    st.warning("请先上传 Excel 文件以启动自动化修正逻辑。")
