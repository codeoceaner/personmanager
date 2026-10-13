# -*- coding: utf-8 -*-
"""药品服务：药品档案、入库 / 出库 / 盘点、库存与效期双维度预警、个人长期用药随访。

预警规则（产品设计 5.3.3）：
    效期：距有效期 ≤90 天 黄色预警，≤30 天 红色报警，已过期 红色报警并禁止出库
    库存：剩余量 ≤ 下限 黄色预警，≤ 下限 50% 红色报警，≥ 上限 提示积压
出入库 / 盘点均在事务内完成，失败自动回滚，保证库存台账与流水一致。
"""

import datetime

import config
from db import database
from services import personnel_service, platform_service


# ---------------------------------------------------------------- 小工具
def _to_int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _today():
    return datetime.date.today()


def days_to_expire(expire_date):
    """距有效期天数：负数表示已过期；无日期返回 None。"""
    date = personnel_service.parse_datetime(expire_date, with_time=False)
    if date is None:
        return None
    return (date.date() - _today()).days


def expire_thresholds():
    """效期预警天数 (黄色, 红色)，超级用户可在系统设置中调整。"""
    return (database.get_int("medicine_expire_yellow_days",
                             config.MEDICINE_EXPIRE_YELLOW_DAYS),
            database.get_int("medicine_expire_red_days",
                             config.MEDICINE_EXPIRE_RED_DAYS))


def expire_level(expire_date):
    """效期状态：正常 / 黄色预警 / 红色报警 / 已过期。"""
    days = days_to_expire(expire_date)
    if days is None:
        return "正常"
    if days < 0:
        return "已过期"
    yellow_days, red_days = expire_thresholds()
    if days <= red_days:
        return "红色报警"
    if days <= yellow_days:
        return "黄色预警"
    return "正常"


def stock_status_of(quantity, lower, upper):
    """库存状态：正常 / 库存偏低 / 库存紧急 / 库存积压。"""
    quantity = quantity or 0
    lower = lower or 0
    if lower > 0:
        if quantity <= lower * 0.5:
            return "库存紧急"
        if quantity <= lower:
            return "库存偏低"
    upper = upper or (lower * config.STOCK_UPPER_RATIO if lower > 0 else None)
    if upper and quantity >= upper:
        return "库存积压"
    return "正常"


def warning_level_of(expire_status, stock_status):
    """总体预警级别：红色报警 > 黄色预警 > 正常。"""
    if expire_status in ("已过期", "红色报警") or stock_status == "库存紧急":
        return "红色报警"
    if expire_status == "黄色预警" or stock_status == "库存偏低":
        return "黄色预警"
    return "正常"


# ---------------------------------------------------------------- 药品档案
def get_medicine(medicine_id):
    row = database.fetch_one("SELECT * FROM medicine WHERE id = ?", (medicine_id,))
    return dict(row) if row else None


def find_medicine_by_name(name, platform_id=platform_service._UNSET):
    if not name:
        return None
    scope_sql, scope_params = platform_service.platform_clause("medicine", platform_id)
    clause = f" AND {scope_sql}" if scope_sql else ""
    row = database.fetch_one(
        f"SELECT * FROM medicine WHERE name = ? AND status = 1{clause}"
        " ORDER BY id LIMIT 1", (name.strip(),) + tuple(scope_params))
    return dict(row) if row else None


