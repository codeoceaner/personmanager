# -*- coding: utf-8 -*-
"""医疗设备服务：设备台账、校准 / 维保到期提醒、一艇一册急救设备核对、使用与检查记录。

维保提醒规则（产品设计 5.3.2):
    距下次校准 / 维保 ≤30 天 → 即将到期（标黄）；已超期 → 已超期（标红）。
"""

import datetime

import config
from db import database
from services import personnel_service, platform_service


# ---------------------------------------------------------------- 小工具
def _today():
    return datetime.date.today()


def maintain_level(next_calibration):
    """维保状态：正常 / 即将到期 / 已超期。"""
    date = personnel_service.parse_datetime(next_calibration, with_time=False)
    if date is None:
        return "正常"
    days = (date.date() - _today()).days
    if days < 0:
        return "已超期"
    if days <= database.get_int("equipment_notice_days",
                                config.EQUIPMENT_MAINTAIN_NOTICE_DAYS):
        return "即将到期"
    return "正常"


def days_to_maintain(next_calibration):
    date = personnel_service.parse_datetime(next_calibration, with_time=False)
    if date is None:
        return None
    return (date.date() - _today()).days


# ---------------------------------------------------------------- 设备台账
def get_equipment(equipment_id):
    row = database.fetch_one("SELECT * FROM equipment WHERE id = ?", (equipment_id,))
    return dict(row) if row else None


def list_equipment(keyword=None, status=None, only_due=False, boat_no=None,
                   platform_id=platform_service._UNSET):
    """设备台账：附维保状态与使用记录数。"""
    where = []
    params = []
    scope_sql, scope_params = platform_service.platform_clause("e", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if status:
        where.append("e.status = ?")
        params.append(status)
    if boat_no:
        where.append("e.keep_boat_no = ?")
        params.append(boat_no)
    if keyword:
        where.append("(e.name LIKE ? OR e.serial_no LIKE ? OR e.model LIKE ?"
                     " OR e.keeper LIKE ?)")
        params.extend([f"%{keyword}%"] * 4)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    rows = database.fetch_all(
        "SELECT e.*, (SELECT COUNT(*) FROM equipment_use u WHERE u.equipment_id = e.id)"
        " AS use_count FROM equipment e"
        f"{clause} ORDER BY e.name, e.serial_no LIMIT 2000", params)

    records = []
    for row in rows:
        item = dict(row)
        item["maintain_status"] = maintain_level(item.get("next_calibration"))
        item["days_to_maintain"] = days_to_maintain(item.get("next_calibration"))
        if only_due and item["maintain_status"] == "正常":
            continue
        records.append(item)
    records.sort(key=lambda item: (
        0 if item["maintain_status"] == "已超期" else
        1 if item["maintain_status"] == "即将到期" else 2,
        item["name"]))
    return records


def save_equipment(equipment_id, data, operator):
    """新增或更新设备档案。返回 (是否成功, 提示)。"""
    name = (data.get("name") or "").strip()
    serial_no = (data.get("serial_no") or "").strip()
    if not name:
        return False, "设备名称不能为空"
    if not serial_no:
        return False, "设备编号不能为空"
    status = (data.get("status") or "").strip()
    if status not in config.EQUIPMENT_STATUSES:
        return False, "状态只能为 " + " / ".join(config.EQUIPMENT_STATUSES)

    dates = {}
    for key, label in (("purchase_date", "购置日期"), ("start_date", "启用日期"),
                       ("last_calibration", "上次校准"), ("next_calibration", "下次校准")):
        value = (data.get(key) or "").strip()[:10]
        if value and personnel_service.parse_datetime(value, with_time=False) is None:
            return False, f"{label}格式应为 2026-10-01"
        dates[key] = value or None

    duplicate = database.fetch_one(
        "SELECT id FROM equipment WHERE serial_no = ? AND id <> ?",
        (serial_no, equipment_id or 0))
    if duplicate:
        return False, f"设备编号 {serial_no} 已存在"

    fields = (name, (data.get("model") or "").strip(), serial_no,
              (data.get("manufacturer") or "").strip(), dates["purchase_date"],
              dates["start_date"], (data.get("location") or "").strip(),
              (data.get("keeper") or "").strip(), status, dates["last_calibration"],
              dates["next_calibration"], (data.get("keep_boat_no") or "").strip())

    with database.get_connection() as conn:
        if equipment_id:
            conn.execute(
                "UPDATE equipment SET name = ?, model = ?, serial_no = ?,"
                " manufacturer = ?, purchase_date = ?, start_date = ?, location = ?,"
                " keeper = ?, status = ?, last_calibration = ?, next_calibration = ?,"
                " keep_boat_no = ? WHERE id = ?", fields + (equipment_id,))
        else:
            conn.execute(
                "INSERT INTO equipment(platform_id, name, model, serial_no, manufacturer,"
                " purchase_date, start_date, location, keeper, status, last_calibration,"
                " next_calibration, keep_boat_no) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (platform_service.current_id(),) + fields)

    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "保存设备档案", serial_no, f"{name}｜{status}")
    return True, f"设备「{name}」已保存"


def delete_equipment(equipment_id, operator):
    """删除设备：存在使用记录时不删除，改为提示报废。"""
    equipment = get_equipment(equipment_id)
    if equipment is None:
        return False, "设备不存在"
    used = database.fetch_one(
        "SELECT COUNT(*) AS n FROM equipment_use WHERE equipment_id = ?",
        (equipment_id,))["n"]
    if used:
        return False, "该设备已有使用 / 检查记录，不能删除，请改为报废"
    with database.get_connection() as conn:
        conn.execute("DELETE FROM equipment WHERE id = ?", (equipment_id,))
    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "删除设备档案", equipment["serial_no"], equipment["name"])
    return True, f"设备「{equipment['name']}」已删除"


