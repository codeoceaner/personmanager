# -*- coding: utf-8 -*-
"""动态看板服务：指标卡统计、四张图表数据源、多来源预警统一聚合。

看板只做聚合与排序，业务判定仍由各业务服务负责：
    住井 → personnel_service；健康 / 体检 → health_service；
    药品 → medicine_service；设备 → equipment_service。
"""

import datetime

import config
from db import database
from services import (assign_service, equipment_service, health_service,
                      medicine_service, personnel_service, platform_service)

# 级别排序权重（红色优先，超期并入红色）
_LEVEL_ORDER = {"红色报警": 0, "超期": 0, "黄色预警": 1, "提示": 2}

# 人员类预警来源：这三类预警的对象是在平台人员，需补充关联人员信息
_PERSON_SOURCES = ("住井超期", "健康异常", "体检到期")
# 非人员类（药品 / 设备）预警的关联人员字段统一占位
_EMPTY_PERSON = {"person_type": "—", "post": "—", "phone": "—", "resource": "—"}


def _today():
    return datetime.date.today()


def _person_scope(unit=None, person_type=None):
    """在平台人员的公共过滤条件（默认跟随当前平台范围）。"""
    where = ["status = ?", "deleted = 0"]
    params = [config.PERSON_STATUS_ONBOARD]
    scope_sql, scope_params = platform_service.platform_clause("personnel")
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if unit:
        where.append("unit = ?")
        params.append(unit)
    if person_type:
        where.append("person_type = ?")
        params.append(person_type)
    return " AND ".join(where), params


def _person_index():
    """工号 → 关联人员信息（人员类型 / 岗位 / 联系电话 / 房间或救生艇）。

    人员类预警的「对象」是在平台人员，预警列表需一并展示其联系方式与所在位置，
    方便值班人员快速定位与联络。房间 / 救生艇取当前在用分配记录，两者都有时
    以「房间 / 艇号」形式合并展示。一次查询建索引，避免每行单独查库。
    """
    scope_sql, scope_params = platform_service.platform_clause("p")
    scope = f" AND {scope_sql}" if scope_sql else ""
    rows = database.fetch_all(
        "SELECT p.emp_no, p.person_type, p.post, p.phone,"
        " (SELECT r.room_no FROM assignment a JOIN room r ON r.id = a.resource_id"
        "  WHERE a.person_id = p.id AND a.resource_type = ? AND a.status = ?) AS room_no,"
        " (SELECT l.boat_no FROM assignment a JOIN lifeboat l ON l.id = a.resource_id"
        "  WHERE a.person_id = p.id AND a.resource_type = ? AND a.status = ?) AS boat_no"
        f" FROM personnel p WHERE p.deleted = 0{scope}",
        (assign_service.RESOURCE_ROOM, assign_service.STATUS_USED,
         assign_service.RESOURCE_LIFEBOAT, assign_service.STATUS_USED)
        + tuple(scope_params))
    index = {}
    for row in rows:
        room = row["room_no"] or ""
        boat = row["boat_no"] or ""
        if room and boat:
            resource = f"{room} / {boat}"
        else:
            resource = room or boat or "—"
        index[row["emp_no"]] = {
            "person_type": row["person_type"] or "—",
            "post": row["post"] or "—",
            "phone": row["phone"] or "—",
            "resource": resource,
        }
    return index


# ---------------------------------------------------------------- 指标卡
def overview_metrics(unit=None, person_type=None):
    """顶部 6 个指标卡：在平台人数、三类人员、房间占用率、红色预警总数。"""
    clause, params = _person_scope(unit, person_type)
    onboard = database.fetch_one(
        f"SELECT COUNT(*) AS c FROM personnel WHERE {clause}", params)["c"]

    by_type = {name: 0 for name in config.PERSON_TYPES}
    for row in database.fetch_all(
            f"SELECT person_type, COUNT(*) AS c FROM personnel"
            f" WHERE {clause} GROUP BY person_type", params):
        if row["person_type"] in by_type:
            by_type[row["person_type"]] = row["c"]

    usage = assign_service.resource_usage()
    warnings = unified_warnings(unit=unit, person_type=person_type)
    return {
        "onboard": onboard,
        "internal": by_type.get("内部人员", 0),
        "outsource": by_type.get("外协人员", 0),
        "party": by_type.get("甲方人员", 0),
        "room_rate": usage["bed_rate"],
        "bed_used": usage["bed_used"],
        "bed_total": usage["bed_total"],
        "red_total": sum(1 for item in warnings if item["level"] == "红色报警"),
    }