def list_medicines(keyword=None, category=None, only_active=True, only_warning=False,
                   platform_id=platform_service._UNSET):
    """药品台账：合并各批次库存，附效期 / 库存状态与总体预警级别。"""
    where = []
    params = []
    scope_sql, scope_params = platform_service.platform_clause("m", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if only_active:
        where.append("m.status = 1")
    if category:
        where.append("m.category = ?")
        params.append(category)
    if keyword:
        where.append("(m.code LIKE ? OR m.name LIKE ? OR m.manufacturer LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    rows = database.fetch_all(
        "SELECT m.*, IFNULL(SUM(s.quantity), 0) AS total_quantity,"
        " COUNT(s.id) AS batch_count,"
        " MIN(CASE WHEN s.quantity > 0 AND s.expire_date IS NOT NULL"
        "     THEN s.expire_date END) AS nearest_expire"
        " FROM medicine m LEFT JOIN medicine_stock s ON s.medicine_id = m.id"
        f"{clause} GROUP BY m.id"
        " ORDER BY CASE m.category WHEN '急救' THEN 0 ELSE 1 END, m.code LIMIT 2000",
        params)

    records = []
    for row in rows:
        item = dict(row)
        item["is_prescription_text"] = "处方药" if item.get("is_prescription") else "非处方药"
        item["status_text"] = "启用" if item.get("status") else "停用"
        item["expire_status"] = expire_level(item.get("nearest_expire"))
        item["stock_status"] = stock_status_of(
            item["total_quantity"], item.get("stock_lower"), item.get("stock_upper"))
        item["warning_level"] = warning_level_of(item["expire_status"], item["stock_status"])
        if only_warning and item["warning_level"] == "正常":
            continue
        records.append(item)
    return records


def save_medicine(medicine_id, data, operator):
    """新增或更新药品档案。返回 (是否成功, 提示)。"""
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code:
        return False, "药品编码不能为空"
    if not name:
        return False, "通用名不能为空"
    category = (data.get("category") or "").strip()
    if category not in config.MEDICINE_CATEGORIES:
        return False, "类别只能为 " + " / ".join(config.MEDICINE_CATEGORIES)
    dosage_form = (data.get("dosage_form") or "").strip()
    if dosage_form and dosage_form not in config.DOSAGE_FORMS:
        return False, "剂型只能为 " + " / ".join(config.DOSAGE_FORMS)

    lower = _to_int(data.get("stock_lower"),
                    database.get_int("stock_lower_default", config.STOCK_LOWER_DEFAULT))
    upper = _to_int(data.get("stock_upper"), None)
    if lower is None or lower < 0:
        return False, "库存下限需为不小于 0 的整数"
    if upper is None or upper <= 0:
        upper = lower * config.STOCK_UPPER_RATIO if lower > 0 else config.STOCK_UPPER_RATIO
    if upper < lower:
        return False, "库存上限不能小于下限"

    duplicate = database.fetch_one(
        "SELECT id FROM medicine WHERE code = ? AND id <> ?", (code, medicine_id or 0))
    if duplicate:
        return False, f"药品编码 {code} 已存在"

    is_prescription = 1 if str(data.get("is_prescription")) in ("1", "是", "True") else 0
    fields = (code, name, (data.get("spec") or "").strip(), dosage_form,
              (data.get("unit") or "").strip(), (data.get("manufacturer") or "").strip(),
              category, is_prescription, lower, upper)

    with database.get_connection() as conn:
        if medicine_id:
            conn.execute(
                "UPDATE medicine SET code = ?, name = ?, spec = ?, dosage_form = ?,"
                " unit = ?, manufacturer = ?, category = ?, is_prescription = ?,"
                " stock_lower = ?, stock_upper = ? WHERE id = ?", fields + (medicine_id,))
        else:
            conn.execute(
                "INSERT INTO medicine(platform_id, code, name, spec, dosage_form, unit,"
                " manufacturer, category, is_prescription, stock_lower, stock_upper,"
                " status) VALUES(?,?,?,?,?,?,?,?,?,?,?, 1)",
                (platform_service.current_id(),) + fields)

    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "保存药品档案", code, f"{name}｜{category}")
    return True, f"药品「{name}」已保存"


def set_medicine_status(medicine_id, enabled, operator):
    medicine = get_medicine(medicine_id)
    if medicine is None:
        return False, "药品不存在"
    with database.get_connection() as conn:
        conn.execute("UPDATE medicine SET status = ? WHERE id = ?",
                     (1 if enabled else 0, medicine_id))
    action = "启用药品" if enabled else "停用药品"
    label = "启用" if enabled else "停用"
    database.write_op_log(personnel_service.operator_id(operator), "医疗物资", action,
                          medicine["code"], medicine["name"])
    return True, f"药品「{medicine['name']}」已{label}"


def delete_medicine(medicine_id, operator):
    """删除药品档案：存在出入库流水时不删除，改为提示停用。"""
    medicine = get_medicine(medicine_id)
    if medicine is None:
        return False, "药品不存在"
    used = database.fetch_one("SELECT COUNT(*) AS n FROM medicine_io WHERE medicine_id = ?",
                              (medicine_id,))["n"]
    if used:
        return False, "该药品已有出入库流水，不能删除，请改为停用"
    with database.get_connection() as conn:
        conn.execute("DELETE FROM medicine_stock WHERE medicine_id = ?", (medicine_id,))
        conn.execute("DELETE FROM medicine WHERE id = ?", (medicine_id,))
    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "删除药品档案", medicine["code"], medicine["name"])
    return True, f"药品「{medicine['name']}」已删除"


