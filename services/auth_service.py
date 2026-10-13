# -*- coding: utf-8 -*-
"""认证服务：密码加盐哈希、登录校验与锁定、改密、权限判定、日志记录。"""

import datetime
import hashlib
import secrets
from dataclasses import dataclass, field

import config
from db import database


# ---------------------------------------------------------------- 用户模型
@dataclass
class User:
    id: int
    username: str
    role: str
    must_change_pwd: bool = False
    status: int = 1
    last_login: str = None
    permissions: set = field(default_factory=set)

    @property
    def role_label(self):
        return config.ROLE_LABELS.get(self.role, self.role)

    @property
    def is_super_admin(self):
        return self.role == config.ROLE_SUPER_ADMIN

    def can(self, permission):
        """按钮级权限判定：无权限时界面直接不渲染该按钮。"""
        return permission in self.permissions


# ---------------------------------------------------------------- 密码处理
def make_salt():
    return secrets.token_hex(16)


def hash_password(password, salt):
    """SHA-256 + 随机盐，密码不可逆存储。"""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def check_password_strength(password):
    """返回 (是否合格, 提示语)。"""
    if not password or len(password) < config.PASSWORD_MIN_LENGTH:
        return False, f"密码长度不足，{config.PASSWORD_RULE_TEXT}"
    if not any(c.isalpha() for c in password):
        return False, f"密码需包含字母，{config.PASSWORD_RULE_TEXT}"
    if not any(c.isdigit() for c in password):
        return False, f"密码需包含数字，{config.PASSWORD_RULE_TEXT}"
    return True, ""


# ---------------------------------------------------------------- 内部装配
def _row_to_user(row):
    return User(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        must_change_pwd=bool(row["must_change_pwd"]),
        status=row["status"],
        last_login=row["last_login"],
        permissions=set(config.ROLE_PERMISSIONS.get(row["role"], set())),
    )


def get_user_by_id(user_id):
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    return _row_to_user(row) if row else None


# ---------------------------------------------------------------- 初始化账号
def ensure_default_admin():
    """首次运行内置超级用户 admin / Admin@2026，首次登录强制改密。"""
    row = database.fetch_one("SELECT id FROM users WHERE username = ?",
                             (config.DEFAULT_ADMIN_USERNAME,))
    if row:
        return False
    salt = make_salt()
    database.execute(
        "INSERT INTO users(username, password_hash, salt, role, must_change_pwd,"
        " status, created_at) VALUES(?, ?, ?, ?, 1, 1, ?)",
        (config.DEFAULT_ADMIN_USERNAME,
         hash_password(config.DEFAULT_ADMIN_PASSWORD, salt),
         salt, config.ROLE_SUPER_ADMIN, database.now_str()),
    )
    return True


# ---------------------------------------------------------------- 登录
def authenticate(username, password, ip=None):
    """返回 (User 或 None, 提示信息)。连续错误 5 次锁定 10 分钟。"""
    username = (username or "").strip()
    if not username or not password:
        return None, "请输入账号与密码"

    row = database.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None:
        database.write_login_log(None, username, "失败", "账号不存在", ip)
        return None, "账号或密码错误"

    if row["status"] != 1:
        database.write_login_log(row["id"], username, "失败", "账号已停用", ip)
        return None, "该账号已停用，请联系管理员"

    if row["locked_until"]:
        locked_until = _parse_time(row["locked_until"])
        now = _now()
        if locked_until and locked_until > now:
            minutes = int((locked_until - now).total_seconds() // 60) + 1
            database.write_login_log(row["id"], username, "失败", "账号锁定中", ip)
            return None, f"账号已锁定，请 {minutes} 分钟后重试"

    if hash_password(password, row["salt"]) != row["password_hash"]:
        fails = row["fail_count"] + 1
        if fails >= config.LOGIN_MAX_FAIL:
            locked_until = database.now_str(
                _now() + datetime.timedelta(minutes=config.LOGIN_LOCK_MINUTES))
            database.execute(
                "UPDATE users SET fail_count = 0, locked_until = ? WHERE id = ?",
                (locked_until, row["id"]))
            database.write_login_log(row["id"], username, "失败",
                                     f"连续错误 {config.LOGIN_MAX_FAIL} 次，账号锁定", ip)
            return None, (f"密码连续错误 {config.LOGIN_MAX_FAIL} 次，账号已锁定 "
                          f"{config.LOGIN_LOCK_MINUTES} 分钟")
        database.execute("UPDATE users SET fail_count = ? WHERE id = ?",
                         (fails, row["id"]))
        database.write_login_log(row["id"], username, "失败", f"密码错误（第 {fails} 次）", ip)
        return None, f"账号或密码错误，还可尝试 {config.LOGIN_MAX_FAIL - fails} 次"

    database.execute(
        "UPDATE users SET fail_count = 0, locked_until = NULL, last_login = ? WHERE id = ?",
        (database.now_str(), row["id"]))
    database.write_login_log(row["id"], username, "成功", "登录成功", ip)
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (row["id"],))
    return _row_to_user(row), "登录成功"


