# -*- coding: utf-8 -*-
"""数据管理服务：「数据管理」页唯一后端。

统一封装五类数据集的固定模板导出（Excel / PDF）与任意时间段过滤，
并转调人员批量导入 / 模板下载，避免界面直接依赖各业务服务与文件服务。
"""

import datetime

import config
from db import database
from services import (equipment_service, excel_service, health_service,
                      medicine_service, pdf_service, personnel_service)

# 各数据集导出列（(中文表头, 字段名)）——「固定模板」的唯一来源
_PERSONNEL_COLUMNS = ([(label, key) for label, key, _required in config.EXCEL_COLUMNS]
                      + list(config.EXCEL_EXTRA_COLUMNS))

# 数据集目录：key / 名称 / 时间字段标签 / 时间字段名 / 列 / 取数函数
DATASETS = [
    {"key": "personnel", "name": "人员台账",
     "date_label": "上平台时间", "date_key": "onboard_time",
     "columns": _PERSONNEL_COLUMNS, "fetch": lambda: _personnel()},
    {"key": "health", "name": "健康档案",
     "date_label": "最近体检日期", "date_key": "last_checkup_date",
     "columns": config.HEALTH_EXPORT_COLUMNS, "fetch": lambda: health_service.list_profiles()},
    {"key": "monitor", "name": "日常监测",
     "date_label": "监测日期", "date_key": "check_date",
     "columns": config.MONITOR_EXPORT_COLUMNS, "fetch": lambda: health_service.monitor_summary()},
    {"key": "medicine", "name": "药品台账",
     "date_label": "最近效期", "date_key": "nearest_expire",
     "columns": config.MEDICINE_EXPORT_COLUMNS, "fetch": lambda: medicine_service.list_medicines()},
    {"key": "equipment", "name": "医疗设备台账",
     "date_label": "启用日期", "date_key": "start_date",
     "columns": config.EQUIPMENT_EXPORT_COLUMNS, "fetch": lambda: equipment_service.list_equipment()},
]

DATASET_MAP = {item["key"]: item for item in DATASETS}


def _personnel():
    records, _total = personnel_service.list_personnel(page_size=100000)
    return records


def _operator_id(username):
    if not username:
        return None
    row = database.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    return row["id"] if row else None


# ---------------------------------------------------------------- 查询
def dataset_options():
    """供界面渲染下拉：[(key, 名称, 时间字段标签)]。"""
    return [(item["key"], item["name"], item["date_label"]) for item in DATASETS]


def _validate_range(start, end):
    """校验时间段：格式 YYYY-MM-DD，且开始 ≤ 结束。非法抛 ValueError。"""
    parsed = {}
    for label, value in (("开始", start), ("结束", end)):
        if not value:
            continue
        try:
            parsed[label] = datetime.datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"{label}日期格式应为 YYYY-MM-DD")
    if "开始" in parsed and "结束" in parsed and parsed["开始"] > parsed["结束"]:
        raise ValueError("开始日期不能晚于结束日期")


def _in_range(value, start, end):
    """按日期字符串（取前 10 位）判断是否落在区间内。"""
    text = str(value or "")[:10]
    if not text:
        return False
    if start and text < start:
        return False
    if end and text > end:
        return False
    return True


def collect(key, start=None, end=None):
    """按数据集与时间段取数，返回 {key, name, date_label, columns, rows}。"""
    item = DATASET_MAP.get(key)
    if item is None:
        raise ValueError(f"未知数据集：{key}")
    _validate_range(start, end)

    rows = item["fetch"]()
    if start or end:
        rows = [row for row in rows if _in_range(row.get(item["date_key"]), start, end)]
    # 空值统一为空白，避免表格与文件中出现 "None"
    for row in rows:
        for _label, key in item["columns"]:
            if row.get(key) is None:
                row[key] = ""
    return {"key": item["key"], "name": item["name"], "date_label": item["date_label"],
            "columns": item["columns"], "rows": rows}


def range_label(start=None, end=None):
    if not start and not end:
        return "全部"
    return f"{start or '最早'}至{end or '最新'}"


# ---------------------------------------------------------------- 导出
def export(key, fmt="xlsx", start=None, end=None, operator="system"):
    """导出指定数据集，返回 (文件路径, 记录条数)。

    fmt：xlsx（Excel）/ pdf。导出动作写入操作日志，便于审计。
    """
    result = collect(key, start, end)
    rows = result["rows"]
    label = range_label(start, end)
    prefix = f"{result['name']}_{label}"
    subtitle = f"时间字段：{result['date_label']}｜时间范围：{label}"

    if fmt == "pdf":
        path = pdf_service.export_table(prefix, result["name"],
                                        result["columns"], rows, subtitle=subtitle)
    else:
        path = excel_service.export_table(prefix, result["name"],
                                          result["columns"], rows)

    database.write_op_log(_operator_id(operator), "数据管理", "导出数据",
                          result["name"], f"{fmt}｜{label}｜{len(rows)} 条")
    return path, len(rows)


def pdf_available():
    return pdf_service.PDF_AVAILABLE


# ---------------------------------------------------------------- 导入
def template(person_type):
    """生成人员导入模板，返回文件路径。"""
    return excel_service.export_template(person_type)


def import_personnel(path, person_type, operator):
    """人员批量导入（逐行校验、错误不中断），返回结果字典。"""
    return excel_service.import_records(path, person_type, operator)