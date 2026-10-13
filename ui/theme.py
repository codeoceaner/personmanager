# -*- coding: utf-8 -*-
"""主题：多色调配色、字体、圆角与状态色，全部集中在此便于统一调整。

多色调约定：
    品牌主色（深海蓝）用于导航与主操作；
    辅助色按模块区分（人员蓝 / 健康青绿 / 物资靛蓝 / 看板紫 / 设置灰蓝），
    让每个模块的标题条、表头、强调条一眼可辨又不喧宾夺主；
    语义色（绿 / 金 / 红）只用于状态胶囊、角标与告警数字。
"""

import customtkinter as ctk

import config

# ---------------------------------------------------------------- 主色调
PRIMARY = "#1B4965"          # 深海蓝：导航栏、主按钮
SECONDARY = "#5FA8D3"        # 海青：次级按钮、选中态
WARNING = "#F2A104"          # 浪金：黄色预警
DANGER = "#D7263D"           # 警示红：红色报警、删除
SUCCESS = "#2E933C"          # 生态绿：正常

# 扩展辅助色（多色调：模块区分 + 中性提示）
ACCENT_TEAL = "#1F8A70"      # 青绿：健康管理
ACCENT_INDIGO = "#4A5FA5"    # 靛蓝：医疗物资
ACCENT_VIOLET = "#7A5AA6"    # 紫罗兰：动态看板
ACCENT_SLATE = "#54718A"     # 石墨灰蓝：系统设置
ACCENT_SKY = "#3E8FBF"       # 天青：人员登离
ACCENT_PLUM = "#8D5A97"      # 李子紫：数据管理

# ---------------------------------------------------------------- 层次底色
SURFACE_FORM = "#F2F5F7"     # 表单底色 / 内容区背景
SURFACE_CARD = "#FFFFFF"     # 卡片底色
SURFACE_MUTED = "#E7EDF2"    # 次级容器
SURFACE_SUNKEN = "#E9EEF3"   # 下沉区域（筛选条、页脚）
ROW_HOVER = "#EAF1F6"        # 表格行悬停
ROW_SELECTED = "#CFE3F0"     # 表格行选中

TEXT_PRIMARY = "#1A1A1A"
TEXT_SECONDARY = "#6B7280"
TEXT_ON_PRIMARY = "#FFFFFF"
BORDER = "#D6DEE5"
BORDER_LIGHT = "#E3E9EE"     # 卡片描边 / 分隔线
DIVIDER = "#EDF1F4"          # 极浅分隔线
DISABLED_BG = "#B9C4CC"
DISABLED_TEXT = "#7C8792"

# 导航栏
NAV_BG = PRIMARY
NAV_TEXT = "#D7E3EC"
NAV_ITEM_HOVER = "#26587A"
NAV_ITEM_ACTIVE = SECONDARY
NAV_GROUP_BG = "#163A50"
NAV_ITEM_SUB_BG = "#1F5570"  # 未选中子项底色（与分组头区分）

# 状态栏
STATUSBAR_BG = "#E7EDF2"

# ---------------------------------------------------------------- 模块色调
# 左侧导航分组 / 页面标题条 / 表头强调条按模块取色
MODULE_COLORS = {
    "onboard": ACCENT_SKY,
    "health": ACCENT_TEAL,
    "supply": ACCENT_INDIGO,
    "dashboard": ACCENT_VIOLET,
    "data": ACCENT_PLUM,
    "system": ACCENT_SLATE,
    "about": ACCENT_SLATE,
}
# 顶部工具栏底部的多色调细条（顺序与导航分组一致）
MODULE_STRIP = (ACCENT_SKY, ACCENT_TEAL, ACCENT_INDIGO, ACCENT_VIOLET,
                ACCENT_PLUM, ACCENT_SLATE)


def module_color(key, default=None):
    """取模块辅助色，未知模块回退到次级色。"""
    return MODULE_COLORS.get(key, default or SECONDARY)


# 当前页面所属模块：主窗口切页时设置，页面内标题条 / 卡片 / 表格默认取该色调，
# 避免在每个控件调用处重复传色，同时保证同页多色调一致。
_active_module = "onboard"


def set_active_module(key):
    """主窗口切换页面时调用，传入导航分组 key（如 onboard / health）。"""
    global _active_module
    if key in MODULE_COLORS:
        _active_module = key


def active_accent():
    """当前页面的模块色调。"""
    return MODULE_COLORS.get(_active_module, SECONDARY)


# ---------------------------------------------------------------- 图表配色
# 统计图统一色板：模块辅助色 + 语义色，保证多图之间色调一致
CHART_PALETTE = (ACCENT_SKY, ACCENT_TEAL, ACCENT_INDIGO, ACCENT_VIOLET,
                 WARNING, DANGER, ACCENT_SLATE, SUCCESS)

