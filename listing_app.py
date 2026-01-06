import openpyxl
import io

def cross_border_transfer(us_file_buffer, uk_template_buffer):
    """
    创意功能：将美国站数据一键搬运至英国站
    """
    # 1. 加载已填写的美国站文件和空白的英国站模板
    us_wb = openpyxl.load_workbook(us_file_buffer)
    us_sheet = us_wb.active
    
    uk_wb = openpyxl.load_workbook(uk_template_buffer, keep_vba=True)
    uk_sheet = uk_wb.active

    # 2. 建立双站点表头索引映射 (解决表头顺序不一致问题)
    us_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in us_sheet[3]} # 假设表头在第3行
    uk_h = {str(c.value).strip().lower().replace(" ", ""): c.column for c in uk_sheet[3]}

    # 定义核心对位逻辑
    transfer_map = {
        "sellersku": "sellersku",
        "parentsku": "parentsku",
        "productname": "itemname",      # US到UK的名称变化
        "brandname": "brandname",
        "productdescription": "productdescription",
        "generickeyword": "searchterms", # US关键字到UK关键字
        "color": "colour",              # 拼写自动适配
        "colormap": "colourmap",
        "size": "size",
        "sizemap": "sizemap",
        "standardprice": "standardprice"
    }

    # 3. 开始搬运数据 (从第4行数据行开始扫描)
    for row_idx in range(4, us_sheet.max_row + 1):
        for us_key, uk_key in transfer_map.items():
            if us_key in us_h and uk_key in uk_h:
                cell_value = us_sheet.cell(row=row_idx, column=us_h[us_key]).value
                if cell_value:
                    # 写入英国站对应位置
                    uk_sheet.cell(row=row_idx, column=uk_h[uk_key], value=cell_value)
                    
        # 搬运五点描述 (Bullet Points)
        for i in range(1, 6):
            us_bp_key = f"keyproductfeatures{i}"
            uk_bp_key = f"bulletpoint{i}" # 英国模板有时叫法不同
            # 尝试多种可能的表头对位
            us_col = us_h.get(us_bp_key) or us_h.get(f"bulletpoint{i}")
            uk_col = uk_h.get(uk_bp_key) or uk_h.get(f"keyproductfeatures{i}")
            
            if us_col and uk_col:
                bp_val = us_sheet.cell(row=row_idx, column=us_col).value
                uk_sheet.cell(row=row_idx, column=uk_col, value=bp_val)

    # 返回处理后的英国站工作簿
    return uk_wb
