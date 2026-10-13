# -*- coding: utf-8 -*-
"""SQLite 数据访问层：连接管理、建库初始化、日志写入、自动备份。"""

import datetime
import json
import shutil
import sqlite3
from contextlib import contextmanager

import config

SCHEMA_FILE = config.BASE_DIR / "db" / "schema.sql"


# ---------------------------------------------------------------- 通用工具
def now_str(dt=None, fmt="%Y-%m-%d %H:%M:%S"):
    """统一的时间字符串，避免各处格式不一致。"""
    return (dt or datetime.datetime.now()).strftime(fmt)


@contextmanager
def get_connection():
    """获取数据库连接（自动提交 / 回滚 / 关闭）。"""
    conn = sqlite3.connect(config.DB_PATH, timeout=config.DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql, params=()):
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql, params=()):
    with get_connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql, params=()):
    """执行写操作，返回最后插入行 id。"""
    with get_connection() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


# ---------------------------------------------------------------- 建库与初始化
def database_exists():
    return config.DB_PATH.exists()


def init_database():
    """首次运行创建全部表与索引，并初始化系统参数默认值。"""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.executescript(sql)
        apply_migrations(conn)
        # 必须在写入默认值之前执行：新库此时 sys_config 为空，不会被误加 1
        migrate_onboard_days_thresholds(conn)
    seed_default_config()


# 后续版本新增的列：CREATE TABLE IF NOT EXISTS 不会改动已有表结构，需显式补齐
_MIGRATIONS = {
    "personnel": [("contract_end_date", "TEXT"), ("platform_id", "INTEGER")],
    "room": [("platform_id", "INTEGER")],
    "lifeboat": [("platform_id", "INTEGER")],
    "medicine": [("platform_id", "INTEGER")],
    "equipment": [("platform_id", "INTEGER")],
}

# 持 platform_id 的根表（子表通过父表 JOIN 派生过滤）
_ROOT_TABLES = ("personnel", "room", "lifeboat", "medicine", "equipment")

# 住井天数口径由「自然日差」改为「含首日」后，存量库的预警阈值需整体 +1，
# 以保持原有触发点（在平台满 28/29/30 个自然日）；只执行一次，用标记键幂等。
_ONBOARD_DAYS_KEYS = ("onboard_yellow_days", "onboard_red_days", "onboard_limit_days")
_ONBOARD_DAYS_MARK = "onboard_days_inclusive"


def migrate_onboard_days_thresholds(conn):
    """把存量库中已写入的住井预警阈值 +1（新库无记录，不影响默认值）。"""
    if conn.execute("SELECT 1 FROM sys_config WHERE key = ?",
                    (_ONBOARD_DAYS_MARK,)).fetchone():
        return
    for key in _ONBOARD_DAYS_KEYS:
        row = conn.execute("SELECT value FROM sys_config WHERE key = ?", (key,)).fetchone()
        if row is None:
            continue                                # 未写入过，交给默认值
        try:
            value = int(float(row["value"]))
        except (TypeError, ValueError):
            continue                                # 非法值由 get_int 回退默认
        conn.execute("UPDATE sys_config SET value = ? WHERE key = ?",
                     (str(min(value + 1, 365)), key))
    conn.execute("INSERT INTO sys_config(key, value, description) VALUES(?, ?, ?)",
                 (_ONBOARD_DAYS_MARK, "1", "住井天数含首日口径迁移标记"))


def apply_migrations(conn):
    """为已存在的旧库补齐新增列，保证「拷贝即用」的升级路径可用。"""
    for table, columns in _MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    migrate_platform(conn)


def migrate_platform(conn):
    """二期多平台迁移：生成默认平台，并把无归属的旧数据回填到默认平台。"""
    row = conn.execute("SELECT id FROM platform ORDER BY id LIMIT 1").fetchone()
    if row:
        platform_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO platform(code, name, owner, location, status, remark, created_at)"
            " VALUES(?, ?, ?, ?, 1, ?, ?)",
            (config.DEFAULT_PLATFORM_CODE, config.DEFAULT_PLATFORM_NAME,
             config.COMPANY, "", "系统默认平台", now_str()))
        platform_id = cur.lastrowid

    for table in _ROOT_TABLES:
        conn.execute(f"UPDATE {table} SET platform_id = ? WHERE platform_id IS NULL",
                     (platform_id,))
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_platform"
                     f" ON {table}(platform_id)")


