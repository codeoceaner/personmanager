# -*- coding: utf-8 -*-
"""系统设置服务：参数配置、健康阈值、数据备份 / 恢复、操作与登录日志查询。

仅超级用户可达（界面按 user.manage / config.manage / backup.manage / log.view 控制），
所有写操作均写入 op_log 便于审计。
"""

import datetime
import json
import shutil

import config
from db import database
from services import health_service

_SQLITE_HEADER = b"SQLite format 3\x00"


def _operator_id(username):
    if not username:
        return None
    row = database.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    return row["id"] if row else None


# ---------------------------------------------------------------- 参数配置
def list_params():
    """运行参数：[(键, 中文名, 单位, 当前值, 下限, 上限)]，供设置页渲染表单。"""
    items = []
    for key, label, unit, low, high in config.SETTING_PARAMS:
        raw = database.get_config(key, "")
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = None
        items.append({"key": key, "label": label, "unit": unit, "value": value,
                      "min": low, "max": high})
    return items


def _check_ranges(values):
    """跨字段一致性：住井黄 ≤ 红 ≤ 上限，药品效期红 ≤ 黄。"""
    def _get(key, default):
        try:
            return int(str(values.get(key)).strip())
        except (TypeError, ValueError):
            return default

    yellow = _get("onboard_yellow_days", config.ONBOARD_YELLOW_DAYS)
    red = _get("onboard_red_days", config.ONBOARD_RED_DAYS)
    limit = _get("onboard_limit_days", config.ONBOARD_LIMIT_DAYS)
    if not yellow <= red <= limit:
        return False, "住井预警天数需满足：黄色预警 ≤ 红色报警 ≤ 天数上限"
    expire_red = _get("medicine_expire_red_days", config.MEDICINE_EXPIRE_RED_DAYS)
    expire_yellow = _get("medicine_expire_yellow_days", config.MEDICINE_EXPIRE_YELLOW_DAYS)
    if expire_red > expire_yellow:
        return False, "药品效期需满足：红色报警天数 ≤ 黄色预警天数"
    return True, ""


def save_params(values, operator="system"):
    """批量保存运行参数，逐项校验数值与范围。返回 (是否成功, 提示)。"""
    current = {item["key"]: item for item in list_params()}
    updates = []
    merged = {key: item["value"] for key, item in current.items()}
    for key, raw in values.items():
        item = current.get(key)
        if item is None:
            continue
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return False, f"{item['label']} 必须为整数"
        if not item["min"] <= value <= item["max"]:
            return False, f"{item['label']} 需在 {item['min']}–{item['max']} 之间"
        merged[key] = value
        if value != item["value"]:
            updates.append((key, value, item))

    ok, message = _check_ranges(merged)
    if not ok:
        return False, message
    if not updates:
        return True, "参数未发生变化"

    for key, value, item in updates:
        database.set_config(key, value)
    detail = "；".join(f"{item['label']} {item['value']}→{value}"
                      for _key, value, item in updates)
    operator_id = _operator_id(operator)
    database.write_op_log(operator_id, "系统设置", "修改参数", "运行参数", detail)
    return True, f"已保存 {len(updates)} 项参数"


# ---------------------------------------------------------------- 健康阈值
def health_thresholds():
    """当前生效的健康指标阈值（读取逻辑统一由 health_service 维护）。"""
    return health_service.thresholds()


def threshold_fields(item):
    """按方向返回可编辑的阈值字段名（供设置页渲染表单）。"""
    if item.get("direction") == "low_bad":
        return ("normal_min", "normal_max", "yellow_min", "red_max")
    return ("normal_min", "normal_max", "yellow_max", "red_min")


def save_health_thresholds(values, operator="system"):
    """保存健康指标阈值。values: {指标 key: {字段: 数值}}。"""
    thresholds = health_thresholds()
    changed = []
    for item in thresholds:
        fields = threshold_fields(item)
        incoming = values.get(item["key"], {})
        for field in fields:
            if field not in incoming:
                continue
            try:
                number = float(str(incoming[field]).strip())
            except (TypeError, ValueError):
                return False, f"{item['label']} 的阈值必须为数字"
            if number < 0:
                return False, f"{item['label']} 的阈值不能为负数"
            if item.get(field) != number:
                item[field] = number
                changed.append(item["label"])

        ok, message = _check_threshold_order(item)
        if not ok:
            return False, message

    if not changed:
        return True, "健康阈值未发生变化"
    database.set_config("health_thresholds", json.dumps(thresholds, ensure_ascii=False))
    detail = "；".join(sorted(set(changed)))
    database.write_op_log(_operator_id(operator), "系统设置", "修改健康阈值",
                          "健康指标阈值", detail)
    return True, f"已保存 {len(set(changed))} 项指标阈值"