# ---------------------------------------------------------------- 批次库存
def list_batches(medicine_id):
    rows = database.fetch_all(
        "SELECT * FROM medicine_stock WHERE medicine_id = ?"
        " ORDER BY CASE WHEN expire_date IS NULL THEN 1 ELSE 0 END, expire_date, id",
        (medicine_id,))
    records = []
    for row in rows:
        item = dict(row)
        item["expire_status"] = expire_level(item.get("expire_date"))
        item["days_left"] = days_to_expire(item.get("expire_date"))
        records.append(item)
    return records


def stock_in(medicine_id, data, operator):
    """入库：同批号合并数量，事务内更新库存并写入流水。"""
    medicine = get_medicine(medicine_id)
    if medicine is None:
        return False, "药品不存在"
    batch_no = (data.get("batch_no") or "").strip()
    if not batch_no:
        return False, "批号不能为空"
    quantity = _to_int(data.get("quantity"))
    if quantity is None or quantity <= 0:
        return False, "入库数量需为正整数"
    expire_date = (data.get("expire_date") or "").strip()[:10]
    if not expire_date:
        return False, "有效期不能为空"
    if personnel_service.parse_datetime(expire_date, with_time=False) is None:
        return False, "有效期格式应为 2026-12-31"
    produce_date = (data.get("produce_date") or "").strip()[:10]
    if produce_date and personnel_service.parse_datetime(produce_date, with_time=False) is None:
        return False, "生产日期格式应为 2026-01-01"

    supplier = (data.get("supplier") or "").strip()
    location = (data.get("location") or "").strip()
    now = database.now_str()

    with database.get_connection() as conn:
        existing = conn.execute(
            "SELECT id, quantity FROM medicine_stock WHERE medicine_id = ? AND batch_no = ?",
            (medicine_id, batch_no)).fetchone()
        if existing:
            conn.execute("UPDATE medicine_stock SET quantity = quantity + ? WHERE id = ?",
                         (quantity, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO medicine_stock(medicine_id, batch_no, produce_date,"
                " expire_date, quantity, supplier, location) VALUES(?,?,?,?,?,?,?)",
                (medicine_id, batch_no, produce_date or None, expire_date, quantity,
                 supplier, location))
        conn.execute(
            "INSERT INTO medicine_io(medicine_id, batch_no, io_type, quantity, operator,"
            " io_time) VALUES(?,?,?,?,?,?)",
            (medicine_id, batch_no, "入库", quantity, operator, now))

    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "药品入库", medicine["code"],
                          f"{medicine['name']}｜批号 {batch_no}｜+{quantity}")
    return True, f"「{medicine['name']}」入库 {quantity}{medicine.get('unit') or ''} 成功"


def stock_out(medicine_id, data, operator):
    """出库：校验批次效期与库存，已过期批次禁止出库。"""
    medicine = get_medicine(medicine_id)
    if medicine is None:
        return False, "药品不存在"
    batch_no = (data.get("batch_no") or "").strip()
    if not batch_no:
        return False, "请选择出库批号"
    quantity = _to_int(data.get("quantity"))
    if quantity is None or quantity <= 0:
        return False, "出库数量需为正整数"

    person_id = _to_int(data.get("person_id"))
    purpose = (data.get("purpose") or "").strip()
    now = database.now_str()

    with database.get_connection() as conn:
        batch = conn.execute(
            "SELECT * FROM medicine_stock WHERE medicine_id = ? AND batch_no = ?",
            (medicine_id, batch_no)).fetchone()
        if batch is None:
            return False, "该批号不存在，请先入库"
        if expire_level(batch["expire_date"]) == "已过期":
            return False, "该批次已过期，禁止出库，请隔离销毁"
        if batch["quantity"] < quantity:
            return False, f"该批次库存不足（当前 {batch['quantity']}）"
        conn.execute("UPDATE medicine_stock SET quantity = quantity - ? WHERE id = ?",
                     (quantity, batch["id"]))
        conn.execute(
            "INSERT INTO medicine_io(medicine_id, batch_no, io_type, quantity, person_id,"
            " purpose, operator, io_time) VALUES(?,?,?,?,?,?,?,?)",
            (medicine_id, batch_no, "出库", quantity, person_id, purpose, operator, now))

    target = ""
    if person_id:
        person = personnel_service.get_person(person_id)
        if person:
            target = f"｜领用人 {person['name']}"
    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "药品出库", medicine["code"],
                          f"{medicine['name']}｜批号 {batch_no}｜-{quantity}{target}")
    return True, f"「{medicine['name']}」出库 {quantity}{medicine.get('unit') or ''} 成功"


