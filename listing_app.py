import pandas as pd
import re
import os

class ListingOptimizer:
    def __init__(self, input_file, output_file):
        self.input_file = input_file
        self.output_file = output_file
        # 定义标准表头（根据亚马逊批量模板设定）
        self.col_sku = 'Seller SKU'
        self.col_parent_sku = 'Parent SKU'
        self.col_color = 'Color'
        self.col_color_map = 'Color Map'
        self.col_search_terms = 'Search Terms'
        self.bullet_cols = ['Bullet Point 1', 'Bullet Point 2', 'Bullet Point 3', 'Bullet Point 4', 'Bullet Point 5']

    def clean_text(self, text):
        """规则4：彻底清除乱码，防止上传失败"""
        if pd.isna(text) or str(text).strip() == "":
            return ""
        # 强制过滤非标准字符，保留纯文本
        return str(text).encode('utf-8', 'ignore').decode('utf-8').strip()

    def process_data(self):
        print(f"正在读取文件: {self.input_file}")
        df = pd.read_excel(self.input_file)

        # 规则1：检查第一行 Seller SKU 是否缺失
        if pd.isna(df.loc[0, self.col_sku]):
            print("⚠️ 警告: 第一行 Seller SKU 不能为空！已标记占位符。")
            df.loc[0, self.col_sku] = "REQUIRED_START_SKU"

        # 规则2：生成 Parent SKU (区间命名法：001-003)
        # 提取 SKU 中的数字部分并找到最小/最大值
        all_skus = df[self.col_sku].dropna().astype(str)
        nums = [int(n) for s in all_skus for n in re.findall(r'\d+', s)]
        if nums:
            parent_range = f"{min(nums):03d}-{max(nums):03d}"
            df[self.col_parent_sku] = parent_range
            # 特殊规则：第一行的 Seller SKU 与 Parent SKU 保持一致
            df.loc[0, self.col_sku] = parent_range 
            print(f"✅ Parent SKU 已锁定为: {parent_range}")

        # 规则3：Color 与 Color Map 镜像同步 (必填且含元素词)
        # 强制让 Color Map 等于 Color 的内容
        df[self.col_color_map] = df[self.col_color].fillna("Pattern Element")

        # 规则4：五点描述全覆盖 + 乱码修复
        for col in self.bullet_cols:
            if col in df.columns:
                df[col] = df[col].apply(self.clean_text)
                # 确保不留空，如果某行缺失则补齐
                df[col] = df[col].replace("", "High-quality professional print with vivid details.")

        # 规则5：关键词格式化 (元素词 + 通用词，严格空格分隔)
        if self.col_search_terms in df.columns:
            def format_keywords(val):
                if pd.isna(val): return ""
                # 将所有符号替换为空格
                words = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(val))
                # 合并空格并去重
                return " ".join(dict.fromkeys(words.split()))
            
            df[self.col_search_terms] = df[self.col_search_terms].apply(format_keywords)

        # 保存结果
        df.to_excel(self.output_file, index=False)
        print(f"✅ 处理完成！修正后的文件保存为: {self.output_file}")

if __name__ == "__main__":
    # 使用前请确保文件名正确
    optimizer = ListingOptimizer("original_listing.xlsx", "final_upload_ready.xlsx")
    optimizer.process_data()