def _check_threshold_order(item):
    """阈值必须保持 正常区间 ⊂ 黄警 ⊂ 红警 的递增关系。"""
    if item.get("direction") == "low_bad":
        values = [item.get("red_max"), item.get("yellow_min"),
                  item.get("normal_min"), item.get("normal_max")]
        if any(value is None for value in values):
            return True, ""
        if not values[0] <= values[1] <= values[2] <= values[3]:
            return False, f"{item['label']} 需满足：红警 ≤ 黄警 ≤ 正常下限 ≤ 正常上限"
        return True, ""

    values = [item.get("normal_min"), item.get("normal_max"),
              item.get("yellow_max"), item.get("red_min")]
    if any(value is None for value in values):
        return True, ""
    if not values[0] <= values[1] <= values[2] <= values[3]:
        return False, f"{item['label']} 需满足：正常下限 ≤ 正常上限 ≤ 黄警上限 ≤ 红警下限"
    return True, ""


# ---------------------------------------------------------------- 备份 / 恢复
def list_backups():
    """备份文件列表（新→旧）。"""
    files = sorted(config.BACKUP_DIR.glob("platform_*.db"),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    return [{
        "name": path.name,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "time": datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"),
        "path": str(path),
    } for path in files]


def create_backup(operator="system", tag=None):
    """手动备份。返回 (是否成功, 提示)。"""
    if not database.database_exists():
        return False, "数据库尚未创建，无需备份"
    stamp = tag or datetime.datetime.now().strftime(config.BACKUP_NAME_STAMP)
    path = database.backup_now(stamp)
    if path is None:
        return False, "备份失败"
    database.write_op_log(_operator_id(operator), "系统设置", "手动备份", path.name, None)
    return True, f"已生成备份：{path.name}"


def restore_backup(name, operator="system"):
    """从备份恢复：先自动留一份恢复前备份，再覆盖当前库并校验。"""
    source = config.BACKUP_DIR / name
    if not source.exists():
        return False, f"备份文件不存在：{name}"
    with open(source, "rb") as handle:
        if handle.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
            return False, "该文件不是有效的数据库备份，已终止恢复"

    safety = database.backup_now("before_restore")
    shutil.copy2(source, config.DB_PATH)
    database.clear_config_cache()
    try:
        row = database.fetch_one("SELECT COUNT(*) AS c FROM users")
    except Exception as exc:                            # noqa: BLE001 恢复后校验失败
        return False, f"恢复后的数据库校验失败：{exc}"

    detail = f"来自 {name}"
    if safety is not None:
        detail += f"；恢复前备份 {safety.name}"
    database.write_op_log(_operator_id(operator), "系统设置", "恢复数据", name, detail)
    return True, (f"已从 {name} 恢复（当前 {row['c']} 个账号）；"
                  f"恢复前数据已备份为 {safety.name if safety else '—'}")


# ---------------------------------------------------------------- 日志查询
def _paged(count_sql, rows_sql, params, page, page_size):
    total = database.fetch_one(count_sql, params)["c"]
    offset = max(page - 1, 0) * page_size
    rows = database.fetch_all(rows_sql + " LIMIT ? OFFSET ?",
                              tuple(params) + (page_size, offset))
    return rows, total


def list_op_logs(keyword=None, module=None, page=1, page_size=None):
    """操作日志（新→旧），可按关键字（操作人 / 对象 / 明细）与模块过滤。"""
    page_size = page_size or config.LOG_PAGE_SIZE
    where, params = [], []
    if module:
        where.append("l.module = ?")
        params.append(module)
    if keyword:
        where.append("(u.username LIKE ? OR l.target LIKE ? OR l.detail LIKE ?"
                     " OR l.action LIKE ?)")
        params.extend([f"%{keyword}%"] * 4)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = "FROM op_log l LEFT JOIN users u ON u.id = l.user_id" + clause
    result, total = _paged(
        f"SELECT COUNT(*) AS c {base}",
        f"SELECT l.*, u.username {base} ORDER BY l.id DESC",
        params, page, page_size)
    rows = [
        {"op_time": row["op_time"], "operator": row["username"] or "系统",
         "module": row["module"] or "—", "action": row["action"] or "—",
         "target": row["target"] or "—", "detail": row["detail"] or "—"}
        for row in result
    ]
    return rows, total


def op_log_modules():
    rows = database.fetch_all(
        "SELECT DISTINCT module FROM op_log WHERE module IS NOT NULL AND module <> ''")
    return sorted(row["module"] for row in rows)


def list_login_logs(keyword=None, result=None, page=1, page_size=None):
    """登录日志（新→旧），可按账号关键字与结果过滤。"""
    page_size = page_size or config.LOG_PAGE_SIZE
    where, params = [], []
    if result:
        where.append("result = ?")
        params.append(result)
    if keyword:
        where.append("(username LIKE ? OR detail LIKE ? OR ip LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    result, total = _paged(
        f"SELECT COUNT(*) AS c FROM login_log{clause}",
        f"SELECT * FROM login_log{clause} ORDER BY id DESC",
        params, page, page_size)
    rows = [
        {"login_time": row["login_time"], "username": row["username"] or "—",
         "ip": row["ip"] or "本机", "result": row["result"] or "—",
         "detail": row["detail"] or "—"}
        for row in result
    ]
    return rows, total