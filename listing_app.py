import openpyxl
import re
import os
from datetime import datetime, timedelta

# --- 1. 核心規則配置 ---
# 品牌名稱與站點差異拼寫轉換
BRAND_NAME = "AMAZING WALL"
COLOR_TRANS = {"Gray": "Grey", "Black": "Black", "Blue": "Blue"} 

class AmazonFixer:
    @staticmethod
    def clean_mojibake(text):
        """規則：徹底修復亂碼、JSON 殘留及佔位符"""
        if text is None: return ""
        # 移除 JSON 符號
        text = re.sub(r"[\[\]'\"']", "", str(text))
        # 物理過濾佔位詞 (如 word1, fake 等)
        blacklist = {'word1', 'word2', 'fake', 'placeholder', 'detailed', 'rich', 'title'}
        words = text.split()
        return " ".join([w for w in words if w.lower() not in blacklist]).strip()

    @staticmethod
    def format_keywords(raw_text):
        """規則：關鍵詞僅限空格分隔，嚴禁標點，限長 245 字符"""
        if not raw_text: return ""
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(raw_text).lower())
        words = []
        seen = set()
        for w in clean.split():
            if w not in seen and len(w) > 1:
                words.append(w)
                seen.add(w)
        return " ".join(words)[:245]

def run_converter():
    # 準備文件路徑
    us_file = 'us.xlsx'  # 您的美國站已填表格
    uk_tpl = 'uk.xlsx'   # 英國站空白模板
    output_name = f'UK_Ready_{datetime.now().strftime("%m%d")}.xlsx'

    if not os.path.exists(us_file) or not os.path.exists(uk_tpl):
        print("❌ 錯誤：請確保文件夾內有 us.xlsx 和 uk.xlsx")
        return

    print("⏳ 正在加載數據...")
    # data_only=True 讀取數值而非公式
    us_wb = openpyxl.load_workbook(us_file, data_only=True)
    us_sheet = us_wb.active
    uk_wb = openpyxl.load_workbook(uk_tpl, keep_vba=True)
    uk_sheet = uk_wb.active

    # 建立表頭索引映射 (解決 US/UK 模板順序不一致)
    # 假設表頭在第 3 行
    us_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in us_sheet[3] if c.value}
    uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[3] if c.value}

    # 定義跨站點對位地圖 (US 鍵 : UK 鍵)
    transfer_map = {
        "sellersku": "sellersku",
        "parentsku": "parentsku",
        "productname": "itemname",      # UK 站通常叫 item_name
        "brandname": "brandname",
        "productdescription": "productdescription",
        "generickeyword": "searchterms", # US Keyword -> UK Search Terms
        "color": "colour",              # 拼寫轉換
        "colormap": "colourmap",
        "size": "size",
        "sizemap": "sizemap",
        "standardprice": "standardprice",
        "mainimageurl": "mainimageurl",
        "otherimageurl1": "otherimageurl1"
    }

    print("🚀 開始搬運數據並同步規格...")
    # 從第 4 行開始遍歷所有數據
    for row_idx in range(4, us_sheet.max_row + 1):
        # 檢查 Seller SKU 是否存在，防止處理空行
        sku_val = us_sheet.cell(row=row_idx, column=us_h.get('sellersku', 1)).value
        if not sku_val: continue

        # A. 執行核心字段搬運
        for us_key, uk_key in transfer_map.items():
            u_col = us_h.get(us_key)
            k_col = uk_h.get(uk_key)
            
            if u_col and k_col:
                raw_val = us_sheet.cell(row=row_idx, column=u_col).value
                clean_val = AmazonFixer.clean_mojibake(raw_val)
                
                # 特殊規則：如果是關鍵詞，執行嚴格格式化
                if us_key == "generickeyword":
                    clean_val = AmazonFixer.format_keywords(raw_val)
                
                # 寫入英國模板
                uk_sheet.cell(row=row_idx, column=k_col, value=clean_val)
        
        # B. 搬運五點描述 (1-5點)
        for i in range(1, 6):
            us_bp = us_h.get(f"keyproductfeatures{i}") or us_h.get(f"bulletpoint{i}")
            uk_bp = uk_h.get(f"bulletpoint{i}") or uk_h.get(f"keyproductfeatures{i}")
            
            if us_bp and uk_bp:
                bp_val = us_sheet.cell(row=row_idx, column=us_bp).value
                uk_sheet.cell(row=row_idx, column=uk_bp, value=AmazonFixer.clean_mojibake(bp_val))

        # C. 規則補齊：確保第一行 (Parent 行) SKU 範圍正確
        # 如果是 Parent 行，強制清空 Color 等欄位 (按您之前要求)
        parentage_col = us_h.get("parentage")
        if parentage_col:
            parentage_val = str(us_sheet.cell(row=row_idx, column=parentage_col).value).lower()
            if "parent" in parentage_val:
                # 確保父行 Color/Color Map 留空
                if uk_h.get("colour"): uk_sheet.cell(row=row_idx, column=uk_h["colour"], value="")
                if uk_h.get("colourmap"): uk_sheet.cell(row=row_idx, column=uk_h["colourmap"], value="")

    # 存檔
    uk_wb.save(output_name)
    print(f"✅ 成功！文件已生成：{output_name}")

if __name__ == "__main__":
    try:
        run_converter()
    except Exception as e:
        print(f"❌ 運行出錯：{e}")