# ---------------------------------------------------------------- 字体
FONT_FAMILY = config.FONT_FAMILY
FONT_TITLE = (FONT_FAMILY, 22, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 15, "bold")
FONT_BODY = (FONT_FAMILY, 13)
FONT_SMALL = (FONT_FAMILY, 11)
FONT_TINY = (FONT_FAMILY, 10)
FONT_BUTTON = (FONT_FAMILY, 13, "bold")
FONT_NAV = (FONT_FAMILY, 13)
FONT_NAV_GROUP = (FONT_FAMILY, 14, "bold")
FONT_METRIC = (FONT_FAMILY, 20, "bold")
FONT_METRIC_SMALL = (FONT_FAMILY, 15, "bold")

# ---------------------------------------------------------------- 尺寸
RADIUS_CARD = 10
RADIUS_BUTTON = 8
RADIUS_TAG = 6
PAD_WINDOW = 14
PAD_CARD = 14
GAP = 10
NAV_WIDTH = 220
ACCENT_BAR = 3               # 标题条 / 表头强调条厚度

# ---------------------------------------------------------------- 状态色映射
SEVERITY_COLORS = {
    "正常": SUCCESS,
    "黄色预警": WARNING,
    "红色报警": DANGER,
    "提示": SECONDARY,
    "超期": DANGER,
    "已下平台": TEXT_SECONDARY,
    # 健康档案体检状态
    "有效": SUCCESS,
    "已到期": DANGER,
    "未体检": WARNING,
    # 药品效期 / 库存状态
    "已过期": DANGER,
    "库存偏低": WARNING,
    "库存紧急": DANGER,
    "库存积压": SECONDARY,
    # 设备维保 / 状态
    "即将到期": WARNING,
    "已超期": DANGER,
    "在用": SUCCESS,
    "维修": WARNING,
    "报废": TEXT_SECONDARY,
    # 药品档案启用状态
    "启用": SUCCESS,
    "停用": TEXT_SECONDARY,
    # 处方药标记
    "处方药": WARNING,
    "非处方药": SUCCESS,
    # 账号锁定
    "已锁定": WARNING,
    # 登录日志结果
    "成功": SUCCESS,
    "失败": DANGER,
}


def severity_color(level):
    return SEVERITY_COLORS.get(level, SUCCESS)


# ---------------------------------------------------------------- 颜色工具
def shade(hex_color, factor):
    """按比例加深/提亮颜色，factor > 0 加深，< 0 提亮。"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    if factor >= 0:
        r, g, b = (int(c * (1 - factor)) for c in (r, g, b))
    else:
        k = -factor
        r, g, b = (int(c + (255 - c) * k) for c in (r, g, b))
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def mix(color_a, color_b, ratio=0.5):
    """线性混合两色，ratio 为 color_b 的占比（0~1）。"""
    ratio = min(max(ratio, 0.0), 1.0)
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    parts = []
    for index in (0, 2, 4):
        first, second = int(a[index:index + 2], 16), int(b[index:index + 2], 16)
        parts.append(int(first + (second - first) * ratio))
    return "#{:02X}{:02X}{:02X}".format(*parts)


def hover(color):
    """悬停态：背景加深 8%。"""
    return shade(color, 0.08)


def active(color):
    """按下态：背景加深 15%。"""
    return shade(color, 0.15)


def tint(color, ratio=0.86):
    """向白色提亮，用于浅底（状态胶囊、强调底纹）。"""
    return shade(color, -ratio)


def stripe(color, ratio=0.95):
    """极浅底纹：表格斑马纹 / 分区底色，保留模块色调但不干扰阅读。"""
    return mix(color, SURFACE_CARD, ratio)


def readable_on(background):
    """在给定底色上取可读前景色（深底白字、浅底深字）。"""
    background = background.lstrip("#")
    r, g, b = (int(background[i:i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return TEXT_ON_PRIMARY if luminance < 0.62 else TEXT_PRIMARY


# ---------------------------------------------------------------- 派生色
# 预计算常用交互色，避免每次构建控件时重复换算
PRIMARY_HOVER = hover(PRIMARY)
PRIMARY_ACTIVE = active(PRIMARY)
SECONDARY_HOVER = hover(SECONDARY)
SECONDARY_ACTIVE = active(SECONDARY)
SUCCESS_HOVER = hover(SUCCESS)
WARNING_HOVER = hover(WARNING)
DANGER_HOVER = hover(DANGER)
DANGER_ACTIVE = active(DANGER)
GHOST_HOVER = shade(SURFACE_MUTED, 0.06)
GHOST_ACTIVE = shade(SURFACE_MUTED, 0.12)
BORDER_HOVER = shade(BORDER, 0.06)


# ---------------------------------------------------------------- 全局应用
def apply_theme():
    """启动时调用：浅色外观 + 中文字体。"""
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")