# ---------------------------------------------------------------- 改密
def change_password(user_id, old_password, new_password):
    """修改本人密码。返回 (是否成功, 提示信息)。"""
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        return False, "用户不存在"
    if hash_password(old_password or "", row["salt"]) != row["password_hash"]:
        return False, "原密码不正确"
    ok, msg = check_password_strength(new_password)
    if not ok:
        return False, msg
    if new_password == old_password:
        return False, "新密码不能与原密码相同"

    salt = make_salt()
    database.execute(
        "UPDATE users SET password_hash = ?, salt = ?, must_change_pwd = 0 WHERE id = ?",
        (hash_password(new_password, salt), salt, user_id))
    database.write_op_log(user_id, "系统", "修改密码", row["username"], "本人修改登录密码")
    return True, "密码修改成功"


# ---------------------------------------------------------------- 账号管理
def _operator_id(username):
    if not username:
        return None
    row = database.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    return row["id"] if row else None


def _is_locked(row):
    if not row["locked_until"]:
        return False
    locked_until = _parse_time(row["locked_until"])
    return bool(locked_until and locked_until > _now())


def _user_row(row):
    """账号列表展示用数据（含中文标签与锁定状态）。"""
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "role_label": config.ROLE_LABELS.get(row["role"], row["role"]),
        "status": row["status"],
        "status_text": "启用" if row["status"] == 1 else "停用",
        "lock_text": "已锁定" if _is_locked(row) else "正常",
        "must_change_pwd": bool(row["must_change_pwd"]),
        "created_at": row["created_at"] or "",
        "last_login": row["last_login"] or "—",
    }


def list_users(keyword=None, role=None, status=None):
    where, params = [], []
    if keyword:
        where.append("username LIKE ?")
        params.append(f"%{keyword}%")
    if role:
        where.append("role = ?")
        params.append(role)
    if status is not None:
        where.append("status = ?")
        params.append(int(status))
    sql = "SELECT * FROM users"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY status DESC, role DESC, username"
    return [_user_row(row) for row in database.fetch_all(sql, params)]


def _enabled_super_count(exclude_id=None):
    if exclude_id:
        row = database.fetch_one(
            "SELECT COUNT(*) AS c FROM users WHERE role = ? AND status = 1 AND id <> ?",
            (config.ROLE_SUPER_ADMIN, exclude_id))
    else:
        row = database.fetch_one(
            "SELECT COUNT(*) AS c FROM users WHERE role = ? AND status = 1",
            (config.ROLE_SUPER_ADMIN,))
    return row["c"]