# ---------------------------------------------------------------- 图表数据
def unit_distribution(unit=None, person_type=None, limit=None):
    """在平台人员按所属单位统计 → [(单位, 人数)]，用于柱状图。"""
    clause, params = _person_scope(unit, person_type)
    rows = database.fetch_all(
        f"SELECT CASE WHEN unit = '' THEN '未填写' ELSE unit END AS label,"
        f" COUNT(*) AS c FROM personnel WHERE {clause} GROUP BY label"
        " ORDER BY c DESC, label LIMIT ?",
        params + [limit or config.DASHBOARD_CHART_TOP_N])
    return [(row["label"], row["c"]) for row in rows]


def health_composition():
    """健康异常构成 → [(指标, 异常人数)]，用于饼图。"""
    counts = health_service.indicator_abnormal_counts()
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)


def flow_trend(days=None):
    """近 N 天上 / 下平台人数双线 → {labels, checkin, leave} 用于折线图。"""
    days = days or config.DASHBOARD_FLOW_DAYS
    start_day = _today() - datetime.timedelta(days=days - 1)
    dates = [(start_day + datetime.timedelta(days=i)).isoformat()
             for i in range(days)]
    start = dates[0]

    def _daily(table, column):
        scope_sql, scope_params = platform_service.platform_clause("p")
        join = " JOIN personnel p ON p.id = %s.person_id" % table
        scope = f" AND {scope_sql}" if scope_sql else ""
        rows = database.fetch_all(
            f"SELECT substr({column}, 1, 10) AS d, COUNT(*) AS c FROM {table}{join}"
            f" WHERE substr({column}, 1, 10) >= ?{scope} GROUP BY d",
            (start,) + tuple(scope_params))
        return {row["d"]: row["c"] for row in rows}

    checkin = _daily("checkin_record", "checkin_time")
    leave = _daily("leave_record", "leave_time")
    return {
        "dates": dates,
        "labels": [day[5:] for day in dates],          # MM-DD，横轴更紧凑
        "checkin": [checkin.get(day, 0) for day in dates],
        "leave": [leave.get(day, 0) for day in dates],
    }


def internal_onboard(by="unit", limit=None):
    """内部人员在岗人数按单位 / 岗位分组 → [(分组, 人数)]，用于横向条形图。"""
    column = "post" if by == "post" else "unit"
    scope_sql, scope_params = platform_service.platform_clause("personnel")
    scope = f" AND {scope_sql}" if scope_sql else ""
    rows = database.fetch_all(
        f"SELECT CASE WHEN {column} = '' THEN '未填写' ELSE {column} END AS label,"
        f" COUNT(*) AS c FROM personnel WHERE person_type = ? AND status = ?"
        f" AND deleted = 0{scope} GROUP BY label ORDER BY c DESC, label LIMIT ?",
        (config.PERSON_TYPES[0], config.PERSON_STATUS_ONBOARD)
        + tuple(scope_params) + (limit or config.DASHBOARD_CHART_TOP_N,))
    return [(row["label"], row["c"]) for row in rows]


# ---------------------------------------------------------------- 预警聚合
def _onboard_warnings(unit=None, person_type=None):
    clause, params = _person_scope(unit, person_type)
    rows = database.fetch_all(
        f"SELECT emp_no, name, unit, onboard_time FROM personnel WHERE {clause}",
        params)
    warnings = []
    for row in rows:
        days = personnel_service.onboard_days(row["onboard_time"])
        level = personnel_service.onboard_level(days)
        if level == "正常":
            continue
        warnings.append({
            "source": "住井超期", "target": row["name"], "code": row["emp_no"],
            "unit": row["unit"] or "—",
            "detail": f"住井 {days} 天",
            "level": "红色报警" if level in ("红色报警", "超期") else "黄色预警",
            "urgency": -days,
        })
    return warnings


