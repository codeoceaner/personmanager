# -*- coding: utf-8 -*-
"""人员服务：登记、离开、住井天数分级预警、分页查询。

住井天数含首日（上平台当天即第 1 天），由 onboard_days() 统一按上/下平台日期计算。
住井天数规则：含首日口径下 29 天黄色预警、30 天红色报警、≥31 天超期，
对应在平台满 28 / 29 / 30 个自然日，与产品设计 5.1.4 的触发点保持一致。
登记时若上平台时间已导致超期，直接拦截，避免把超期人员录入为在平台。
"""

import datetime
import re

import config
from db import database
from services import assign_service, platform_service

_ID_CARD_RE = re.compile(r"^\d{17}[\dXx]$")
_PHONE_RE = re.compile(r"^1\d{10}$")
_DATETIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
_AUTO_TEXT = "自动分配"

REQUIRED_FIELDS = (
    ("emp_no", "工号"), ("name", "姓名"), ("gender", "性别"), ("age", "年龄"),
    ("id_card", "身份证号"), ("phone", "联系电话"), ("unit", "所属单位"),
    ("person_type", "人员类型"), ("onboard_time", "上平台时间"),
    ("emergency_contact", "紧急联系人"), ("emergency_phone", "紧急联系电话"),
)


class _Abort(Exception):
    """业务校验失败，用于回滚登记事务。"""


# ---------------------------------------------------------------- 字段校验
def parse_datetime(text, with_time=True):
    text = (text or "").strip()
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if with_time and fmt == "%Y-%m-%d":
            dt = dt.replace(hour=8, minute=0)
        return dt
    return None


def now_text():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def validate_person(data):
    """返回 (是否通过, 提示语, 规范化后的数据)。"""
    cleaned = {}
    for key, label in REQUIRED_FIELDS:
        value = (data.get(key) or "")
        value = value.strip() if isinstance(value, str) else value
        if value in ("", None):
            return False, f"请填写{label}", None
        cleaned[key] = value

    if cleaned["gender"] not in config.GENDERS:
        return False, "性别只能为男或女", None
    if cleaned["person_type"] not in config.PERSON_TYPES:
        return False, f"人员类型只能为 {' / '.join(config.PERSON_TYPES)}", None

    try:
        age = int(cleaned["age"])
    except (TypeError, ValueError):
        return False, "年龄必须为整数", None
    if not 18 <= age <= 65:
        return False, "年龄需在 18–65 岁之间", None
    cleaned["age"] = age

    if not _ID_CARD_RE.match(str(cleaned["id_card"])):
        return False, "身份证号需为 18 位（末位可为 X）", None
    if not _PHONE_RE.match(str(cleaned["phone"])):
        return False, "联系电话需为 11 位手机号", None
    if not _PHONE_RE.match(str(cleaned["emergency_phone"])):
        return False, "紧急联系电话需为 11 位手机号", None

    onboard = parse_datetime(cleaned["onboard_time"])
    if onboard is None:
        return False, "上平台时间格式应为 2026-10-10 08:00", None
    if onboard > datetime.datetime.now():
        return False, "上平台时间不能晚于当前时间", None
    cleaned["onboard_time"] = onboard.strftime("%Y-%m-%d %H:%M")

    planned = (data.get("planned_off_time") or "").strip()
    if planned:
        planned_dt = parse_datetime(planned, with_time=False)
        if planned_dt is None:
            return False, "预计下平台时间格式应为 2026-10-20", None
        cleaned["planned_off_time"] = planned_dt.strftime("%Y-%m-%d")
    else:
        cleaned["planned_off_time"] = ""

    # 合同到期功能已下线：数据库列保留以兼容旧库，统一写入空值
    cleaned["contract_end_date"] = ""

    for key in ("post", "emergency_contact"):
        cleaned[key] = (data.get(key) or "").strip()
    return True, "", cleaned


def emp_no_exists(emp_no, exclude_id=None):
    if exclude_id:
        row = database.fetch_one(
            "SELECT id FROM personnel WHERE emp_no = ? AND id <> ? AND deleted = 0",
            (emp_no, exclude_id))
    else:
        row = database.fetch_one(
            "SELECT id FROM personnel WHERE emp_no = ? AND deleted = 0", (emp_no,))
    return row is not None


