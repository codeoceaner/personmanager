-- 海上平台人员动态管理系统 —— 数据库结构（SQLite）
-- 版本 V2.0  对应产品设计文档第 6 节

PRAGMA foreign_keys = ON;

-- ============================================================ 用户与日志
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    salt            TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'normal_user',
    must_change_pwd INTEGER NOT NULL DEFAULT 0,
    status          INTEGER NOT NULL DEFAULT 1,      -- 1 启用 / 0 停用
    fail_count      INTEGER NOT NULL DEFAULT 0,      -- 连续登录失败次数
    locked_until    TEXT,                            -- 锁定截止时间
    created_at      TEXT    NOT NULL,
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS login_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   TEXT,
    login_time TEXT NOT NULL,
    ip         TEXT,
    result     TEXT,                                 -- 成功 / 密码错误 / 账号锁定 / 账号停用
    detail     TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS op_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    op_time TEXT NOT NULL,
    module  TEXT,
    action  TEXT,
    target  TEXT,
    detail  TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- ============================================================ 平台主数据
-- 二期：多平台管理。业务数据按平台隔离，旧库迁移时统一归属默认平台。
CREATE TABLE IF NOT EXISTS platform (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,                 -- 平台编码
    name       TEXT NOT NULL,                        -- 平台名称
    owner      TEXT,                                 -- 归属公司
    location   TEXT,                                 -- 海域位置
    status     INTEGER NOT NULL DEFAULT 1,           -- 1 启用 / 0 停用
    remark     TEXT,
    created_at TEXT NOT NULL
);

-- ============================================================ 人员主表
CREATE TABLE IF NOT EXISTS personnel (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id     INTEGER,                         -- 所属平台
    emp_no          TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    gender          TEXT,
    age             INTEGER,
    id_card         TEXT,
    phone           TEXT,
    unit            TEXT,
    person_type     TEXT,                            -- 内部人员 / 外协人员 / 甲方人员
    post            TEXT,
    emergency_contact TEXT,
    emergency_phone TEXT,
    onboard_time    TEXT,                            -- 上平台时间（住井天数起算点）
    planned_off_time TEXT,
    contract_end_date TEXT,                          -- 外协人员合同到期时间
    actual_off_time TEXT,
    status          TEXT NOT NULL DEFAULT '在平台',
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    deleted         INTEGER NOT NULL DEFAULT 0
);

-- ============================================================ 登离记录
CREATE TABLE IF NOT EXISTS checkin_record (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    INTEGER NOT NULL,
    checkin_time TEXT NOT NULL,
    operator     TEXT,
    note         TEXT,
    FOREIGN KEY (person_id) REFERENCES personnel(id)
);

CREATE TABLE IF NOT EXISTS leave_record (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL,
    leave_time  TEXT NOT NULL,
    destination TEXT,
    reason      TEXT,
    operator    TEXT,
    note        TEXT,
    FOREIGN KEY (person_id) REFERENCES personnel(id)
);

-- ============================================================ 房间与救生艇
CREATE TABLE IF NOT EXISTS room (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id   INTEGER,                           -- 所属平台
    room_no       TEXT NOT NULL UNIQUE,
    gender_limit  TEXT,                              -- 男 / 女 / 不限
    capacity      INTEGER NOT NULL DEFAULT 4,
    unit_priority TEXT,
    status        TEXT NOT NULL DEFAULT '可用'        -- 可用 / 停用
);

CREATE TABLE IF NOT EXISTS lifeboat (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id INTEGER,                             -- 所属平台
    boat_no  TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL DEFAULT 25,
    location TEXT,
    status   TEXT NOT NULL DEFAULT '可用'             -- 可用 / 停用
);

-- 分配履历：登记自动写入，离开自动释放
CREATE TABLE IF NOT EXISTS assignment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER NOT NULL,
    resource_type TEXT NOT NULL,                     -- room / lifeboat
    resource_id   INTEGER NOT NULL,
    start_time    TEXT NOT NULL,
    end_time      TEXT,
    status        TEXT NOT NULL DEFAULT '使用中',      -- 使用中 / 已释放
    operator      TEXT,
    FOREIGN KEY (person_id) REFERENCES personnel(id)
);

-- ============================================================ 健康档案（1:1）
CREATE TABLE IF NOT EXISTS health_profile (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id          INTEGER NOT NULL UNIQUE,
    height_cm          REAL,
    weight_kg          REAL,
    bmi                REAL,
    blood_type         TEXT,
    rh_type            TEXT,
    last_checkup_date  TEXT,
    checkup_org        TEXT,
    checkup_report_path TEXT,
    parse_status       TEXT DEFAULT '未解析',         -- 未解析 / 待核对 / 已确认
    medical_history    TEXT,
    surgery_history    TEXT,
    allergy_history    TEXT,
    heart_disease      INTEGER DEFAULT 0,            -- 心脏病
    diabetes           INTEGER DEFAULT 0,            -- 糖尿病
    hypertension       INTEGER DEFAULT 0,            -- 高血压
    occupational_disease INTEGER DEFAULT 0,          -- 职业病
    occupational_desc  TEXT,
    updated_at         TEXT,
    FOREIGN KEY (person_id) REFERENCES personnel(id)
);

