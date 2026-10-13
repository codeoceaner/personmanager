# -*- coding: utf-8 -*-
"""资源分配服务：房间与救生艇的初始化、自动匹配、分配与释放。

分配规则（产品设计 5.1.1）：
    房间：性别一致 → 同单位优先 → 剩余床位最多
    救生艇：剩余定员 > 0，编号最小者优先；同房间人员尽量编入同一艇
"""

import config
from db import database
from services import platform_service

RESOURCE_ROOM = "room"
RESOURCE_LIFEBOAT = "lifeboat"
STATUS_USED = "使用中"
STATUS_RELEASED = "已释放"

_AUTO_TEXT = "自动分配"


# ---------------------------------------------------------------- 默认资源
def seed_default_resources():
    """首次运行生成默认房间 / 救生艇资源（归属默认平台），保证登记即可自动分配。"""
    room_count = database.fetch_one("SELECT COUNT(*) AS c FROM room")["c"]
    boat_count = database.fetch_one("SELECT COUNT(*) AS c FROM lifeboat")["c"]
    if room_count and boat_count:
        return False

    platform_id = platform_service.ensure_default()
    with database.get_connection() as conn:
        if not room_count:
            rooms = []
            for floor in range(1, config.MALE_FLOORS + 1):
                for idx in range(1, config.MALE_ROOMS_PER_FLOOR + 1):
                    rooms.append((platform_id, f"A{floor}{idx:02d}", "男",
                                  config.ROOM_BEDS, "", "可用"))
            for idx in range(1, config.FEMALE_ROOM_COUNT + 1):
                rooms.append((platform_id, f"B{idx:03d}", "女", config.ROOM_BEDS,
                              "", "可用"))
            conn.executemany(
                "INSERT INTO room(platform_id, room_no, gender_limit, capacity,"
                " unit_priority, status) VALUES(?, ?, ?, ?, ?, ?)", rooms)

        if not boat_count:
            boats = [(platform_id, boat_no, config.LIFEBOAT_CAPACITY, location, "可用")
                     for boat_no, location in config.LIFEBOATS]
            conn.executemany(
                "INSERT INTO lifeboat(platform_id, boat_no, capacity, location, status)"
                " VALUES(?, ?, ?, ?, ?)", boats)
    return True


# ---------------------------------------------------------------- 占用统计
def used_count(conn, resource_type, resource_id):
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM assignment WHERE resource_type = ? AND resource_id = ?"
        " AND status = ?", (resource_type, resource_id, STATUS_USED)).fetchone()
    return row["c"]


def _occupants_unit(conn, room_id):
    rows = conn.execute(
        "SELECT p.unit FROM assignment a JOIN personnel p ON p.id = a.person_id"
        " WHERE a.resource_type = ? AND a.resource_id = ? AND a.status = ?",
        (RESOURCE_ROOM, room_id, STATUS_USED)).fetchall()
    return {row["unit"] for row in rows}