# ---------------------------------------------------------------- 住井天数
def onboard_days(onboard_time, end_time=None):
    """住井天数 = 下平台日期 − 上平台日期 + 1（含首日，当天上/下平台均计 1 天）。

    在平台人员以当前日期为终点，已离开人员以下平台时间为终点。
    例：10-01 上、10-06 下 → 6 天；同一天上、下平台 → 1 天。
    """
    start = parse_datetime(onboard_time) if isinstance(onboard_time, str) else onboard_time
    if start is None:
        return 0
    if end_time:
        end = parse_datetime(end_time) if isinstance(end_time, str) else end_time
    else:
        end = datetime.datetime.now()
    if end is None:
        end = datetime.datetime.now()
    return max((end.date() - start.date()).days + 1, 1)


def onboard_thresholds():
    """住井预警阈值 (黄色, 红色, 上限)，超级用户可在系统设置中调整。"""
    return (database.get_int("onboard_yellow_days", config.ONBOARD_YELLOW_DAYS),
            database.get_int("onboard_red_days", config.ONBOARD_RED_DAYS),
            database.get_int("onboard_limit_days", config.ONBOARD_LIMIT_DAYS))


def onboard_level(days):
    yellow, red, limit = onboard_thresholds()
    if days >= limit:
        return "超期"
    if days >= red:
        return "红色报警"
    if days >= yellow:
        return "黄色预警"
    return "正常"


# ---------------------------------------------------------------- 资源解析
def _resolve_room(conn, room_text, gender, unit, platform_id=None):
    """手动选择优先，否则自动匹配；资源须与人员同平台。"""
    room_text = assign_service.split_option(room_text)
    if room_text != _AUTO_TEXT:
        row = assign_service.find_room(conn, room_text)
        if row is None:
            raise _Abort(f"房间 {room_text} 不存在")
        if platform_id is not None and row["platform_id"] != platform_id:
            raise _Abort(f"房间 {room_text} 不属于当前平台")
        if row["gender_limit"] not in ("不限", gender):
            raise _Abort(f"房间 {room_text} 为{row['gender_limit']}房间，与所选性别不符")
        if assign_service.used_count(conn, assign_service.RESOURCE_ROOM,
                                      row["id"]) >= row["capacity"]:
            raise _Abort(f"房间 {room_text} 已满，请重新选择或释放床位")
        return row
    return assign_service.pick_room(conn, gender, unit, platform_id)


def _resolve_lifeboat(conn, boat_text, room_id, platform_id=None):
    boat_text = assign_service.split_option(boat_text)
    if boat_text != _AUTO_TEXT:
        row = assign_service.find_lifeboat(conn, boat_text)
        if row is None:
            raise _Abort(f"救生艇 {boat_text} 不存在")
        if platform_id is not None and row["platform_id"] != platform_id:
            raise _Abort(f"救生艇 {boat_text} 不属于当前平台")
        if assign_service.used_count(conn, assign_service.RESOURCE_LIFEBOAT,
                                      row["id"]) >= row["capacity"]:
            raise _Abort(f"救生艇 {boat_text} 定员已满，不得超员")
        return row
    return assign_service.pick_lifeboat(conn, room_id, platform_id)