def stock_check(medicine_id, data, operator):
    """盘点：录入实盘数量，生成盈亏流水并同步批次库存。"""
    medicine = get_medicine(medicine_id)
    if medicine is None:
        return False, "药品不存在"
    batch_no = (data.get("batch_no") or "").strip()
    if not batch_no:
        return False, "请选择盘点批号"
    actual = _to_int(data.get("actual_quantity"))
    if actual is None or actual < 0:
        return False, "实盘数量需为不小于 0 的整数"

    now = database.now_str()
    with database.get_connection() as conn:
        batch = conn.execute(
            "SELECT * FROM medicine_stock WHERE medicine_id = ? AND batch_no = ?",
            (medicine_id, batch_no)).fetchone()
        if batch is None:
            return False, "该批号不存在，请先入库"
        diff = actual - batch["quantity"]
        conn.execute("UPDATE medicine_stock SET quantity = ? WHERE id = ?",
                     (actual, batch["id"]))
        conn.execute(
            "INSERT INTO medicine_io(medicine_id, batch_no, io_type, quantity, operator,"
            " io_time) VALUES(?,?,?,?,?,?)",
            (medicine_id, batch_no, "盘点", diff, operator, now))

    if diff == 0:
        result = "账实一致"
    else:
        result = f"盘盈 {diff}" if diff > 0 else f"盘亏 {-diff}"
    database.write_op_log(personnel_service.operator_id(operator), "医疗物资",
                          "药品盘点", medicine["code"],
                          f"{medicine['name']}｜批号 {batch_no}｜{result}")
    return True, f"「{medicine['name']}」盘点完成：{result}"