# ---------------------------------------------------------------- 自动匹配
def pick_room(conn, gender, unit=None, platform_id=None):
    """按「性别一致 → 同单位优先 → 剩余床位最多」返回房间行，无可用返回 None。"""
    sql = "SELECT * FROM room WHERE status = '可用'"
    params = []
    if platform_id is not None:
        sql += " AND platform_id = ?"
        params.append(platform_id)
    candidates = []
    for row in conn.execute(sql, params).fetchall():
        if row["gender_limit"] not in ("不限", gender):
            continue
        free = row["capacity"] - used_count(conn, RESOURCE_ROOM, row["id"])
        if free <= 0:
            continue
        same_unit = unit and unit in _occupants_unit(conn, row["id"])
        candidates.append((0 if same_unit else 1, -free, row["room_no"], row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3]


def pick_lifeboat(conn, room_id=None, platform_id=None):
    """优先编入同房间人员所在艇，否则取剩余定员 > 0 且编号最小者。"""
    mates_boat_ids = set()
    if room_id:
        rows = conn.execute(
            "SELECT DISTINCT a.resource_id FROM assignment a"
            " WHERE a.resource_type = ? AND a.status = ? AND a.person_id IN ("
            "   SELECT person_id FROM assignment WHERE resource_type = ? AND resource_id = ?"
            "   AND status = ?)",
            (RESOURCE_LIFEBOAT, STATUS_USED,
             RESOURCE_ROOM, room_id, STATUS_USED)).fetchall()
        mates_boat_ids = {row["resource_id"] for row in rows}

    sql = "SELECT * FROM lifeboat WHERE status = '可用'"
    params = []
    if platform_id is not None:
        sql += " AND platform_id = ?"
        params.append(platform_id)
    candidates = []
    for row in conn.execute(sql + " ORDER BY boat_no", params).fetchall():
        free = row["capacity"] - used_count(conn, RESOURCE_LIFEBOAT, row["id"])
        if free <= 0:
            continue
        candidates.append((0 if row["id"] in mates_boat_ids else 1, row["boat_no"], row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:2])
    return candidates[0][2]


def find_room(conn, room_no):
    return conn.execute("SELECT * FROM room WHERE room_no = ?", (room_no,)).fetchone()


def find_lifeboat(conn, boat_no):
    return conn.execute("SELECT * FROM lifeboat WHERE boat_no = ?", (boat_no,)).fetchone()


# ---------------------------------------------------------------- 分配与释放
def allocate(conn, person_id, resource_type, resource_id, operator=None):
    """写入一条新的分配履历，并先释放该人员同类在用记录。"""
    conn.execute(
        "UPDATE assignment SET status = ?, end_time = ? WHERE person_id = ?"
        " AND resource_type = ? AND status = ?",
        (STATUS_RELEASED, database.now_str(), person_id, resource_type, STATUS_USED))
    conn.execute(
        "INSERT INTO assignment(person_id, resource_type, resource_id, start_time,"
        " status, operator) VALUES(?, ?, ?, ?, ?, ?)",
        (person_id, resource_type, resource_id, database.now_str(), STATUS_USED, operator))


def release_all(conn, person_id, operator=None):
    """人员离开时释放其全部在用资源（房间床位 + 救生艇名额）。"""
    conn.execute(
        "UPDATE assignment SET status = ?, end_time = ? WHERE person_id = ? AND status = ?",
        (STATUS_RELEASED, database.now_str(), person_id, STATUS_USED))


def current_assignment(conn, person_id):
    """返回人员当前占用的房间与救生艇信息。"""
    result = {"room_no": "", "boat_no": "", "room_id": None, "lifeboat_id": None}
    rows = conn.execute(
        "SELECT a.resource_type, a.resource_id, r.room_no, l.boat_no"
        " FROM assignment a"
        " LEFT JOIN room r ON r.id = a.resource_id AND a.resource_type = ?"
        " LEFT JOIN lifeboat l ON l.id = a.resource_id AND a.resource_type = ?"
        " WHERE a.person_id = ? AND a.status = ?",
        (RESOURCE_ROOM, RESOURCE_LIFEBOAT, person_id, STATUS_USED)).fetchall()
    for row in rows:
        if row["resource_type"] == RESOURCE_ROOM:
            result["room_no"] = row["room_no"] or ""
            result["room_id"] = row["resource_id"]
        elif row["resource_type"] == RESOURCE_LIFEBOAT:
            result["boat_no"] = row["boat_no"] or ""
            result["lifeboat_id"] = row["resource_id"]
    return result


# ---------------------------------------------------------------- 界面下拉选项
def room_options(gender=None, platform_id=platform_service._UNSET):
    """可用房间号列表（含"自动分配"）。"""
    scope = platform_service.resolve(platform_id)
    with database.get_connection() as conn:
        options = [_AUTO_TEXT]
        sql = "SELECT * FROM room WHERE status = '可用'"
        params = []
        if scope is not None:
            sql += " AND platform_id = ?"
            params.append(scope)
        for row in conn.execute(sql + " ORDER BY room_no", params).fetchall():
            if gender and row["gender_limit"] not in ("不限", gender):
                continue
            free = row["capacity"] - used_count(conn, RESOURCE_ROOM, row["id"])
            if free > 0:
                options.append(f"{row['room_no']}（余 {free} 床）")
    return options


def lifeboat_options(platform_id=platform_service._UNSET):
    scope = platform_service.resolve(platform_id)
    with database.get_connection() as conn:
        options = [_AUTO_TEXT]
        sql = "SELECT * FROM lifeboat WHERE status = '可用'"
        params = []
        if scope is not None:
            sql += " AND platform_id = ?"
            params.append(scope)
        for row in conn.execute(sql + " ORDER BY boat_no", params).fetchall():
            free = row["capacity"] - used_count(conn, RESOURCE_LIFEBOAT, row["id"])
            if free > 0:
                options.append(f"{row['boat_no']}（余 {free} 人）")
    return options


def auto_assign_preview(gender, unit=None):
    """登记页预览用：返回自动分配到的房间号与救生艇编号（限当前平台）。"""
    platform_id = platform_service.current_id()
    with database.get_connection() as conn:
        room = pick_room(conn, gender, unit, platform_id)
        if room is None:
            return None, None, f"{gender}房间已满，请先释放床位"
        boat = pick_lifeboat(conn, room["id"], platform_id)
        if boat is None:
            return room["room_no"], None, "救生艇定员已满，请先释放名额"
    return room["room_no"], boat["boat_no"], ""


def split_option(text):
    """把下拉选项文本还原为编号，例如 "A101（余 3 床）" → "A101"。"""
    if not text or text == _AUTO_TEXT:
        return _AUTO_TEXT
    return text.split("（")[0].strip()


def resource_usage(platform_id=platform_service._UNSET):
    """房间与救生艇占用概览，用于状态栏与看板（按平台范围统计）。"""
    scope = platform_service.resolve(platform_id)
    room_sql = "SELECT COUNT(*) AS c, SUM(capacity) AS s FROM room"
    boat_sql = "SELECT COUNT(*) AS c, SUM(capacity) AS s FROM lifeboat"
    used_sql = ("SELECT COUNT(*) AS c FROM assignment a JOIN personnel p"
                " ON p.id = a.person_id WHERE a.resource_type = ? AND a.status = ?")
    params = []
    if scope is not None:
        room_sql += " WHERE platform_id = ?"
        boat_sql += " WHERE platform_id = ?"
        used_sql += " AND p.platform_id = ?"
        params.append(scope)
    with database.get_connection() as conn:
        rooms = conn.execute(room_sql, params).fetchone()
        boats = conn.execute(boat_sql, params).fetchone()
        used_beds = conn.execute(used_sql, (RESOURCE_ROOM, STATUS_USED, *params)).fetchone()["c"]
        used_seats = conn.execute(used_sql,
                                  (RESOURCE_LIFEBOAT, STATUS_USED, *params)).fetchone()["c"]
    total_beds = rooms["s"] or 0
    return {
        "room_count": rooms["c"] or 0,
        "bed_total": total_beds,
        "bed_used": used_beds,
        "bed_rate": round(used_beds / total_beds * 100, 1) if total_beds else 0.0,
        "boat_count": boats["c"] or 0,
        "seat_total": boats["s"] or 0,
        "seat_used": used_seats,
    }