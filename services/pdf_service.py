# -*- coding: utf-8 -*-
"""PDF 导出服务：把数据集渲染为带固定页眉模板的 A4 横向 PDF 表格。

与 excel_service.export_table 保持对称签名，复用同一份「中文表头, 字段名」列定义。
使用 matplotlib 的 PdfPages 生成，不引入额外依赖；matplotlib 不可用时降级为
PDF_AVAILABLE = False，由界面禁用 PDF 选项并提示。
"""

import datetime
import textwrap

import config

try:                                                # matplotlib 已是打包依赖
    import matplotlib
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    # 中文字体：与看板 / 趋势图保持一致的字体回退链，避免 PDF 中文乱码
    matplotlib.rcParams["font.sans-serif"] = [
        config.FONT_FAMILY, config.FONT_FAMILY_FALLBACK, "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    PDF_AVAILABLE = True
except Exception:                                   # noqa: BLE001 环境缺失时降级
    PDF_AVAILABLE = False

# A4 横向画布尺寸（英寸）
_PAGE_W, _PAGE_H = 11.69, 8.27
_HEADER_COLOR = "#1B4965"       # 与界面主色一致
_STRIPE_COLOR = "#EEF3F7"       # 斑马纹浅底


def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _font_size(column_count):
    """列越多字号越小，尽量在 A4 横向内放下。"""
    if column_count <= 10:
        return 8.0
    if column_count <= 14:
        return 7.0
    if column_count <= 18:
        return 6.0
    return 5.2


def _wrap(value, width):
    text = "" if value is None else str(value)
    if not text:
        return ""
    return textwrap.fill(text, width=width)


def _display_width(text):
    """估算显示宽度：中文按 2 个西文字宽计算。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in str(text))


def _layout(columns, records, font_size):
    """按内容估算列宽占比与每列折行宽度，避免编号 / 数字被硬折行。"""
    weights = []
    for label, key in columns:
        longest = _display_width(label)
        for row in records[:200]:
            longest = max(longest, min(_display_width(row.get(key, "")), 26))
        weights.append(max(6.0, float(longest)))
    total = sum(weights) or 1.0
    col_widths = [w / total for w in weights]
    chars_per_line = max(40, int(10.9 * 72 / (font_size * 0.62)))
    wrap_widths = [max(6, min(40, int(frac * chars_per_line))) for frac in col_widths]
    return col_widths, wrap_widths


def export_table(prefix, title, columns, records, subtitle=None):
    """导出为 PDF，返回文件路径。

    columns 为 [(中文表头, 字段名)]；records 为 dict 列表；subtitle 展示在页眉
    （通常是导出的时间段），作为「固定模板」的一部分。
    """
    if not PDF_AVAILABLE:
        raise RuntimeError("当前环境未安装 matplotlib，无法生成 PDF")

    headers = [label for label, _key in columns]
    font_size = _font_size(len(columns))
    col_widths, wrap_widths = _layout(columns, records, font_size)

    # 行高按字号换算成画布高度占比，行数直接决定每页容量
    row_height = (font_size * 1.7 / 72) / _PAGE_H
    top = 1 - 1.05 / _PAGE_H                    # 页眉下方
    bottom = 0.09
    max_rows = max(1, int((top - bottom) / row_height) - 1)
    total = len(records)
    chunks = [records[i:i + max_rows] for i in range(0, total, max_rows)] or [[]]

    path = config.REPORT_DIR / f"{prefix}_{_stamp()}.pdf"
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    with PdfPages(path) as pdf:
        for page_index, chunk in enumerate(chunks, start=1):
            fig = Figure(figsize=(_PAGE_W, _PAGE_H))
            ax = fig.add_axes([0, 0, 1, 1])
            ax.axis("off")

            # ---- 固定页眉：应用名 / 公司 / 标题 / 时间段 / 生成时间 / 页码
            fig.text(0.035, 0.965, config.APP_NAME, fontsize=11,
                     fontweight="bold", color=_HEADER_COLOR)
            fig.text(0.035, 0.938, config.COMPANY, fontsize=8, color="#6B7280")
            fig.text(0.5, 0.963, title, fontsize=13, fontweight="bold",
                     ha="center", color=_HEADER_COLOR)
            fig.text(0.965, 0.965, f"第 {page_index} / {len(chunks)} 页",
                     fontsize=8, ha="right", color="#6B7280")
            fig.text(0.035, 0.912, subtitle or "全部数据",
                     fontsize=8, color="#6B7280")
            fig.text(0.965, 0.912, f"生成时间：{generated}",
                     fontsize=8, ha="right", color="#6B7280")

            if not chunk:
                fig.text(0.5, 0.5, "该时间段内无数据", fontsize=12,
                         ha="center", va="center", color="#6B7280")
                pdf.savefig(fig)
                fig.clear()
                continue

            cell_text = [[_wrap(row.get(key, ""), wrap_widths[i])
                          for i, (_label, key) in enumerate(columns)]
                         for row in chunk]
            height = (len(chunk) + 1) * row_height
            table = ax.table(
                cellText=cell_text, colLabels=headers, colWidths=col_widths,
                cellLoc="left", colLoc="center",
                bbox=[0.035, top - height, 0.93, height])
            table.auto_set_font_size(False)
            table.set_fontsize(font_size)

            for (r, c), cell in table.get_celld().items():
                cell.set_linewidth(0.3)
                cell.set_edgecolor("#D6DEE5")
                if r == 0:
                    cell.set_facecolor(_HEADER_COLOR)
                    cell.get_text().set_color("#FFFFFF")
                    cell.get_text().set_fontweight("bold")
                    cell.get_text().set_ha("center")
                elif r % 2 == 0:
                    cell.set_facecolor(_STRIPE_COLOR)

            fig.text(0.035, 0.045, f"共 {total} 条记录", fontsize=8, color="#6B7280")
            fig.text(0.965, 0.045, config.APP_SHORT_NAME, fontsize=8,
                     ha="right", color="#6B7280")
            pdf.savefig(fig)
            fig.clear()

    return path