-- ============================================================ 日常监测（1:N）
CREATE TABLE IF NOT EXISTS daily_check (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id      INTEGER NOT NULL,
    check_date     TEXT NOT NULL,
    systolic       REAL,
    diastolic      REAL,
    blood_sugar    REAL,
    weight_kg      REAL,
    homocysteine   REAL,
    cholesterol    REAL,
    ldl_c          REAL,
    hdl_c          REAL,
    abnormal_level TEXT DEFAULT '正常',               -- 正常 / 黄色预警 / 红色报警
    abnormal_items TEXT,
    recorder       TEXT,
    note           TEXT,
    FOREIGN KEY (person_id) REFERENCES personnel(id)
);

-- ============================================================ 药品与库存
CREATE TABLE IF NOT EXISTS medicine (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id    INTEGER,                          -- 所属平台
    code           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    spec           TEXT,
    dosage_form    TEXT,
    unit           TEXT,
    manufacturer   TEXT,
    category       TEXT,                             -- 急救 / 常用 / 慢病 / 其他
    is_prescription INTEGER DEFAULT 0,
    stock_lower    INTEGER DEFAULT 20,
    stock_upper    INTEGER DEFAULT 60,
    status         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS medicine_stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id  INTEGER NOT NULL,
    batch_no     TEXT,
    produce_date TEXT,
    expire_date  TEXT,
    quantity     INTEGER NOT NULL DEFAULT 0,
    supplier     TEXT,
    location     TEXT,
    FOREIGN KEY (medicine_id) REFERENCES medicine(id)
);

CREATE TABLE IF NOT EXISTS medicine_io (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL,
    batch_no    TEXT,
    io_type     TEXT NOT NULL,                       -- 入库 / 出库 / 盘点
    quantity    INTEGER NOT NULL DEFAULT 0,
    person_id   INTEGER,
    purpose     TEXT,
    operator    TEXT,
    io_time     TEXT NOT NULL,
    FOREIGN KEY (medicine_id) REFERENCES medicine(id)
);

-- ============================================================ 医疗设备
CREATE TABLE IF NOT EXISTS equipment (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id      INTEGER,                        -- 所属平台
    name             TEXT NOT NULL,
    model            TEXT,
    serial_no        TEXT UNIQUE,
    manufacturer     TEXT,
    purchase_date    TEXT,
    start_date       TEXT,
    location         TEXT,
    keeper           TEXT,
    status           TEXT DEFAULT '在用',             -- 在用 / 维修 / 报废
    last_calibration TEXT,
    next_calibration TEXT,
    keep_boat_no     TEXT
);

CREATE TABLE IF NOT EXISTS equipment_use (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL,
    person_id    INTEGER,
    use_time     TEXT NOT NULL,
    item         TEXT,
    result       TEXT,
    operator     TEXT,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);

-- ============================================================ 个人用药登记
CREATE TABLE IF NOT EXISTS medication_plan (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER NOT NULL,
    medicine_name TEXT NOT NULL,
    dosage        TEXT,
    frequency     TEXT,
    start_date    TEXT,
    follow_up     TEXT,
    note          TEXT,
    FOREIGN KEY (person_id) REFERENCES personnel(id)
);

-- ============================================================ 系统参数
CREATE TABLE IF NOT EXISTS sys_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    description TEXT
);

-- ============================================================ 索引
CREATE INDEX IF NOT EXISTS idx_personnel_emp_no     ON personnel(emp_no);
CREATE INDEX IF NOT EXISTS idx_personnel_type_status ON personnel(person_type, status);
CREATE INDEX IF NOT EXISTS idx_personnel_onboard    ON personnel(status, onboard_time);
CREATE INDEX IF NOT EXISTS idx_checkin_person       ON checkin_record(person_id);
CREATE INDEX IF NOT EXISTS idx_leave_person         ON leave_record(person_id);
CREATE INDEX IF NOT EXISTS idx_daily_check          ON daily_check(person_id, check_date);
CREATE INDEX IF NOT EXISTS idx_daily_level          ON daily_check(abnormal_level);
CREATE INDEX IF NOT EXISTS idx_assign_resource      ON assignment(resource_type, resource_id, status);
CREATE INDEX IF NOT EXISTS idx_assign_person        ON assignment(person_id, status);
CREATE INDEX IF NOT EXISTS idx_stock_expire         ON medicine_stock(expire_date);
CREATE INDEX IF NOT EXISTS idx_stock_medicine       ON medicine_stock(medicine_id);
CREATE INDEX IF NOT EXISTS idx_medicine_io_time     ON medicine_io(io_time);
CREATE INDEX IF NOT EXISTS idx_equip_calibration    ON equipment(next_calibration);
CREATE INDEX IF NOT EXISTS idx_login_log_time       ON login_log(login_time);
CREATE INDEX IF NOT EXISTS idx_op_log_time          ON op_log(op_time);
-- 注：platform_id 相关索引在 database.migrate_platform() 中创建，
--     以保证旧库先补齐列、再建索引（executescript 阶段列可能尚不存在）。