def list_io_records(medicine_id=None, limit=100, platform_id=platform_service._UNSET):
    where = []
    params = []
    scope_sql, scope_params = platform_service.platform_clause("m", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if medicine_id:
        where.append("i.medicine_id = ?")
        params.append(medicine_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = database.fetch_all(
        "SELECT i.*, m.code, m.name, m.unit, p.name AS person_name FROM medicine_io i"
        " JOIN medicine m ON m.id = i.medicine_id"
        " LEFT JOIN personnel p ON p.id = i.person_id"
        f"{clause} ORDER BY i.io_time DESC, i.id DESC LIMIT ?", params + [limit])
    return [dict(row) for row in rows]


# ---------------------------------------------------------------- 预警聚合
def expired_batches(platform_id=platform_service._UNSET):
    """有库存且已过期的批次。"""
    scope_sql, scope_params = platform_service.platform_clause("m", platform_id)
    scope = f" AND {scope_sql}" if scope_sql else ""
    rows = database.fetch_all(
        "SELECT s.*, m.code, m.name, m.category, m.unit FROM medicine_stock s"
        " JOIN medicine m ON m.id = s.medicine_id"
        " WHERE s.quantity > 0 AND m.status = 1 AND s.expire_date IS NOT NULL"
        f" AND s.expire_date < ?{scope} ORDER BY m.code",
        (_today().isoformat(),) + tuple(scope_params))
    return [dict(row) for row in rows]


def medicine_warnings(source=None, level=None):
    """药品效期与库存预警统一列表；急救药品与红色报警置顶。"""
    warnings = []

    for record in list_medicines(only_active=True):
        # 效期预警：逐批次列出
        for batch in list_batches(record["id"]):
            status = batch["expire_status"]
            if batch["quantity"] <= 0 or status == "正常":
                continue
            days = batch["days_left"]
            if status == "已过期":
                detail = f"批号 {batch['batch_no']} 已过期 {-days} 天，请隔离销毁"
            else:
                detail = (f"批号 {batch['batch_no']} 有效期 {batch['expire_date']}，"
                          f"剩余 {days} 天")
            warnings.append({
                "source": "药品效期", "code": record["code"], "name": record["name"],
                "category": record["category"], "batch_no": batch["batch_no"],
                "detail": detail, "level": "红色报警" if status == "已过期" else status,
                "sort_urgency": days if days is not None else 9999,
            })
        # 库存预警：按药品
        if record["stock_status"] != "正常":
            level_value = "红色报警" if record["stock_status"] == "库存紧急" else "黄色预警"
            if record["stock_status"] == "库存积压":
                level_value = "提示"
            detail = (f"当前库存 {record['total_quantity']}{record.get('unit') or ''}，"
                      f"下限 {record.get('stock_lower')}、上限 {record.get('stock_upper')}")
            warnings.append({
                "source": "药品库存", "code": record["code"], "name": record["name"],
                "category": record["category"], "batch_no": "—",
                "detail": f"{record['stock_status']}：{detail}", "level": level_value,
                "sort_urgency": record["total_quantity"],
            })

    if source:
        warnings = [item for item in warnings if item["source"] == source]
    if level:
        warnings = [item for item in warnings if item["level"] == level]
    warnings.sort(key=lambda item: (
        0 if item["category"] == "急救" else 1,
        0 if item["level"] == "红色报警" else 1,
        item["sort_urgency"]))
    return warnings


def medicine_summary():
    """药品预警概览：红色报警、黄色预警、已过期批次数。"""
    warnings = medicine_warnings()
    return {
        "red": sum(1 for item in warnings if item["level"] == "红色报警"),
        "yellow": sum(1 for item in warnings if item["level"] == "黄色预警"),
        "expired": len([item for item in warnings if item["source"] == "药品效期"
                        and "已过期" in item["detail"]]),
    }


# ---------------------------------------------------------------- 长期用药随访
def list_plans(person_id=None, keyword=None, limit=500,
               platform_id=platform_service._UNSET):
    where = []
    params = []
    scope_sql, scope_params = platform_service.platform_clause("p", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if person_id:
        where.append("m.person_id = ?")
        params.append(person_id)
    if keyword:
        where.append("(p.emp_no LIKE ? OR p.name LIKE ? OR m.medicine_name LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = database.fetch_all(
        "SELECT m.*, p.emp_no, p.name, p.unit FROM medication_plan m"
        " JOIN personnel p ON p.id = m.person_id"
        f"{clause} ORDER BY m.start_date DESC, m.id DESC LIMIT ?", params + [limit])
    records = []
    for row in rows:
        item = dict(row)
        item["has_stock"] = find_medicine_by_name(item["medicine_name"]) is not None
        records.append(item)
    return records


def save_plan(plan_id, data, operator):
    """保存长期用药登记。返回 (是否成功, 提示)。"""
    person_id = _to_int(data.get("person_id"))
    if not person_id or personnel_service.get_person(person_id) is None:
        return False, "请选择用药人员"
    medicine_name = (data.get("medicine_name") or "").strip()
    if not medicine_name:
        return False, "药品名称不能为空"
    start_date = (data.get("start_date") or "").strip()[:10]
    if start_date and personnel_service.parse_datetime(start_date, with_time=False) is None:
        return False, "开始日期格式应为 2026-10-01"

    fields = (person_id, medicine_name, (data.get("dosage") or "").strip(),
              (data.get("frequency") or "").strip(), start_date or None,
              (data.get("follow_up") or "").strip(), (data.get("note") or "").strip())
    with database.get_connection() as conn:
        if plan_id:
            conn.execute(
                "UPDATE medication_plan SET person_id = ?, medicine_name = ?, dosage = ?,"
                " frequency = ?, start_date = ?, follow_up = ?, note = ? WHERE id = ?",
                fields + (plan_id,))
        else:
            conn.execute(
                "INSERT INTO medication_plan(person_id, medicine_name, dosage, frequency,"
                " start_date, follow_up, note) VALUES(?,?,?,?,?,?,?)", fields)

    person = personnel_service.get_person(person_id)
    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "保存用药登记", person["emp_no"],
                          f"{person['name']}｜{medicine_name}")
    return True, f"{person['name']} 的用药登记已保存"


def delete_plan(plan_id, operator):
    row = database.fetch_one(
        "SELECT m.*, p.emp_no, p.name FROM medication_plan m"
        " JOIN personnel p ON p.id = m.person_id WHERE m.id = ?", (plan_id,))
    if row is None:
        return False, "用药记录不存在"
    with database.get_connection() as conn:
        conn.execute("DELETE FROM medication_plan WHERE id = ?", (plan_id,))
    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "删除用药登记", row["emp_no"],
                          f"{row['name']}｜{row['medicine_name']}")
    return True, f"已删除 {row['name']} 的 {row['medicine_name']} 用药登记"