def create_user(username, password, role, operator="system", must_change_pwd=True):
    """新增账号。返回 (是否成功, 提示信息)。"""
    username = (username or "").strip()
    if not username:
        return False, "请填写账号名称"
    if len(username) > 30:
        return False, "账号名称不超过 30 个字符"
    if role not in config.ROLE_OPTIONS:
        return False, "账号角色不合法"
    if database.fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
        return False, f"账号 {username} 已存在"
    ok, message = check_password_strength(password)
    if not ok:
        return False, message

    salt = make_salt()
    database.execute(
        "INSERT INTO users(username, password_hash, salt, role, must_change_pwd,"
        " status, created_at) VALUES(?, ?, ?, ?, ?, 1, ?)",
        (username, hash_password(password, salt), salt, role,
         1 if must_change_pwd else 0, database.now_str()))
    database.write_op_log(_operator_id(operator), "系统设置", "新增账号", username,
                          f"角色：{config.ROLE_LABELS.get(role, role)}")
    return True, f"账号 {username} 已创建"


def update_user_role(user_id, role, operator="system"):
    """调整账号角色；须始终保留至少一个启用的超级用户。"""
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        return False, "账号不存在"
    if role not in config.ROLE_OPTIONS:
        return False, "账号角色不合法"
    if row["role"] == role:
        return False, "角色未发生变化"
    if (row["role"] == config.ROLE_SUPER_ADMIN and role == config.ROLE_NORMAL_USER
            and row["status"] == 1 and _enabled_super_count(exclude_id=user_id) == 0):
        return False, "系统需保留至少一个启用的超级用户，无法降级"

    database.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    database.write_op_log(_operator_id(operator), "系统设置", "调整角色", row["username"],
                          f"{config.ROLE_LABELS.get(row['role'])}→"
                          f"{config.ROLE_LABELS.get(role)}")
    return True, f"{row['username']} 的角色已调整为 {config.ROLE_LABELS.get(role)}"


def set_user_status(user_id, enabled, operator="system"):
    """启用 / 停用账号；不得停用自己，也不得停用最后一个超级用户。"""
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        return False, "账号不存在"
    target = 1 if enabled else 0
    if row["status"] == target:
        return False, f"账号已处于{'启用' if target else '停用'}状态"
    if not target:
        if row["username"] == operator:
            return False, "不能停用当前登录账号"
        if (row["role"] == config.ROLE_SUPER_ADMIN
                and _enabled_super_count(exclude_id=user_id) == 0):
            return False, "系统需保留至少一个启用的超级用户，无法停用"

    database.execute("UPDATE users SET status = ? WHERE id = ?", (target, user_id))
    action = "启用账号" if target else "停用账号"
    database.write_op_log(_operator_id(operator), "系统设置", action, row["username"], None)
    return True, f"{row['username']} 已{'启用' if target else '停用'}"


def reset_user_password(user_id, new_password, operator="system"):
    """管理员重置他人密码，被重置账号下次登录须强制改密。"""
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        return False, "账号不存在"
    ok, message = check_password_strength(new_password)
    if not ok:
        return False, message

    salt = make_salt()
    database.execute(
        "UPDATE users SET password_hash = ?, salt = ?, must_change_pwd = 1,"
        " fail_count = 0, locked_until = NULL WHERE id = ?",
        (hash_password(new_password, salt), salt, user_id))
    database.write_op_log(_operator_id(operator), "系统设置", "重置密码", row["username"],
                          "被重置账号下次登录须修改密码")
    return True, f"{row['username']} 的密码已重置"


def unlock_user(user_id, operator="system"):
    """解除因连续登录失败产生的锁定。"""
    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        return False, "账号不存在"
    if not _is_locked(row):
        return False, "该账号当前未被锁定"
    database.execute("UPDATE users SET fail_count = 0, locked_until = NULL WHERE id = ?",
                     (user_id,))
    database.write_op_log(_operator_id(operator), "系统设置", "解锁账号", row["username"], None)
    return True, f"{row['username']} 已解锁"


# ---------------------------------------------------------------- 时间辅助
def _now():
    return datetime.datetime.now()


def _parse_time(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None