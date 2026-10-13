# -*- coding: utf-8 -*-
"""Excel 导入导出服务：模板生成、批量导出、逐行校验导入与错误报告。

统一使用 openpyxl 直接读写 .xlsx，不引入 pandas，降低打包体积与依赖风险。

导入策略（产品设计第 10 节容错要求）——逐行校验、错误不中断：
    合法行正常入库；非法行不写入库，汇总到《导入错误报告.xlsx》供下载核对。
"""

import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config
from services import personnel_service

_HEADER_FILL = PatternFill("solid", fgColor="1B4965")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
_TITLE_FONT = Font(bold=True, size=12)
_WRAP_TOP = Alignment(wrap_text=True, vertical="top")

# 导入时提交给登记服务的字段（房间 / 救生艇单独作为资源参数传递）
_DATA_KEYS = [key for _label, key, _required in config.EXCEL_COLUMNS
              if key not in ("room_no", "boat_no")]


# ---------------------------------------------------------------- 小工具
def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _cell_text(value):
    """单元格值归一化为文本：None→空串、日期→标准格式、整数浮点→整数串。"""
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _template_headers():
    return [f"{label}*" if required else label
            for label, _key, required in config.EXCEL_COLUMNS]


def _style_header(worksheet, headers):
    for index, title in enumerate(headers, start=1):
        cell = worksheet.cell(row=1, column=index, value=title)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.column_dimensions[get_column_letter(index)].width = max(
            len(title) * 2 + 4, 12)
    worksheet.freeze_panes = "A2"


# 表头智能识别：除标准表头外，兼容常见别称（比较前统一去掉 * 与空格）。
# 命中规则：标准表头优先，别称次之；同一字段只取最先出现的列。
_HEADER_ALIASES = {
    "名字": "name", "姓名": "name",
    "身份证": "id_card", "身份证号码": "id_card", "身份证件号": "id_card",
    "手机": "phone", "手机号": "phone", "手机号码": "phone",
    "电话": "phone", "联系方式": "phone", "联系手机": "phone",
    "单位": "unit", "工作单位": "unit", "所属单位名称": "unit",
    "类型": "person_type", "人员类别": "person_type", "人员类型": "person_type",
    "工种": "post", "岗位": "post", "岗位工种": "post",
    "上平台日期": "onboard_time", "上平台时间": "onboard_time", "登平台时间": "onboard_time",
    "预计下平台": "planned_off_time", "预计下平台日期": "planned_off_time",
    "紧急联系": "emergency_contact", "紧急联系人": "emergency_contact",
    "紧急联系电话": "emergency_phone", "紧急联系手机": "emergency_phone",
    "房间": "room_no", "房间号": "room_no",
    "救生艇": "boat_no", "救生艇编号": "boat_no", "艇号": "boat_no",
    "性别": "gender", "年龄": "age", "工号": "emp_no",
}


def _header_index(worksheet):
    """按表头文本建立 字段名 → 列号 索引，容忍 *、空格差异与常见别称。"""
    standard = {label.replace(" ", ""): key
                for label, key, _required in config.EXCEL_COLUMNS}
    mapping = {}
    for column in range(1, worksheet.max_column + 1):
        text = _cell_text(worksheet.cell(row=1, column=column).value)
        text = text.replace("*", "").replace(" ", "")
        if not text:
            continue
        key = standard.get(text) or _HEADER_ALIASES.get(text)
        if key and key not in mapping:
            mapping[key] = column
    return mapping


def _sample_row(person_type):
    return {
        "emp_no": "NM2026001", "name": "张三", "gender": "男", "age": 35,
        "id_card": "110101199001011234", "phone": "13800000000",
        "unit": "中海油服", "person_type": person_type, "post": "钻井工",
        "onboard_time": "2026-10-01 08:00", "planned_off_time": "2026-10-20",
        "emergency_contact": "李四", "emergency_phone": "13900000000",
        "room_no": "", "boat_no": "",
    }


# ---------------------------------------------------------------- 模板
def template_path(person_type):
    return config.TEMPLATE_DIR / f"{person_type}导入模板.xlsx"


