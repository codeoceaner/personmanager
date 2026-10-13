# -*- coding: utf-8 -*-
"""主窗口：顶部工具栏 + 左侧两级折叠导航 + 三段式主内容区 + 底部状态栏。"""

import customtkinter as ctk

import config
from db import database
from services import dashboard_service, personnel_service
from ui import theme
from ui.about_frame import AboutPage
from ui.dashboard_frame import DashboardPage, WarningListPage
from ui.data_frame import DataPage
from ui.health_frame import (EquipmentUsePage, HealthProfilePage, MedicationPage,
                             MonitorPage)
from ui.login_window import ChangePasswordDialog
from ui.onboard_frame import CategoryPage, LeavePage, RegisterPage
from ui.settings_frame import SystemSettingsPage
from ui.supply_frame import (EquipmentLedgerPage, MedicineStockPage,
                             SupplyWarningPage)
from ui.widgets import Badge, DynamicButton

# 带预警角标的导航分组：key → 角标级别来源（dashboard_service.badge_counts）
BADGE_GROUPS = ("dashboard", "supply")

# 左侧导航栏宽度可拖拽调整，并持久化到系统配置表（重启后保持上次宽度）
NAV_WIDTH_KEY = "nav_width"
NAV_WIDTH_MIN = 170
NAV_WIDTH_MAX = 420
# 专注显示（综合看板全屏）时固定收起的页面
FOCUS_PAGE = "dashboard.overview"

# 已实现的业务页
PAGE_CLASSES = {
    "dashboard.overview": DashboardPage,
    "dashboard.warning": WarningListPage,
    "onboard.register": RegisterPage,
    "onboard.leave": LeavePage,
    "onboard.internal": lambda master, app: CategoryPage(master, app, "内部人员"),
    "onboard.outsource": lambda master, app: CategoryPage(master, app, "外协人员"),
    "onboard.party": lambda master, app: CategoryPage(master, app, "甲方人员"),
    "health.profile": HealthProfilePage,
    "health.monitor": MonitorPage,
    "health.medicine": MedicationPage,
    "health.equipment": EquipmentUsePage,
    "supply.medicine": MedicineStockPage,
    "supply.equipment": EquipmentLedgerPage,
    "supply.warning": SupplyWarningPage,
    "system.settings": SystemSettingsPage,
    "data.manage": DataPage,
    "about.author": AboutPage,
}

# ---------------------------------------------------------------- 导航结构
# perm 为展示所需权限，None 表示对所有登录用户可见；无权限的分组 / 条目直接不渲染
NAV_TREE = [
    {
        "key": "onboard", "label": "人员登离管理", "perm": "personnel.view",
        "children": [
            ("onboard.register", "人员登记", "personnel.create"),
            ("onboard.leave", "人员离开", "personnel.view"),
            ("onboard.internal", "内部人员", "personnel.view"),
            ("onboard.outsource", "外协人员", "personnel.view"),
            ("onboard.party", "甲方人员", "personnel.view"),
        ],
    },
    {
        "key": "health", "label": "健康管理", "perm": "health.view",
        "children": [
            ("health.profile", "健康档案", "health.view"),
            ("health.monitor", "日常监测", "check.view"),
            ("health.medicine", "药品管理", "medicine.view"),
            ("health.equipment", "医疗设备管理", "equipment.view"),
        ],
    },
    {
        "key": "supply", "label": "医疗物资管理", "perm": "supply.view",
        "children": [
            ("supply.medicine", "药品库存台账", "supply.view"),
            ("supply.equipment", "医疗设备台账", "equipment.view"),
            ("supply.warning", "效期与库存预警", "supply.view"),
        ],
    },
    {
        "key": "dashboard", "label": "动态看板", "perm": "dashboard.view",
        "children": [
            ("dashboard.overview", "综合看板", "dashboard.view"),
            ("dashboard.warning", "预警看板", "dashboard.view"),
        ],
    },
    {
        "key": "data", "label": "数据管理", "perm": "data.manage",
        "children": [
            ("data.manage", "导入 / 导出 / 备份", "data.manage"),
        ],
    },
    {
        "key": "about", "label": "关于软件", "perm": None,
        "children": [
            ("about.author", "作者信息", None),
        ],
    },
]