# 系统参数读多写少：缓存后，列表 / 看板渲染时逐行读取不再反复查库
_config_cache = {}


def clear_config_cache():
    """库内容被整体替换（如备份恢复）后调用，避免读到过期参数。"""
    _config_cache.clear()


def seed_default_config():
    """把 config.py 中的默认阈值写入 sys_config（已存在则不覆盖）。"""
    clear_config_cache()
    defaults = [
        ("onboard_yellow_days", config.ONBOARD_YELLOW_DAYS, "住井黄色预警天数"),
        ("onboard_red_days", config.ONBOARD_RED_DAYS, "住井红色报警天数"),
        ("onboard_limit_days", config.ONBOARD_LIMIT_DAYS, "住井天数上限"),
        ("checkup_expire_months", config.CHECKUP_EXPIRE_MONTHS, "体检有效月数"),
        ("medicine_expire_yellow_days", config.MEDICINE_EXPIRE_YELLOW_DAYS, "药品效期黄色预警天数"),
        ("medicine_expire_red_days", config.MEDICINE_EXPIRE_RED_DAYS, "药品效期红色报警天数"),
        ("stock_lower_default", config.STOCK_LOWER_DEFAULT, "库存下限默认值"),
        ("equipment_notice_days", config.EQUIPMENT_MAINTAIN_NOTICE_DAYS, "设备维保提前提醒天数"),
        ("backup_keep", config.BACKUP_KEEP, "备份保留份数"),
        ("health_thresholds", json.dumps(config.HEALTH_INDICATORS, ensure_ascii=False),
         "健康指标两级预警阈值"),
    ]
    with get_connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO sys_config(key, value, description) VALUES(?, ?, ?)",
            [(k, str(v), d) for k, v, d in defaults],
        )


def get_config(key, default=None):
    if key in _config_cache:
        return _config_cache[key]
    row = fetch_one("SELECT value FROM sys_config WHERE key = ?", (key,))
    value = row["value"] if row else default
    _config_cache[key] = value
    return value


def get_int(key, default):
    """读取整数型系统参数，未配置或非法时回退默认值。"""
    try:
        return int(float(get_config(key)))
    except (TypeError, ValueError):
        return default


def set_config(key, value, description=None):
    if fetch_one("SELECT 1 FROM sys_config WHERE key = ?", (key,)):
        execute("UPDATE sys_config SET value = ? WHERE key = ?", (str(value), key))
    else:
        execute("INSERT INTO sys_config(key, value, description) VALUES(?, ?, ?)",
                (key, str(value), description))
    _config_cache[key] = str(value)


# ---------------------------------------------------------------- 日志
def write_op_log(user_id, module, action, target=None, detail=None):
    """关键操作审计：删除、导入、参数修改等由各业务服务调用。"""
    execute(
        "INSERT INTO op_log(user_id, op_time, module, action, target, detail)"
        " VALUES(?, ?, ?, ?, ?, ?)",
        (user_id, now_str(), module, action, target, detail),
    )


def write_login_log(user_id, username, result, detail=None, ip=None):
    execute(
        "INSERT INTO login_log(user_id, username, login_time, ip, result, detail)"
        " VALUES(?, ?, ?, ?, ?, ?)",
        (user_id, username, now_str(), ip or "本机", result, detail),
    )


# ---------------------------------------------------------------- 备份
def backup_now(tag=None):
    """备份数据库，返回备份文件路径。启动时每日自动执行一次。"""
    if not database_exists():
        return None
    stamp = now_str(fmt="%Y%m%d")
    name = f"platform_{stamp}{('_' + tag) if tag else ''}.db"
    target = config.BACKUP_DIR / name
    shutil.copy2(config.DB_PATH, target)
    clean_old_backups()
    return target


def clean_old_backups():
    """仅保留最近 N 份备份（N 可在系统设置中调整），控制磁盘占用。"""
    files = sorted(config.BACKUP_DIR.glob("platform_*.db"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[get_int("backup_keep", config.BACKUP_KEEP):]:
        try:
            old.unlink()
        except OSError:
            pass


def auto_backup_daily():
    """每日首次启动自动备份一次（同一天已备份则跳过）。"""
    if not database_exists():
        return None
    stamp = now_str(fmt="%Y%m%d")
    if (config.BACKUP_DIR / f"platform_{stamp}.db").exists():
        return None
    return backup_now()