def _health_warnings(unit=None, person_type=None):
    warnings = []
    for row in health_service.latest_abnormal_persons(limit=10000):
        if unit and row["unit"] != unit:
            continue
        if person_type and row["person_type"] != person_type:
            continue
        warnings.append({
            "source": "健康异常", "target": row["name"], "code": row["emp_no"],
            "unit": row["unit"] or "—",
            "detail": row["abnormal_items"] or "指标越限",
            "level": row["abnormal_level"],
            "urgency": 0,
        })
    return warnings


def _checkup_warnings(unit=None, person_type=None):
    warnings = []
    for row in health_service.list_profiles(only_onboard=True, unit=unit,
                                            person_type=person_type):
        level = row["checkup_level"]
        if level not in ("未体检", "已到期"):
            continue
        last = row["last_checkup_date"] or "从未体检"
        warnings.append({
            "source": "体检到期", "target": row["name"], "code": row["emp_no"],
            "unit": row["unit"] or "—",
            "detail": last,
            "level": "红色报警" if level == "已到期" else "黄色预警",
            "urgency": 0,
        })
    return warnings


def _supply_warnings():
    """药品效期 / 库存与设备维保预警，单位不适用，统一记为「—」。"""
    warnings = []
    for item in medicine_service.medicine_warnings():
        warnings.append({
            "source": item["source"], "target": item["name"], "code": item["code"],
            "unit": "—", "detail": item["detail"], "level": item["level"],
            "urgency": item["sort_urgency"],
        })
    for item in equipment_service.equipment_warnings():
        warnings.append({
            "source": item["source"], "target": item["name"], "code": item["code"],
            "unit": "—", "detail": item["detail"], "level": item["level"],
            "urgency": item["sort_urgency"],
        })
    return warnings


def unified_warnings(level=None, source=None, unit=None, person_type=None):
    """多来源预警统一聚合，红色优先排序，供看板预警列表与角标使用。"""
    warnings = (_onboard_warnings(unit, person_type)
                + _health_warnings(unit, person_type)
                + _checkup_warnings(unit, person_type)
                + _supply_warnings())
    if unit:
        warnings = [item for item in warnings
                    if item["unit"] == unit or item["unit"] == "—"]
    if source:
        warnings = [item for item in warnings if item["source"] == source]
    if level:
        warnings = [item for item in warnings if item["level"] == level]

    # 列表列宽受限，对象与编码 / 编号合并为一列展示；人员类预警再补充关联人员信息
    index = None
    for item in warnings:
        item["target_code"] = f"{item.get('target') or '—'} / {item.get('code') or '—'}"
        if item["source"] in _PERSON_SOURCES:
            if index is None:
                index = _person_index()
            item.update(index.get(item["code"], _EMPTY_PERSON))
        else:
            item.update(_EMPTY_PERSON)

    warnings.sort(key=lambda item: (_LEVEL_ORDER.get(item["level"], 9),
                                    item["source"], item["urgency"]))
    return warnings


def warning_counts(source=None, unit=None):
    """预警级别计数（红色 / 黄色 / 提示）。"""
    warnings = unified_warnings(source=source, unit=unit)
    return {
        "红色报警": sum(1 for item in warnings if item["level"] == "红色报警"),
        "黄色预警": sum(1 for item in warnings if item["level"] == "黄色预警"),
        "提示": sum(1 for item in warnings if item["level"] == "提示"),
    }


def badge_counts():
    """导航角标：动态看板与医疗物资管理的预警条数与级别（红色优先，无红色取黄色）。"""
    def _pack(counts):
        if counts["红色报警"]:
            return counts["红色报警"], "红色报警"
        if counts["黄色预警"]:
            return counts["黄色预警"], "黄色预警"
        return 0, "红色报警"

    supply_sources = ("药品效期", "药品库存", "设备维保")
    total = {"红色报警": 0, "黄色预警": 0, "提示": 0}
    supply = {"红色报警": 0, "黄色预警": 0, "提示": 0}
    for item in unified_warnings():
        level = item["level"]
        if level in total:
            total[level] += 1
            if item["source"] in supply_sources:
                supply[level] += 1
    dashboard_count, dashboard_level = _pack(total)
    supply_count, supply_level = _pack(supply)
    return {"dashboard": (dashboard_count, dashboard_level),
            "supply": (supply_count, supply_level)}