# ---------------------------------------------------------------- 登记
def register_person(data, operator, room_text=None, boat_text=None):
    """登记即建档并自动分配房间与救生艇。返回 (是否成功, 提示, person_id)。"""
    ok, message, cleaned = validate_person(data)
    if not ok:
        return False, message, None
    if emp_no_exists(cleaned["emp_no"]):
        return False, f"工号 {cleaned['emp_no']} 已存在，请核对后台账", None

    days = onboard_days(cleaned["onboard_time"])
    limit_days = onboard_thresholds()[2]
    if days >= limit_days:
        return False, (f"该人员按上平台时间计算已住井 {days} 天，达到 "
                       f"{limit_days} 天上限，禁止登记，"
                       "请核实后安排下平台"), None

    platform_id = platform_service.current_id()
    try:
        with database.get_connection() as conn:
            room = _resolve_room(conn, room_text, cleaned["gender"], cleaned["unit"],
                                 platform_id)
            if room is None:
                raise _Abort(f"{cleaned['gender']}房间已满，请先释放床位")
            boat = _resolve_lifeboat(conn, boat_text, room["id"], platform_id)
            if boat is None:
                raise _Abort("救生艇定员已满，请先释放名额")

            cur = conn.execute(
                "INSERT INTO personnel(platform_id, emp_no, name, gender, age, id_card,"
                " phone, unit, person_type, post, emergency_contact, emergency_phone,"
                " onboard_time, planned_off_time, contract_end_date, status, created_at,"
                " deleted) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (platform_id, cleaned["emp_no"], cleaned["name"], cleaned["gender"],
                 cleaned["age"], cleaned["id_card"], cleaned["phone"], cleaned["unit"],
                 cleaned["person_type"], cleaned["post"], cleaned["emergency_contact"],
                 cleaned["emergency_phone"], cleaned["onboard_time"],
                 cleaned["planned_off_time"], cleaned["contract_end_date"],
                 config.PERSON_STATUS_ONBOARD, database.now_str()))
            person_id = cur.lastrowid

            conn.execute(
                "INSERT INTO checkin_record(person_id, checkin_time, operator, note)"
                " VALUES(?, ?, ?, ?)",
                (person_id, cleaned["onboard_time"], operator, "人员登记"))

            assign_service.allocate(conn, person_id, assign_service.RESOURCE_ROOM,
                                    room["id"], operator)
            assign_service.allocate(conn, person_id, assign_service.RESOURCE_LIFEBOAT,
                                    boat["id"], operator)
    except _Abort as exc:
        return False, str(exc), None

    database.write_op_log(
        operator_id(operator), "人员登离管理", "人员登记", cleaned["emp_no"],
        f"{cleaned['name']}｜房间 {room['room_no']}｜救生艇 {boat['boat_no']}")
    message = (f"{cleaned['name']} 登记成功，已分配房间 {room['room_no']}、"
               f"救生艇 {boat['boat_no']}")
    return True, message, person_id


def operator_id(username):
    """把操作人姓名映射为 users.id，便于日志关联。"""
    if not username:
        return None
    row = database.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    return row["id"] if row else None


# ---------------------------------------------------------------- 离开
def leave_person(person_id, leave_time, destination, reason, operator, note=""):
    """离开登记：写入离开记录、释放房间床位与救生艇名额。"""
    person = database.fetch_one("SELECT * FROM personnel WHERE id = ?", (person_id,))
    if person is None:
        return False, "人员不存在"
    if person["status"] != config.PERSON_STATUS_ONBOARD:
        return False, f"{person['name']} 当前不在平台，无需办理离开"

    leave_dt = parse_datetime(leave_time)
    if leave_dt is None:
        return False, "离开时间格式应为 2026-10-10 08:00"
    if leave_dt < parse_datetime(person["onboard_time"]):
        return False, "离开时间不能早于上平台时间"
    leave_text = leave_dt.strftime("%Y-%m-%d %H:%M")

    if not (destination or "").strip():
        return False, "请填写离开去向"
    if reason not in config.LEAVE_REASONS:
        return False, f"离开原因只能为 {' / '.join(config.LEAVE_REASONS)}"

    with database.get_connection() as conn:
        conn.execute(
            "UPDATE personnel SET status = ?, actual_off_time = ?, updated_at = ?"
            " WHERE id = ?",
            (config.PERSON_STATUS_LEFT, leave_text, database.now_str(), person_id))
        conn.execute(
            "INSERT INTO leave_record(person_id, leave_time, destination, reason,"
            " operator, note) VALUES(?, ?, ?, ?, ?, ?)",
            (person_id, leave_text, destination.strip(), reason, operator, note))
        assign_service.release_all(conn, person_id, operator)

    days = onboard_days(person["onboard_time"], leave_text)
    database.write_op_log(operator_id(operator), "人员登离管理", "人员离开",
                          person["emp_no"],
                          f"{person['name']}｜住井 {days} 天｜{reason}｜{destination.strip()}")
    return True, f"{person['name']} 已办理离开，住井 {days} 天，房间与救生艇已释放"


