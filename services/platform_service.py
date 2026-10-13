# -*- coding: utf-8 -*-
"""平台服务：平台主数据、当前平台上下文与平台过滤条件构造。

二期引入「平台」维度后，业务数据按平台隔离：
    根表（personnel / room / lifeboat / medicine / equipment）持 platform_id 列，
    子表通过父表 JOIN 派生过滤（如 daily_check → personnel）。
当前平台存于 sys_config.current_platform_id：具体 id 表示单一平台，
"all" 表示「全部平台」（读取范围不限平台）。写入一律落到具体平台。
"""

import config
from db import database

CURRENT_KEY = "current_platform_id"
SCOPE_ALL = "all"

# 读取范围未显式指定时的占位，用于区分「未传参」与「显式传 None（全部平台）」
_UNSET = object()


# ---------------------------------------------------------------- 默认平台
def ensure_default():
    """保证存在默认平台，返回其 id。"""
    row = database.fetch_one("SELECT id FROM platform ORDER BY id LIMIT 1")
    if row:
        return row["id"]
    with database.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO platform(code, name, owner, location, status, remark, created_at)"
            " VALUES(?, ?, ?, ?, 1, ?, ?)",
            (config.DEFAULT_PLATFORM_CODE, config.DEFAULT_PLATFORM_NAME,
             config.COMPANY, "", "系统默认平台", database.now_str()))
        return cur.lastrowid


def default_id():
    """默认平台 id（库中最早的一条）。"""
    row = database.fetch_one("SELECT id FROM platform ORDER BY id LIMIT 1")
    return row["id"] if row else 1


# ---------------------------------------------------------------- 主数据
def list_platforms(only_active=True):
    where = " WHERE status = 1" if only_active else ""
    rows = database.fetch_all(f"SELECT * FROM platform{where} ORDER BY id")
    return [dict(row) for row in rows]


def get_platform(platform_id):
    row = database.fetch_one("SELECT * FROM platform WHERE id = ?", (platform_id,))
    return dict(row) if row else None


def save_platform(platform_id, data, operator=None):
    """新增或更新平台。返回 (是否成功, 提示, platform_id)。"""
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code:
        return False, "平台编码不能为空", None
    if not name:
        return False, "平台名称不能为空", None
    duplicate = database.fetch_one(
        "SELECT id FROM platform WHERE code = ? AND id <> ?", (code, platform_id or 0))
    if duplicate:
        return False, f"平台编码 {code} 已存在", None

    active = 0 if str(data.get("status", 1)) in ("0", "停用", "False") else 1
    fields = (code, name, (data.get("owner") or "").strip(),
              (data.get("location") or "").strip(), active,
              (data.get("remark") or "").strip())
    with database.get_connection() as conn:
        if platform_id:
            conn.execute(
                "UPDATE platform SET code = ?, name = ?, owner = ?, location = ?,"
                " status = ?, remark = ? WHERE id = ?", fields + (platform_id,))
            new_id = platform_id
        else:
            cur = conn.execute(
                "INSERT INTO platform(code, name, owner, location, status, remark,"
                " created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                fields + (database.now_str(),))
            new_id = cur.lastrowid
    return True, f"平台「{name}」已保存", new_id


# ---------------------------------------------------------------- 当前平台
def _raw():
    return (database.get_config(CURRENT_KEY) or "").strip()


def current_id():
    """写入与默认读取所用的具体平台 id；未设置或已失效时回退默认平台。"""
    raw = _raw()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = None
    if value and get_platform(value):
        return value
    return default_id()


def scope_id():
    """读取范围：具体平台 id，或 None 表示「全部平台」（不过滤）。"""
    if _raw().lower() == SCOPE_ALL:
        return None
    return current_id()


def set_current(platform_id):
    """设置当前平台；传 None 表示「全部平台」。"""
    database.set_config(CURRENT_KEY,
                        SCOPE_ALL if platform_id is None else str(int(platform_id)))


def resolve(platform_id=_UNSET):
    """把「未传参」解析为当前读取范围（None=全部平台），显式传参则原样返回。"""
    return scope_id() if platform_id is _UNSET else platform_id


def platform_clause(alias, platform_id=_UNSET):
    """生成平台过滤片段。返回 (sql, params)；「全部平台」时返回 ("", [])。

    alias 为查询中根表别名（如 personnel 的 "p"、medicine 的 "m"）。
    """
    value = resolve(platform_id)
    if value is None:
        return "", []
    return f"{alias}.platform_id = ?", [value]