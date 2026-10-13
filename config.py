# -*- coding: utf-8 -*-
"""全局配置：路径、业务阈值、权限定义。

本文件只存放"默认值"，运行期可调整的参数（健康阈值、库存上下限等）
会写入数据库 sys_config 表，由系统设置界面维护。
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------- 应用信息
APP_NAME = "海上平台人员动态管理系统"
APP_SHORT_NAME = "海上平台人员动态管理系统"
APP_VERSION = "2.0"
COMPANY = "海洋钻井公司"

# ---------------------------------------------------------------- 平台
# 多平台管理：旧库迁移与首次运行都会生成该默认平台，旧数据统一归属至此
DEFAULT_PLATFORM_CODE = "P01"
DEFAULT_PLATFORM_NAME = "默认平台"


# ---------------------------------------------------------------- 路径解析
def _resource_dir():
    """只读资源目录：打包后随 exe 解压到临时目录，源码运行时为项目目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _app_dir():
    """可写数据根目录：打包后取 exe 同级目录，实现免安装、数据可随程序拷贝。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _resource_dir()                   # 只读资源（db/schema.sql）
APP_DIR = _app_dir()                         # 可写数据根目录

DATA_DIR = APP_DIR / "data"
ATTACH_DIR = APP_DIR / "attachments"       # 体检报告，按工号归档
REPORT_DIR = APP_DIR / "reports"           # 导出文件
BACKUP_DIR = APP_DIR / "backup"            # 数据库备份
TEMPLATE_DIR = APP_DIR / "templates"       # 导入模板

DB_PATH = DATA_DIR / "platform.db"

for _d in (DATA_DIR, ATTACH_DIR, REPORT_DIR, BACKUP_DIR, TEMPLATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 界面参数
WINDOW_SIZE = (1440, 900)                   # 期望尺寸（超出屏幕时自动收缩）
WINDOW_MIN_SIZE = (1200, 660)               # 最小尺寸需小于常见 1366×768 屏幕
LOGIN_WINDOW_SIZE = (460, 560)

FONT_FAMILY = "Microsoft YaHei UI"          # 中文界面字体
FONT_FAMILY_FALLBACK = "微软雅黑"

# ---------------------------------------------------------------- 登录安全
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@2026"
LOGIN_MAX_FAIL = 5                          # 连续错误次数上限
LOGIN_LOCK_MINUTES = 10                     # 锁定时长（分钟）
PASSWORD_MIN_LENGTH = 8
PASSWORD_RULE_TEXT = "至少 8 位，需同时包含字母与数字"

# ---------------------------------------------------------------- 角色
ROLE_SUPER_ADMIN = "super_admin"
ROLE_NORMAL_USER = "normal_user"
ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "超级用户",
    ROLE_NORMAL_USER: "普通用户",
}

# ---------------------------------------------------------------- 权限项
# 命名规则：<模块>.<动作>，导航与按钮均按权限项控制显示
PERMISSIONS = {
    "dashboard.view": "动态看板查看",

    "personnel.view": "人员信息查看",
    "personnel.create": "人员登记",
    "personnel.update": "人员信息修改",
    "personnel.delete": "人员信息删除",
    "personnel.import": "人员信息批量导入",
    "personnel.export": "人员信息批量导出",
    "assign.manage": "房间分配 / 救生艇分配",

    "health.view": "健康档案查看",
    "health.create": "健康档案新增",
    "health.update": "健康档案修改",
    "health.delete": "健康档案删除",
    "check.view": "日常监测查看",
    "check.create": "日常监测录入",
    "check.update": "日常监测修改",
    "check.delete": "日常监测删除",

    "medicine.view": "药品信息查看",
    "medicine.create": "药品信息新增",
    "medicine.update": "药品信息修改",
    "medicine.delete": "药品信息删除",
    "equipment.view": "医疗设备查看",
    "equipment.create": "医疗设备新增",
    "equipment.update": "医疗设备修改",
    "equipment.delete": "医疗设备删除",

    "supply.view": "医疗物资台账查看",
    "supply.manage": "药品库存出入库 / 盘点",

    "user.manage": "用户账号管理",
    "config.manage": "健康阈值与预警参数配置",
    "backup.manage": "数据备份 / 恢复",
    "log.view": "操作日志与登录日志查看",
    "data.manage": "数据管理（导入 / 导出 / 备份）",
}

# 超级用户拥有全部权限；普通用户按产品设计 4.1 权限矩阵授予
ROLE_PERMISSIONS = {
    ROLE_SUPER_ADMIN: set(PERMISSIONS.keys()),
    ROLE_NORMAL_USER: {
        "dashboard.view",
        "personnel.view", "personnel.create", "personnel.update",
        "personnel.delete", "personnel.import", "personnel.export",
        "assign.manage",
        "health.view", "health.create", "health.update", "health.delete",
        "check.view", "check.create", "check.update", "check.delete",
        "medicine.view", "medicine.create", "medicine.update", "medicine.delete",
        "equipment.view", "equipment.create", "equipment.update", "equipment.delete",
        "supply.view", "supply.manage",
        "data.manage",
    },
}

# ---------------------------------------------------------------- 住井天数预警
# 住井天数含首日（上平台当天即第 1 天），故阈值较自然日差整体 +1：
# 29/30/31 天 对应 在平台满 28/29/30 个自然日，保持产品设计 5.1.4 的触发点不变。
ONBOARD_YELLOW_DAYS = 29       # ≥29 天 黄色预警
ONBOARD_RED_DAYS = 30          # ≥30 天 红色报警
ONBOARD_LIMIT_DAYS = 31        # ≥31 天 超期，强制拦截新登记

# ---------------------------------------------------------------- 人员类型
PERSON_TYPES = ("内部人员", "外协人员", "甲方人员")
GENDERS = ("男", "女")
PERSON_STATUS_ONBOARD = "在平台"
PERSON_STATUS_LEFT = "已离开"
LEAVE_REASONS = ("休假", "调离", "公务", "其他")

# ---------------------------------------------------------------- 健康阈值
# direction: high_bad = 高于正常为异常；low_bad = 低于正常为异常；none = 仅记录
HEALTH_INDICATORS = [
    {"key": "systolic", "label": "收缩压", "unit": "mmHg", "direction": "high_bad",
     "normal_min": 90, "normal_max": 139, "yellow_max": 159, "red_min": 160},
    {"key": "diastolic", "label": "舒张压", "unit": "mmHg", "direction": "high_bad",
     "normal_min": 60, "normal_max": 89, "yellow_max": 99, "red_min": 100},
    {"key": "blood_sugar", "label": "血糖(空腹)", "unit": "mmol/L", "direction": "high_bad",
     "normal_min": 3.9, "normal_max": 6.1, "yellow_max": 7.0, "red_min": 7.0},
    {"key": "bmi", "label": "BMI", "unit": "kg/m²", "direction": "high_bad",
     "normal_min": 18.5, "normal_max": 23.9, "yellow_max": 27.9, "red_min": 28.0},
    {"key": "homocysteine", "label": "同型半胱氨酸", "unit": "μmol/L", "direction": "high_bad",
     "normal_min": 0, "normal_max": 15, "yellow_max": 20, "red_min": 20},
    {"key": "cholesterol", "label": "总胆固醇", "unit": "mmol/L", "direction": "high_bad",
     "normal_min": 0, "normal_max": 5.2, "yellow_max": 6.2, "red_min": 6.2},
    {"key": "ldl_c", "label": "低密度脂蛋白", "unit": "mmol/L", "direction": "high_bad",
     "normal_min": 0, "normal_max": 3.4, "yellow_max": 4.1, "red_min": 4.1},
    {"key": "hdl_c", "label": "高密度脂蛋白", "unit": "mmol/L", "direction": "low_bad",
     "normal_min": 1.0, "normal_max": 99.0, "yellow_min": 0.8, "red_max": 0.8},
]
HEALTH_INDICATOR_MAP = {item["key"]: item for item in HEALTH_INDICATORS}
CHECKUP_EXPIRE_MONTHS = 6      # 超过 6 个月未体检 → 体检到期提醒

# ---------------------------------------------------------------- 健康档案
BLOOD_TYPES = ("未知", "A", "B", "O", "AB")
RH_TYPES = ("未知", "阳性", "阴性")
PARSE_STATUS = ("未解析", "待核对", "已确认")
CHECKUP_LEVELS = ("有效", "已到期", "未体检")

# 慢病标记（字段名, 中文名）
CHRONIC_KEYS = (
    ("heart_disease", "心脏病"),
    ("diabetes", "糖尿病"),
    ("hypertension", "高血压"),
    ("occupational_disease", "职业病"),
)

# 日常监测录入项（字段名, 中文名, 单位）—— 体重用于结合档案身高计算 BMI
MONITOR_FIELDS = (
    ("systolic", "收缩压", "mmHg"),
    ("diastolic", "舒张压", "mmHg"),
    ("blood_sugar", "血糖(空腹)", "mmol/L"),
    ("weight_kg", "体重", "kg"),
    ("homocysteine", "同型半胱氨酸", "μmol/L"),
    ("cholesterol", "总胆固醇", "mmol/L"),
    ("ldl_c", "低密度脂蛋白", "mmol/L"),
    ("hdl_c", "高密度脂蛋白", "mmol/L"),
)

# 体检报告允许的附件类型
REPORT_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")

# ---------------------------------------------------------------- 医疗物资预警
MEDICINE_EXPIRE_YELLOW_DAYS = 90    # 距有效期 ≤3 个月 黄色报警
MEDICINE_EXPIRE_RED_DAYS = 30       # 距有效期 ≤1 个月 红色报警
STOCK_LOWER_DEFAULT = 20            # 库存下限默认值
STOCK_UPPER_RATIO = 3               # 库存上限 = 下限 × 3
EQUIPMENT_MAINTAIN_NOTICE_DAYS = 30  # 维保/校准到期提前提醒天数

# ---------------------------------------------------------------- 医疗物资台账
MEDICINE_CATEGORIES = ("急救", "常用", "慢病", "其他")
DOSAGE_FORMS = ("片剂", "胶囊", "颗粒", "注射剂", "口服液", "软膏", "喷雾剂", "其他")
MEDICINE_UNITS = ("盒", "瓶", "支", "袋", "片", "支/盒", "其他")
MEDICINE_IO_TYPES = ("入库", "出库", "盘点")
EQUIPMENT_STATUSES = ("在用", "维修", "报废")
SUPPLY_WARNING_SOURCES = ("药品效期", "药品库存", "设备维保")

# 预警级别与状态胶囊文案（与 theme.SEVERITY_COLORS 对应）
EXPIRE_STATUSES = ("正常", "黄色预警", "红色报警", "已过期")
STOCK_STATUSES = ("正常", "库存偏低", "库存紧急", "库存积压")
EQUIPMENT_MAINTAIN_LEVELS = ("正常", "即将到期", "已超期")

# 药品档案表单字段：(字段名, 标签, 类型, 选项)
MEDICINE_FORM_FIELDS = [
    ("code", "药品编码 *", "entry", None),
    ("name", "通用名 *", "entry", None),
    ("spec", "规格", "entry", None),
    ("dosage_form", "剂型", "option", DOSAGE_FORMS),
    ("unit", "单位", "combo", MEDICINE_UNITS),
    ("manufacturer", "生产厂家", "entry", None),
    ("category", "类别 *", "option", MEDICINE_CATEGORIES),
    ("is_prescription", "处方药", "option", ("否", "是")),
    ("stock_lower", "库存下限", "entry", None),
    ("stock_upper", "库存上限", "entry", None),
]

# 医疗设备表单字段：(字段名, 标签, 类型, 选项)
EQUIPMENT_FORM_FIELDS = [
    ("name", "设备名称 *", "entry", None),
    ("model", "型号", "entry", None),
    ("serial_no", "设备编号 *", "entry", None),
    ("manufacturer", "生产厂家", "entry", None),
    ("purchase_date", "购置日期", "entry", None),
    ("start_date", "启用日期", "entry", None),
    ("location", "存放位置", "entry", None),
    ("keeper", "责任人", "entry", None),
    ("status", "状态 *", "option", EQUIPMENT_STATUSES),
    ("last_calibration", "上次校准", "entry", None),
    ("next_calibration", "下次校准 / 维保", "entry", None),
    ("keep_boat_no", "配置救生艇", "boat", None),
]

# 库存台账导出列：(中文表头, 字段名)
MEDICINE_EXPORT_COLUMNS = [
    ("药品编码", "code"), ("通用名", "name"), ("规格", "spec"),
    ("剂型", "dosage_form"), ("单位", "unit"), ("生产厂家", "manufacturer"),
    ("类别", "category"), ("处方药", "is_prescription_text"),
    ("库存量", "total_quantity"), ("库存下限", "stock_lower"),
    ("库存上限", "stock_upper"), ("批次数", "batch_count"),
    ("最近效期", "nearest_expire"), ("效期状态", "expire_status"),
    ("库存状态", "stock_status"), ("预警级别", "warning_level"),
]

# ---------------------------------------------------------------- 动态看板
DASHBOARD_REFRESH_SECONDS = 30          # 看板默认自动刷新间隔（秒）
DASHBOARD_FLOW_DAYS = 30                # 流动趋势折线图统计天数
DASHBOARD_CHART_TOP_N = 10              # 柱状图 / 条形图最多展示的分组数
# 看板预警列表来源（与各业务服务输出的 source 一致）
DASHBOARD_WARNING_SOURCES = ("住井超期", "健康异常", "体检到期",
                             "药品效期", "药品库存", "设备维保")
DASHBOARD_WARNING_LEVELS = ("红色报警", "黄色预警", "提示")
# 看板预警列表导出列：(中文表头, 字段名)；人员类预警附关联人员信息，非人员类推「—」
DASHBOARD_EXPORT_COLUMNS = [
    ("级别", "level"), ("来源", "source"), ("对象", "target"),
    ("编码/编号", "code"), ("人员类型", "person_type"), ("岗位/工种", "post"),
    ("联系电话", "phone"), ("所属单位", "unit"), ("房间/救生艇", "resource"),
    ("预警详情", "detail"),
]

# ---------------------------------------------------------------- 数据管理导出模板
# 「数据管理」页固定导出模板：(中文表头, 字段名)，与各业务服务list函数的返回字段一一对应
HEALTH_EXPORT_COLUMNS = [
    ("工号", "emp_no"), ("姓名", "name"), ("性别", "gender"), ("年龄", "age"),
    ("所属单位", "unit"), ("人员类型", "person_type"),
    ("身高(cm)", "height_cm"), ("体重(kg)", "weight_kg"), ("BMI", "bmi"),
    ("血型", "blood_type"), ("Rh血型", "rh_type"),
    ("最近体检日期", "last_checkup_date"), ("体检机构", "checkup_org"),
    ("体检状态", "checkup_level"), ("解析状态", "parse_status"),
    ("慢病标记", "chronic_text"), ("既往病史", "medical_history"),
    ("手术史", "surgery_history"), ("过敏史", "allergy_history"),
    ("职业病描述", "occupational_desc"),
]
MONITOR_EXPORT_COLUMNS = [
    ("工号", "emp_no"), ("姓名", "name"), ("所属单位", "unit"),
    ("人员类型", "person_type"), ("监测日期", "check_date"),
    ("收缩压", "systolic"), ("舒张压", "diastolic"), ("血糖(空腹)", "blood_sugar"),
    ("体重(kg)", "weight_kg"), ("同型半胱氨酸", "homocysteine"),
    ("总胆固醇", "cholesterol"), ("低密度脂蛋白", "ldl_c"),
    ("高密度脂蛋白", "hdl_c"), ("预警级别", "abnormal_level"),
    ("异常项", "abnormal_items"), ("记录人", "recorder"), ("备注", "note"),
]
EQUIPMENT_EXPORT_COLUMNS = [
    ("设备名称", "name"), ("型号", "model"), ("设备编号", "serial_no"),
    ("生产厂家", "manufacturer"), ("购置日期", "purchase_date"),
    ("启用日期", "start_date"), ("存放位置", "location"), ("责任人", "keeper"),
    ("状态", "status"), ("上次校准", "last_calibration"),
    ("下次校准/维保", "next_calibration"), ("配置救生艇", "keep_boat_no"),
    ("使用次数", "use_count"), ("维保状态", "maintain_status"),
    ("距维保天数", "days_to_maintain"),
]

# ---------------------------------------------------------------- 数据维护
BACKUP_KEEP = 7                # 备份保留份数

# ---------------------------------------------------------------- 房间与救生艇资源
# 首次运行按以下参数生成默认资源；资源维护界面在 M7「系统设置」中提供
ROOM_BEDS = 4                  # 每房间床位数
MALE_FLOORS = 4                # 男房间层数
MALE_ROOMS_PER_FLOOR = 30      # 每层男房间数（合计 120 间）
FEMALE_ROOM_COUNT = 20         # 女房间数

# 救生艇：固定 4 艘，编号与舷位一一对应（左舷 LB-L-*，右舷 LB-R-*）
LIFEBOATS = (
    ("LB-L-1", "救生甲板左舷"),
    ("LB-L-2", "救生甲板左舷"),
    ("LB-R-1", "救生甲板右舷"),
    ("LB-R-2", "救生甲板右舷"),
)
LIFEBOAT_CAPACITY = 25         # 每艇定员

# ---------------------------------------------------------------- 列表分页
PAGE_SIZE = 50

# 常用单位预置（登记时可下拉选择，也可手工输入其它单位）
COMMON_UNITS = ("中海油服", "海洋钻井公司", "甲方单位", "外协单位")

# ---------------------------------------------------------------- 人员表单字段
# kind: entry 文本 / option 下拉 / combo 可输入下拉 / room 房间 / boat 救生艇
# 人员登记页与人员编辑对话框共用同一份定义，避免字段不一致
PERSON_FORM_FIELDS = [
    ("emp_no", "工号 *", "entry", None),
    ("name", "姓名 *", "entry", None),
    ("gender", "性别 *", "option", GENDERS),
    ("age", "年龄 *", "entry", None),
    ("id_card", "身份证号 *", "entry", None),
    ("phone", "联系电话 *", "entry", None),
    ("unit", "所属单位 *", "combo", None),
    ("person_type", "人员类型 *", "option", PERSON_TYPES),
    ("post", "岗位 / 工种", "entry", None),
    ("onboard_time", "上平台时间 *", "entry", None),
    ("planned_off_time", "预计下平台时间", "entry", None),
    ("emergency_contact", "紧急联系人 *", "entry", None),
    ("emergency_phone", "紧急联系电话 *", "entry", None),
    ("room_no", "房间号 *", "room", None),
    ("boat_no", "救生艇编号 *", "boat", None),
]

# Excel 导入导出列：(中文表头, 字段名, 是否必填)
EXCEL_COLUMNS = [
    ("工号", "emp_no", True),
    ("姓名", "name", True),
    ("性别", "gender", True),
    ("年龄", "age", True),
    ("身份证号", "id_card", True),
    ("联系电话", "phone", True),
    ("所属单位", "unit", True),
    ("人员类型", "person_type", True),
    ("岗位/工种", "post", False),
    ("上平台时间", "onboard_time", True),
    ("预计下平台时间", "planned_off_time", False),
    ("紧急联系人", "emergency_contact", True),
    ("紧急联系电话", "emergency_phone", True),
    ("房间号", "room_no", False),
    ("救生艇编号", "boat_no", False),
]

# 导出文件额外附带的分析列
EXCEL_EXTRA_COLUMNS = [("住井天数", "onboard_days"), ("住井状态", "onboard_level")]

# ---------------------------------------------------------------- 系统设置
# 可配置参数：(sys_config 键, 中文名, 单位, 整数上下限)，超级用户可调整
SETTING_PARAMS = [
    ("onboard_yellow_days", "住井黄色预警天数", "天", 1, 365),
    ("onboard_red_days", "住井红色报警天数", "天", 1, 365),
    ("onboard_limit_days", "住井天数上限", "天", 1, 365),
    ("checkup_expire_months", "体检有效月数", "月", 1, 60),
    ("medicine_expire_yellow_days", "药品效期黄色预警", "天", 1, 3650),
    ("medicine_expire_red_days", "药品效期红色报警", "天", 1, 3650),
    ("stock_lower_default", "库存下限默认值", "件", 0, 100000),
    ("equipment_notice_days", "设备维保提前提醒", "天", 1, 3650),
    ("backup_keep", "备份保留份数", "份", 1, 60),
]
HEALTH_THRESHOLD_FIELDS = ("normal_min", "normal_max", "yellow_max", "red_min",
                           "yellow_min", "red_max")
LOG_PAGE_SIZE = 50                 # 日志列表每页条数
ROLE_OPTIONS = (ROLE_SUPER_ADMIN, ROLE_NORMAL_USER)
BACKUP_NAME_STAMP = "%Y%m%d_%H%M%S"

# ---------------------------------------------------------------- 数据库
DB_TIMEOUT = 10.0