# ---------------------------------------------------------------- 查询
def _build_filters(person_type=None, keyword=None, only_onboard=False, unit=None,
                   name=None, room_no=None, boat_no=None, status=None,
                   platform_id=platform_service._UNSET):
    where = ["p.deleted = 0"]
    params = []
    scope_sql, scope_params = platform_service.platform_clause("p", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if only_onboard:
        where.append("p.status = ?")
        params.append(config.PERSON_STATUS_ONBOARD)
    if status:
        where.append("p.status = ?")
        params.append(status)
    if person_type:
        where.append("p.person_type = ?")
        params.append(person_type)
    if name:
        where.append("p.name LIKE ?")
        params.append(f"%{name}%")
    if unit:
        where.append("p.unit LIKE ?")
        params.append(f"%{unit}%")
    if keyword:
        where.append("(p.emp_no LIKE ? OR p.name LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    # 房间号 / 救生艇取在用的分配记录，SELECT 别名不可用于 WHERE，故用 EXISTS 过滤
    if room_no:
        where.append(
            "EXISTS (SELECT 1 FROM assignment a JOIN room r ON r.id = a.resource_id"
            " WHERE a.person_id = p.id AND a.resource_type = ? AND a.status = ?"
            " AND r.room_no LIKE ?)")
        params.extend([assign_service.RESOURCE_ROOM, assign_service.STATUS_USED,
                       f"%{room_no}%"])
    if boat_no:
        where.append(
            "EXISTS (SELECT 1 FROM assignment a JOIN lifeboat l ON l.id = a.resource_id"
            " WHERE a.person_id = p.id AND a.resource_type = ? AND a.status = ?"
            " AND l.boat_no LIKE ?)")
        params.extend([assign_service.RESOURCE_LIFEBOAT, assign_service.STATUS_USED,
                       f"%{boat_no}%"])
    return " WHERE " + " AND ".join(where), params


def list_personnel(page=1, page_size=None, person_type=None, keyword=None,
                   only_onboard=False, unit=None, name=None, room_no=None,
                   boat_no=None, status=None, platform_id=platform_service._UNSET):
    """分页查询人员，附带房间 / 救生艇 / 住井天数与预警级别。

    过滤条件均为可选：name / unit / room_no / boat_no 为模糊匹配，
    status 取「在平台 / 已离开」精确匹配，keyword 同时匹配工号与姓名。
    """
    page_size = page_size or config.PAGE_SIZE
    clause, params = _build_filters(person_type, keyword, only_onboard, unit,
                                    name, room_no, boat_no, status, platform_id)

    total = database.fetch_one(
        f"SELECT COUNT(*) AS c FROM personnel p{clause}", params)["c"]
    offset = max(page - 1, 0) * page_size

    rows = database.fetch_all(
        f"SELECT p.*,"
        f" (SELECT r.room_no FROM assignment a JOIN room r ON r.id = a.resource_id"
        f"   WHERE a.person_id = p.id AND a.resource_type = ? AND a.status = ?) AS room_no,"
        f" (SELECT l.boat_no FROM assignment a JOIN lifeboat l ON l.id = a.resource_id"
        f"   WHERE a.person_id = p.id AND a.resource_type = ? AND a.status = ?) AS boat_no"
        f" FROM personnel p{clause} ORDER BY p.onboard_time DESC, p.id DESC"
        f" LIMIT ? OFFSET ?",
        [assign_service.RESOURCE_ROOM, assign_service.STATUS_USED,
         assign_service.RESOURCE_LIFEBOAT, assign_service.STATUS_USED]
        + params + [page_size, offset])

    records = []
    for row in rows:
        item = dict(row)
        end_time = item.get("actual_off_time") if item["status"] != config.PERSON_STATUS_ONBOARD else None
        days = onboard_days(item["onboard_time"], end_time)
        item["onboard_days"] = days
        item["onboard_level"] = (onboard_level(days) if item["status"]
                                 == config.PERSON_STATUS_ONBOARD else "已下平台")
        item["room_no"] = item.get("room_no") or ""
        item["boat_no"] = item.get("boat_no") or ""
        # 下平台时间：无值统一为空白，避免表格出现 "None"
        item["actual_off_time"] = item.get("actual_off_time") or ""
        records.append(item)
    return records, total


# ---------------------------------------------------------------- 编辑
def person_form_data(person_id):
    """编辑对话框回填数据（含当前房间与救生艇）。"""
    person = database.fetch_one("SELECT * FROM personnel WHERE id = ?", (person_id,))
    if person is None:
        return None
    data = dict(person)
    with database.get_connection() as conn:
        current = assign_service.current_assignment(conn, person_id)
    data["room_no"] = current["room_no"] or _AUTO_TEXT
    data["boat_no"] = current["boat_no"] or _AUTO_TEXT
    return data


def update_person(person_id, data, operator, room_text=None, boat_text=None):
    """修改人员信息；在平台人员可同时调整房间与救生艇。"""
    person = database.fetch_one("SELECT * FROM personnel WHERE id = ?", (person_id,))
    if person is None:
        return False, "人员不存在"

    ok, message, cleaned = validate_person(data)
    if not ok:
        return False, message
    if emp_no_exists(cleaned["emp_no"], exclude_id=person_id):
        return False, f"工号 {cleaned['emp_no']} 已被其他人员占用"

    onboard_ing = person["status"] == config.PERSON_STATUS_ONBOARD
    if onboard_ing:
        days = onboard_days(cleaned["onboard_time"])
        limit_days = onboard_thresholds()[2]
        if days >= limit_days:
            return False, (f"该人员按上平台时间计算已住井 {days} 天，达到 "
                           f"{limit_days} 天上限，请先安排下平台")

    try:
        with database.get_connection() as conn:
            if onboard_ing and room_text is not None:
                current = assign_service.current_assignment(conn, person_id)
                room = _resolve_room(conn, room_text, cleaned["gender"], cleaned["unit"])
                if room is not None and room["id"] != current["room_id"]:
                    assign_service.allocate(conn, person_id, assign_service.RESOURCE_ROOM,
                                            room["id"], operator)
                    boat_text = (assign_service.split_option(boat_text)
                                 if boat_text else _AUTO_TEXT)
            if onboard_ing and boat_text is not None:
                current = assign_service.current_assignment(conn, person_id)
                boat = _resolve_lifeboat(conn, boat_text, assign_service.current_assignment(
                    conn, person_id)["room_id"])
                if boat is not None and boat["id"] != current["lifeboat_id"]:
                    assign_service.allocate(conn, person_id,
                                            assign_service.RESOURCE_LIFEBOAT,
                                            boat["id"], operator)

            conn.execute(
                "UPDATE personnel SET emp_no = ?, name = ?, gender = ?, age = ?,"
                " id_card = ?, phone = ?, unit = ?, person_type = ?, post = ?,"
                " onboard_time = ?, planned_off_time = ?, contract_end_date = ?,"
                " emergency_contact = ?, emergency_phone = ?, updated_at = ? WHERE id = ?",
                (cleaned["emp_no"], cleaned["name"], cleaned["gender"], cleaned["age"],
                 cleaned["id_card"], cleaned["phone"], cleaned["unit"],
                 cleaned["person_type"], cleaned["post"], cleaned["onboard_time"],
                 cleaned["planned_off_time"], cleaned["contract_end_date"],
                 cleaned["emergency_contact"], cleaned["emergency_phone"],
                 database.now_str(), person_id))
    except _Abort as exc:
        return False, str(exc)

    database.write_op_log(operator_id(operator), "人员登离管理", "修改人员",
                          cleaned["emp_no"],
                          f"{cleaned['name']}｜{person['person_type']}→{cleaned['person_type']}")
    return True, f"{cleaned['name']} 的信息已更新"


# ---------------------------------------------------------------- 删除
def soft_delete(person_id, operator, reason=""):
    """软删除：在平台人员须先办理离开，删除仅做标记保留审计痕迹。"""
    person = database.fetch_one("SELECT * FROM personnel WHERE id = ?", (person_id,))
    if person is None or person["deleted"]:
        return False, "人员不存在或已删除"
    if person["status"] == config.PERSON_STATUS_ONBOARD:
        return False, f"{person['name']} 仍在平台，请先办理离开再删除"

    with database.get_connection() as conn:
        conn.execute("UPDATE personnel SET deleted = 1, updated_at = ? WHERE id = ?",
                     (database.now_str(), person_id))
    database.write_op_log(operator_id(operator), "人员登离管理", "删除人员",
                          person["emp_no"], f"{person['name']}｜{reason or '未填写原因'}")
    return True, f"{person['name']} 已从台账中删除（可在日志中追溯）"


# ---------------------------------------------------------------- 分类统计
def category_stats(person_type):
    """三类人员视图的统计口径：单位分布、岗位分布、住井排行、进出场频次等。"""
    params = (person_type,)
    base_where = "deleted = 0 AND person_type = ?"
    onboard_where = base_where + " AND status = ?"

    counts = database.fetch_one(
        f"SELECT COUNT(*) AS total,"
        f" SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS onboard"
        f" FROM personnel WHERE {base_where}",
        (config.PERSON_STATUS_ONBOARD, person_type))
    total = counts["total"] or 0
    onboard = counts["onboard"] or 0

    by_unit = [dict(row) for row in database.fetch_all(
        f"SELECT unit, COUNT(*) AS total,"
        f" SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS onboard"
        f" FROM personnel WHERE {base_where}"
        f" GROUP BY unit ORDER BY total DESC",
        (config.PERSON_STATUS_ONBOARD, person_type))]

    by_post = [dict(row) for row in database.fetch_all(
        f"SELECT CASE WHEN post = '' THEN '未填写' ELSE post END AS post,"
        f" COUNT(*) AS onboard FROM personnel WHERE {onboard_where}"
        f" GROUP BY post ORDER BY onboard DESC LIMIT 8",
        (person_type, config.PERSON_STATUS_ONBOARD))]

    rank = []
    for row in database.fetch_all(
            f"SELECT emp_no, name, unit, onboard_time FROM personnel"
            f" WHERE {onboard_where} ORDER BY onboard_time ASC LIMIT 5",
            (person_type, config.PERSON_STATUS_ONBOARD)):
        days = onboard_days(row["onboard_time"])
        rank.append({"emp_no": row["emp_no"], "name": row["name"], "unit": row["unit"],
                     "days": days, "level": onboard_level(days)})

    flow = [dict(row) for row in database.fetch_all(
        f"SELECT p.emp_no, p.name,"
        f" (SELECT COUNT(*) FROM checkin_record c WHERE c.person_id = p.id) AS in_cnt,"
        f" (SELECT COUNT(*) FROM leave_record l WHERE l.person_id = p.id) AS out_cnt"
        f" FROM personnel p WHERE p.deleted = 0 AND p.person_type = ?"
        f" ORDER BY in_cnt DESC, p.id LIMIT 8", params)]

    batches = [dict(row) for row in database.fetch_all(
        f"SELECT substr(onboard_time, 1, 7) AS month, COUNT(*) AS cnt"
        f" FROM personnel WHERE {base_where} GROUP BY month ORDER BY month DESC LIMIT 6",
        params)]

    rooms = [dict(row) for row in database.fetch_all(
        f"SELECT r.room_no, COUNT(*) AS cnt FROM assignment a"
        f" JOIN personnel p ON p.id = a.person_id"
        f" JOIN room r ON r.id = a.resource_id"
        f" WHERE p.deleted = 0 AND p.person_type = ? AND a.resource_type = ?"
        f" AND a.status = ? GROUP BY r.room_no ORDER BY cnt DESC LIMIT 8",
        (person_type, assign_service.RESOURCE_ROOM, assign_service.STATUS_USED))]

    return {"person_type": person_type, "total": total, "onboard": onboard,
            "left": total - onboard, "by_unit": by_unit, "by_post": by_post,
            "rank": rank, "flow": flow, "batches": batches, "rooms": rooms}


def get_person(person_id):
    row = database.fetch_one("SELECT * FROM personnel WHERE id = ?", (person_id,))
    return dict(row) if row else None


def distinct_units(platform_id=platform_service._UNSET):
    clause, params = platform_service.platform_clause("personnel", platform_id)
    where = " WHERE deleted = 0 AND unit <> ''"
    if clause:
        where += " AND " + clause
    rows = database.fetch_all(
        f"SELECT DISTINCT unit FROM personnel{where} ORDER BY unit", params)
    return [row["unit"] for row in rows]


def summary_counts(platform_id=platform_service._UNSET):
    """在平台人数与三类人员分布，供状态栏与看板使用。"""
    clause, params = platform_service.platform_clause("personnel", platform_id)
    scope = f" AND {clause}" if clause else ""
    onboard = database.fetch_one(
        f"SELECT COUNT(*) AS c FROM personnel WHERE status = ? AND deleted = 0{scope}",
        (config.PERSON_STATUS_ONBOARD,) + tuple(params))["c"]
    by_type = {}
    for row in database.fetch_all(
            f"SELECT person_type, COUNT(*) AS c FROM personnel"
            f" WHERE status = ? AND deleted = 0{scope} GROUP BY person_type",
            (config.PERSON_STATUS_ONBOARD,) + tuple(params)):
        by_type[row["person_type"]] = row["c"]
    return {"onboard": onboard, "by_type": by_type}