class MainWindow(ctk.CTkFrame):
    def __init__(self, master, user, on_logout):
        super().__init__(master, fg_color=theme.SURFACE_FORM, corner_radius=0)
        self.user = user
        self.on_logout = on_logout

        self.nav_buttons = {}
        self.nav_badges = {}
        self.nav_accents = {}
        self.group_frames = {}
        self.active_page = None
        self.focus_mode = False        # 综合看板专注显示：自动收起左侧导航
        self.sidebar_hidden = False    # 工具栏「隐藏菜单」手动收起左侧导航
        self._split_origin = 0         # 拖拽分隔条时的导航栏左边缘坐标
        self._split_motion_id = None   # 拖拽期间临时注册的全局移动绑定
        self._split_release_id = None  # 拖拽期间临时注册的全局松手绑定

        self._build_toolbar()
        # 状态栏必须先于主体 pack：主体 fill=both/expand 会占满空间，
        # 后 pack 的 side="bottom" 状态栏会被挤出（内容较高的页面尤其明显）。
        self._build_statusbar()
        self._build_body()

        self.select_page(self._first_page(), from_nav=False)
        self.refresh_status()

    # ------------------------------------------------------------ 顶部工具栏
    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=56)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # 工具栏底部多色调细条：五段模块辅助色等分，弱化但一眼可辨
        strip = ctk.CTkFrame(self, fg_color="transparent", height=theme.ACCENT_BAR)
        strip.pack(fill="x")
        for color in theme.MODULE_STRIP:
            ctk.CTkFrame(strip, fg_color=color, corner_radius=0,
                         height=theme.ACCENT_BAR).pack(side="left", fill="x",
                                                       expand=True)

        ctk.CTkLabel(bar, text=config.APP_SHORT_NAME, font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(side="left", padx=(18, 0))
        ctk.CTkLabel(bar, text=f"V{config.APP_VERSION}", font=theme.FONT_SMALL,
                     text_color=theme.NAV_TEXT).pack(side="left", padx=(8, 0))

        # 左侧目录显示 / 隐藏开关：始终可见，随时收起或展开侧边栏
        self.menu_button = DynamicButton(bar, text="◀ 隐藏菜单", style="ghost",
                                         width=104, height=32,
                                         command=self.toggle_sidebar)
        self.menu_button.pack(side="left", padx=(16, 0))

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=16)

        DynamicButton(right, text="刷新", style="secondary", width=74, height=32,
                      command=self.refresh_status).pack(side="right", padx=(10, 0))

        self.user_menu = ctk.CTkOptionMenu(
            right, values=["账号操作", "修改密码", "退出登录"], width=104, height=32,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY,
            command=self._on_user_menu)
        self.user_menu.pack(side="right")

        ctk.CTkLabel(right, text=f"当前用户：{self.user.username}"
                                 f"（{self.user.role_label}）",
                     font=theme.FONT_BODY,
                     text_color=theme.TEXT_ON_PRIMARY).pack(side="right", padx=(0, 12))

        if self.user.can("config.manage"):
            DynamicButton(right, text="系统设置", style="ghost", width=92, height=32,
                          command=lambda: self.select_page("system.settings",
                                                           from_nav=False)).pack(
                side="right", padx=(0, 10))

    # ------------------------------------------------------------ 导航 + 内容
    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.PAD_WINDOW,
                  pady=(theme.PAD_WINDOW, 6))
        self.body = body

        self._nav_width = self._stored_nav_width()
        self.nav = ctk.CTkScrollableFrame(body, width=self._nav_width,
                                          fg_color=theme.NAV_BG, corner_radius=theme.RADIUS_CARD)
        self.nav.pack(side="left", fill="y")

        # 导航栏与内容区之间的拖拽分隔条：按住左右拖动即可调整左侧目录宽度
        self.splitter = ctk.CTkFrame(body, width=6, corner_radius=2,
                                     fg_color=theme.BORDER,
                                     cursor="sb_h_double_arrow")
        self.splitter.pack(side="left", fill="y", padx=(4, 0))
        self.splitter.bind("<ButtonPress-1>", self._on_split_press)

        self.content = ctk.CTkFrame(body, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True,
                          padx=(theme.PAD_WINDOW, 0))

        self._build_nav()
        # 初始排布与按钮文案统一交给可见性逻辑，避免 pack 顺序与状态不一致
        self._apply_nav_visibility()

    # ------------------------------------------------------------ 目录宽度调整
    def _stored_nav_width(self):
        """读取上次保存的导航栏宽度（越界值自动收敛到允许区间）。"""
        return max(NAV_WIDTH_MIN,
                   min(NAV_WIDTH_MAX, database.get_int(NAV_WIDTH_KEY, theme.NAV_WIDTH)))

    def _nav_width_limit(self):
        """右侧内容区需保留最小可用宽度，导航栏不能无限拉宽。"""
        room = self.body.winfo_width() - 560
        return max(NAV_WIDTH_MIN, min(NAV_WIDTH_MAX, room))

    def _on_split_press(self, _event=None):
        # 记录导航栏左边缘：拖动时「鼠标 x − 左边缘」即为新的导航栏宽度
        self._split_origin = self.nav.winfo_rootx()
        # 抢占鼠标：拖到分隔条之外再松手也能收到 Release，宽度才不会漏存
        self.splitter.grab_set()
        # 拖拽期间在顶层窗口上监听移动与松手。
        # customtkinter 的 CTkFrame 把事件绑定挂在内部 canvas 上，而 grab_set
        # 会把指针事件转交给外层 frame，canvas 绑定此后收不到 <B1-Motion> /
        # <ButtonRelease-1>（表现就是拖动完全没反应）。顶层窗口存在于所有子控件
        # 的 bindtags 中，无论事件最终落到哪个控件都能收到，左右拖动都可靠。
        top = self.winfo_toplevel()
        self._split_motion_id = top.bind("<B1-Motion>", self._on_split_drag, add="+")
        self._split_release_id = top.bind("<ButtonRelease-1>", self._on_split_release,
                                          add="+")

    def _on_split_drag(self, event):
        self._set_nav_width(event.x_root - self._split_origin)

    def _on_split_release(self, _event=None):
        top = self.winfo_toplevel()
        if self._split_motion_id is not None:
            top.unbind("<B1-Motion>", self._split_motion_id)
            self._split_motion_id = None
        if self._split_release_id is not None:
            top.unbind("<ButtonRelease-1>", self._split_release_id)
            self._split_release_id = None
        self.splitter.grab_release()
        # 松手才落库：拖动过程中不频繁写配置缓存与数据库
        database.set_config(NAV_WIDTH_KEY, self._nav_width, "左侧导航栏宽度")

    def _set_nav_width(self, width):
        width = max(NAV_WIDTH_MIN, min(self._nav_width_limit(), int(width)))
        if width == self._nav_width:
            return
        self._nav_width = width
        self.nav.configure(width=width)

    def _build_nav(self):
        ctk.CTkLabel(self.nav, text="功能导航", font=theme.FONT_NAV_GROUP,
                     text_color=theme.TEXT_ON_PRIMARY).pack(anchor="w", padx=16, pady=(14, 8))

        for group in NAV_TREE:
            if not self._visible(group["perm"]):
                continue
            children = [(key, label, perm) for key, label, perm in group["children"]
                        if self._visible(perm)]
            if not children:
                continue
            self._build_nav_group(group, children)

    def _visible(self, perm):
        """perm 为 None 表示对所有登录用户可见（如「作者信息」）。"""
        return perm is None or self.user.can(perm)

    def _build_nav_group(self, group, children):
        # 分组标题行：模块色调标题按钮 + 预警角标（看板 / 物资管理两组实时显示条数）
        accent = theme.module_color(group["key"])
        row = ctk.CTkFrame(self.nav, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(6, 2))

        header = ctk.CTkButton(
            row, text=f"▾  {group['label']}", anchor="w", height=38,
            corner_radius=theme.RADIUS_BUTTON,
            fg_color=theme.mix(theme.NAV_GROUP_BG, accent, 0.32),
            hover_color=theme.mix(theme.NAV_ITEM_HOVER, accent, 0.30),
            text_color=theme.TEXT_ON_PRIMARY, font=theme.FONT_NAV_GROUP,
            command=lambda k=group["key"]: self._toggle_group(k))
        header.pack(side="left", fill="x", expand=True)

        if group["key"] in BADGE_GROUPS:
            badge = Badge(row, count=0)
            badge.pack(side="right", padx=(0, 8))
            self.nav_badges[group["key"]] = badge

        holder = ctk.CTkFrame(self.nav, fg_color="transparent")
        holder.pack(fill="x")
        self.group_frames[group["key"]] = {"holder": holder, "header": header,
                                           "row": row, "label": group["label"],
                                           "open": True}

        for key, label, _perm in children:
            btn = ctk.CTkButton(
                holder, text=f"     {label}", anchor="w", height=34,
                corner_radius=theme.RADIUS_BUTTON, fg_color="transparent",
                hover_color=theme.mix(theme.NAV_ITEM_HOVER, accent, 0.30),
                text_color=theme.NAV_TEXT, font=theme.FONT_NAV,
                command=lambda k=key: self.select_page(k))
            btn.pack(fill="x", padx=8, pady=1)
            self.nav_buttons[key] = btn
            self.nav_accents[key] = accent

    def _toggle_group(self, key):
        info = self.group_frames.get(key)
        if not info:
            return
        info["open"] = not info["open"]
        arrow = "▾" if info["open"] else "▸"
        info["header"].configure(text=f"{arrow}  {info['label']}")
        self._relayout_nav()

    def _relayout_nav(self):
        """按 NAV_TREE 顺序重排分组，保证展开的子项始终紧跟所属分组标题。

        Tk 的 pack 在控件被重新 pack 时会把它追加到末尾：收起再展开某组后，
        该组子项会落到导航栏最底部，看起来像挂在最后一个分组下面（曾出现
        「动态看板」下显示成人员登离管理子项的错觉），因此每次切换都统一重排。
        """
        for info in self.group_frames.values():
            info["holder"].pack_forget()
            info["row"].pack_forget()
        for group in NAV_TREE:
            info = self.group_frames.get(group["key"])
            if not info:
                continue
            info["row"].pack(fill="x", padx=8, pady=(6, 2))
            if info["open"]:
                info["holder"].pack(fill="x")

    def _first_page(self):
        for key in self.nav_buttons:
            return key
        return next(iter(PAGE_CLASSES))

    # ------------------------------------------------------------ 页面切换
    def select_page(self, page_key, from_nav=True):
        if page_key not in PAGE_CLASSES:
            return
        self.active_page = page_key

        for key, btn in self.nav_buttons.items():
            active = key == page_key
            btn.configure(fg_color=self.nav_accents.get(key, theme.NAV_ITEM_ACTIVE)
                          if active else "transparent",
                          text_color=theme.TEXT_ON_PRIMARY if active
                          else theme.NAV_TEXT)

        # 先设定模块色调，页面内标题条 / 卡片 / 表格据此取色
        theme.set_active_module(page_key.split(".")[0])
        for child in self.content.winfo_children():
            child.destroy()
        PAGE_CLASSES[page_key](self.content, self).pack(fill="both", expand=True)

        # 综合看板默认收起左侧导航，让图表铺满窗口；点工具栏「显示菜单」可随时恢复
        self._apply_focus_mode(page_key == FOCUS_PAGE)

    # ------------------------------------------------------------ 侧边栏显隐
    def _nav_hidden(self):
        """综合看板专注收起与工具栏手动收起，任一成立即不显示左侧目录。"""
        return self.focus_mode or self.sidebar_hidden

    def _apply_focus_mode(self, focus):
        """综合看板专注显示：默认收起左侧导航，让图表铺满窗口。"""
        if focus == self.focus_mode:
            return
        self.focus_mode = focus
        if focus:
            # 重新进入综合看板时恢复「自动收起」，不受上次手动展开影响
            self.sidebar_hidden = False
        self._apply_nav_visibility()

    def toggle_sidebar(self):
        """工具栏按钮：显示 / 隐藏左侧目录。"""
        if self._nav_hidden():
            self.focus_mode = False
            self.sidebar_hidden = False
        else:
            self.sidebar_hidden = True
        self._apply_nav_visibility()

    def _apply_nav_visibility(self):
        """按当前状态收起或展开左侧目录，并同步工具栏按钮文案。"""
        if self._nav_hidden():
            self.nav.pack_forget()
            self.splitter.pack_forget()
            self.content.pack_configure(padx=(0, 0))
            self.menu_button.configure(text="▶ 显示菜单")
            return
        # 恢复导航：pack 顺序决定左右位置，必须按 导航 → 分隔条 → 内容 依次插回
        self.nav.pack(side="left", fill="y", before=self.content)
        self.splitter.pack(side="left", fill="y", padx=(4, 0), before=self.content)
        self.content.pack_configure(padx=(theme.PAD_WINDOW, 0))
        self.menu_button.configure(text="◀ 隐藏菜单")

    # ------------------------------------------------------------ 底部状态栏
    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=theme.STATUSBAR_BG, corner_radius=0, height=30)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_user = ctk.CTkLabel(bar, text="", font=theme.FONT_SMALL,
                                        text_color=theme.TEXT_SECONDARY)
        self.status_user.pack(side="left", padx=16)

        self.status_version = ctk.CTkLabel(bar, text=f"V{config.APP_VERSION}",
                                           font=theme.FONT_SMALL,
                                           text_color=theme.TEXT_SECONDARY)
        self.status_version.pack(side="right", padx=16)

        self.status_warning_yellow = ctk.CTkLabel(
            bar, text="", font=theme.FONT_SMALL, text_color=theme.WARNING)
        self.status_warning_yellow.pack(side="right", padx=(0, 12))

        self.status_warning_red = ctk.CTkLabel(
            bar, text="", font=theme.FONT_SMALL, text_color=theme.DANGER)
        self.status_warning_red.pack(side="right", padx=(0, 12))

        self.status_onboard = ctk.CTkLabel(bar, text="", font=theme.FONT_SMALL,
                                           text_color=theme.PRIMARY)
        self.status_onboard.pack(side="right", padx=(0, 12))

    def refresh_status(self):
        """刷新状态栏与导航角标：在平台人数、全来源预警条数与角标。"""
        counts = personnel_service.summary_counts()
        # 预警条数必须与看板角标、预警列表同口径（住井超期 + 健康异常 + 体检到期
        # + 药品效期 / 库存 + 设备维保）；若只统计住井，界面显示会与库中实际预警不符。
        warnings = dashboard_service.warning_counts()
        red = warnings["红色报警"]

        self.status_user.configure(
            text=f"当前用户：{self.user.username}｜{self.user.role_label}")
        self.status_onboard.configure(text=f"● 在平台 {counts['onboard']} 人")
        self.status_warning_red.configure(text=f"● 红色报警 {red}")
        self.status_warning_yellow.configure(
            text=f"● 黄色预警 {warnings['黄色预警']}")
        self.status_warning_red.configure(
            text_color=theme.DANGER if red else theme.TEXT_SECONDARY)
        self.status_warning_yellow.configure(
            text_color=theme.WARNING if warnings["黄色预警"] else theme.TEXT_SECONDARY)

        if self.nav_badges:
            badges = dashboard_service.badge_counts()
            for key, badge in self.nav_badges.items():
                count, level = badges.get(key, (0, "红色报警"))
                badge.set_count(count, level)

    # ------------------------------------------------------------ 用户菜单
    def _on_user_menu(self, choice):
        self.user_menu.set("账号操作")
        if choice == "修改密码":
            self._change_password()
        elif choice == "退出登录":
            self.on_logout()

    def _change_password(self):
        dialog = ChangePasswordDialog(self, self.user)
        dialog.grab_set()
        self.wait_window(dialog)