def export_template(person_type):
    """生成导入模板：表头（必填带 *）+ 示例行 + 填写说明。返回文件路径。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "人员信息"
    headers = _template_headers()
    _style_header(sheet, headers)
    sample = _sample_row(person_type)
    for index, (_label, key, _required) in enumerate(config.EXCEL_COLUMNS, start=1):
        sheet.cell(row=2, column=index, value=sample.get(key, ""))

    notes = workbook.create_sheet("填写说明")
    lines = [
        f"{config.APP_NAME} — {person_type}批量导入模板",
        "1. 仅在「人员信息」工作表填写，第 1 行为表头，请勿修改表头文字。",
        "2. 带 * 的列为必填项，其余列可留空。",
        "3. 性别仅支持：男 / 女；人员类型仅支持：内部人员 / 外协人员 / 甲方人员。",
        "4. 年龄需为 18–65 的整数；身份证号 18 位（末位可为 X）。",
        "5. 联系电话与紧急联系电话需为 11 位手机号（以 1 开头）。",
        "6. 上平台时间格式：2026-10-01 08:00（可省略时间，默认 08:00）；"
        "预计下平台时间格式：2026-10-20。",
        "7. 房间号 / 救生艇编号可留空，系统按性别与单位自动分配；"
        "如需指定请填写编号（如 A101、LB-01）。",
        "8. 第 2 行为示例数据，导入前请删除；住井已达 31 天（在平台满 30 个自然日）"
        "的人员会被拦截。",
        "9. 导入逐行校验：合法行正常入库，非法行汇总到导入错误报告中。",
    ]
    for row_index, text in enumerate(lines, start=1):
        cell = notes.cell(row=row_index, column=1, value=text)
        if row_index == 1:
            cell.font = _TITLE_FONT
    notes.column_dimensions["A"].width = 96

    path = template_path(person_type)
    workbook.save(path)
    return path


# ---------------------------------------------------------------- 导出
def export_records(records, person_type):
    """批量导出人员台账（含住井天数与状态），返回文件路径。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = person_type
    headers = [label for label, _key, _required in config.EXCEL_COLUMNS] + \
              [label for label, _key in config.EXCEL_EXTRA_COLUMNS]
    _style_header(sheet, headers)
    for row_index, record in enumerate(records, start=2):
        column_index = 1
        for _label, key, _required in config.EXCEL_COLUMNS:
            sheet.cell(row=row_index, column=column_index, value=record.get(key, ""))
            column_index += 1
        for _label, key in config.EXCEL_EXTRA_COLUMNS:
            sheet.cell(row=row_index, column=column_index, value=record.get(key, ""))
            column_index += 1

    path = config.REPORT_DIR / f"{person_type}台账_{_stamp()}.xlsx"
    workbook.save(path)
    return path


def export_table(prefix, sheet_title, columns, records):
    """通用导出：columns 为 [(中文表头, 字段名)]，records 为记录列表。返回文件路径。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title[:31]
    _style_header(sheet, [label for label, _key in columns])
    for row_index, record in enumerate(records, start=2):
        for column_index, (_label, key) in enumerate(columns, start=1):
            value = record.get(key, "")
            sheet.cell(row=row_index, column=column_index,
                       value="" if value is None else value)
    path = config.REPORT_DIR / f"{prefix}_{_stamp()}.xlsx"
    workbook.save(path)
    return path


# ---------------------------------------------------------------- 导入
def import_records(path, person_type, operator):
    """逐行校验导入，返回 {total, ok, fail, errors, report_path}。"""
    workbook = load_workbook(path, data_only=True)
    sheet = workbook["人员信息"] if "人员信息" in workbook.sheetnames else workbook.worksheets[0]

    index = _header_index(sheet)
    missing = [label for label, key, required in config.EXCEL_COLUMNS
               if required and key not in index]
    if missing:
        workbook.close()
        raise ValueError("模板缺少必填列：" + "、".join(missing))

    total = 0
    ok_count = 0
    errors = []
    for row_index in range(2, sheet.max_row + 1):
        values = {key: _cell_text(sheet.cell(row=row_index, column=column).value)
                  for key, column in index.items()}
        if not any(values.values()):          # 跳过空行
            continue
        total += 1
        emp_no = values.get("emp_no", "")
        name = values.get("name", "")

        data = {key: values.get(key, "") for key in _DATA_KEYS}
        data["person_type"] = values.get("person_type") or person_type

        ok, message, _person_id = personnel_service.register_person(
            data, operator,
            room_text=values.get("room_no", ""), boat_text=values.get("boat_no", ""))
        if ok:
            ok_count += 1
        else:
            errors.append((row_index, emp_no, name, message))
    workbook.close()

    report_path = _write_error_report(errors, person_type) if errors else None
    return {"total": total, "ok": ok_count, "fail": len(errors),
            "errors": errors, "report_path": report_path}


def _write_error_report(errors, person_type):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "导入错误"
    _style_header(sheet, ["行号", "工号", "姓名", "错误原因"])
    sheet.column_dimensions["D"].width = 60
    for offset, (row_index, emp_no, name, message) in enumerate(errors, start=2):
        sheet.cell(row=offset, column=1, value=row_index)
        sheet.cell(row=offset, column=2, value=emp_no)
        sheet.cell(row=offset, column=3, value=name)
        sheet.cell(row=offset, column=4, value=message).alignment = _WRAP_TOP
    path = config.REPORT_DIR / f"导入错误报告_{person_type}_{_stamp()}.xlsx"
    workbook.save(path)
    return path