# ---------------------------------------------------------------- 预警与核对
def equipment_warnings():
    """校准 / 维保即将到期或已超期的设备。"""
    warnings = []
    for record in list_equipment(only_due=True):
        days = record["days_to_maintain"]
        if record["maintain_status"] == "已超期":
            detail = f"维保已超期 {-days} 天（应于 {record['next_calibration']}）"
        else:
            detail = (f"距维保到期 {days} 天（{record['next_calibration']}）")
        warnings.append({
            "source": "设备维保", "code": record["serial_no"], "name": record["name"],
            "category": record.get("status") or "—", "batch_no": "—",
            "detail": detail,
            "level": "红色报警" if record["maintain_status"] == "已超期" else "黄色预警",
            "sort_urgency": days if days is not None else 9999,
        })
    warnings.sort(key=lambda item: (
        0 if item["level"] == "红色报警" else 1, item["sort_urgency"]))
    return warnings


def equipment_summary(platform_id=platform_service._UNSET):
    warnings = equipment_warnings()
    scope_sql, scope_params = platform_service.platform_clause("equipment", platform_id)
    scope = f" AND {scope_sql}" if scope_sql else ""
    in_use = database.fetch_one(
        f"SELECT COUNT(*) AS n FROM equipment WHERE status = '在用'{scope}",
        scope_params)["n"]
    return {"in_use": in_use,
            "red": sum(1 for item in warnings if item["level"] == "红色报警"),
            "yellow": sum(1 for item in warnings if item["level"] == "黄色预警")}


def boat_options(platform_id=platform_service._UNSET):
    """救生艇编号选项：设备台账中出现过的 + 救生艇表的编号（限平台范围）。"""
    scope = platform_service.resolve(platform_id)
    equip_sql = ("SELECT DISTINCT keep_boat_no FROM equipment"
                 " WHERE keep_boat_no IS NOT NULL AND keep_boat_no <> ''")
    boat_sql = "SELECT boat_no FROM lifeboat"
    params = []
    if scope is not None:
        equip_sql += " AND platform_id = ?"
        boat_sql += " WHERE platform_id = ?"
        params.append(scope)
    options = []
    for row in database.fetch_all(equip_sql, params):
        options.append(row["keep_boat_no"])
    for row in database.fetch_all(boat_sql + " ORDER BY boat_no", params):
        if row["boat_no"] not in options:
            options.append(row["boat_no"])
    return options


def boat_checklist(boat_no):
    """一艇一册：某救生艇配置的急救设备清单与齐全情况。"""
    rows = list_equipment(boat_no=boat_no) if boat_no else []
    total = len(rows)
    normal = sum(1 for item in rows if item["status"] == "在用"
                 and item["maintain_status"] == "正常")
    return {"boat_no": boat_no, "rows": rows, "total": total, "normal": normal,
            "abnormal": total - normal}


# ---------------------------------------------------------------- 使用记录
def list_uses(equipment_id=None, keyword=None, limit=300,
              platform_id=platform_service._UNSET):
    where = []
    params = []
    scope_sql, scope_params = platform_service.platform_clause("e", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if equipment_id:
        where.append("u.equipment_id = ?")
        params.append(equipment_id)
    if keyword:
        where.append("(e.name LIKE ? OR e.serial_no LIKE ? OR p.name LIKE ?"
                     " OR u.item LIKE ?)")
        params.extend([f"%{keyword}%"] * 4)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = database.fetch_all(
        "SELECT u.*, e.name AS equipment_name, e.serial_no, p.name AS person_name,"
        " p.emp_no FROM equipment_use u"
        " JOIN equipment e ON e.id = u.equipment_id"
        " LEFT JOIN personnel p ON p.id = u.person_id"
        f"{clause} ORDER BY u.use_time DESC, u.id DESC LIMIT ?", params + [limit])
    return [dict(row) for row in rows]


def save_use(equipment_id, data, operator):
    """登记设备使用 / 检查记录。返回 (是否成功, 提示)。"""
    equipment = get_equipment(equipment_id)
    if equipment is None:
        return False, "设备不存在"
    use_time = (data.get("use_time") or "").strip() or personnel_service.now_text()
    if personnel_service.parse_datetime(use_time) is None:
        return False, "使用时间格式应为 2026-10-01 09:00"
    person_id = data.get("person_id")
    try:
        person_id = int(person_id) if person_id not in (None, "") else None
    except (TypeError, ValueError):
        person_id = None

    with database.get_connection() as conn:
        conn.execute(
            "INSERT INTO equipment_use(equipment_id, person_id, use_time, item, result,"
            " operator) VALUES(?,?,?,?,?,?)",
            (equipment_id, person_id, use_time, (data.get("item") or "").strip(),
             (data.get("result") or "").strip(), operator))

    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "登记设备使用", equipment["serial_no"],
                          f"{equipment['name']}｜{use_time}｜{data.get('item') or '—'}")
    return True, f"「{equipment['name']}」使用记录已登记"


def delete_use(use_id, operator):
    row = database.fetch_one(
        "SELECT u.*, e.name AS equipment_name, e.serial_no FROM equipment_use u"
        " JOIN equipment e ON e.id = u.equipment_id WHERE u.id = ?", (use_id,))
    if row is None:
        return False, "使用记录不存在"
    with database.get_connection() as conn:
        conn.execute("DELETE FROM equipment_use WHERE id = ?", (use_id,))
    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "删除设备使用记录", row["serial_no"],
                          f"{row['equipment_name']}｜{row['use_time']}")
    return True, "使用记录已删除"