# -*- coding: utf-8 -*-
"""动态看板：综合看板（指标卡 + 四张统计图表）与统一预警看板两个页面。

统计口径全部由 dashboard_service 提供，界面只负责呈现；
图表使用 matplotlib 嵌入，未安装时降级为文字摘要。
"""

import customtkinter as ctk

import config
from services import dashboard_service, excel_service, personnel_service
from ui import theme
from ui.widgets import (DataTable, DynamicButton, filter_label, info,
                        page_header, warn)

try:
    import matplotlib

    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    matplotlib.rcParams["font.sans-serif"] = [config.FONT_FAMILY,
                                              config.FONT_FAMILY_FALLBACK]
    matplotlib.rcParams["axes.unicode_minus"] = False
    HAS_MPL = True
except Exception:                                      # noqa: BLE001 缺依赖时降级
    HAS_MPL = False

# 统计图统一色板：模块辅助色 + 语义色，保证多图之间色调一致
_PIE_COLORS = theme.CHART_PALETTE
_TIME_RANGES = {"近 7 天": 7, "近 30 天": 30, "近 90 天": 90}
# 图表一次拉取全部分组（分组数量很小），再在界面侧做 Top-N + 「其他」聚合，
# 避免服务层直接 LIMIT 截断导致总量信息丢失、图形看不全。
_CHART_FETCH_LIMIT = 200


# ---------------------------------------------------------------- 小工具
def _clickable(widget, command):
    """让整块卡片连同其子控件都响应左键点击，并切换手型光标。

    Tk 的事件只投递给光标下的最底层控件，不会冒泡到父控件，
    因此必须遍历卡片内所有子控件逐个绑定，点文字处才能触发跳转。
    """
    widget.bind("<Button-1>", lambda _event=None: command())
    widget.configure(cursor="hand2")
    for child in widget.winfo_children():
        _clickable(child, command)


def _metric_card(parent, column, label, value, color, hint=None, command=None):
    # 6 张卡必须用 grid + uniform 等宽铺排：pack 的 expand 在总宽超出容器时
    # 会把末尾卡片直接裁掉（曾导致「红色预警总数」整卡不可见）。
    # width 显式给小值，否则 CTkFrame 默认请求 200px，6 张合计超过容器宽度。
    card = ctk.CTkFrame(parent, width=150, fg_color=theme.SURFACE_CARD,
                        corner_radius=theme.RADIUS_CARD,
                        border_width=1, border_color=theme.BORDER_LIGHT)
    card.grid(row=0, column=column, sticky="nsew",
              padx=(0 if column == 0 else theme.GAP, 0))
    # 顶部强调条取指标自身色调，多块指标卡形成渐次色谱
    ctk.CTkFrame(card, height=theme.ACCENT_BAR, corner_radius=0,
                 fg_color=color).pack(fill="x")
    ctk.CTkLabel(card, text=str(value), font=theme.FONT_METRIC,
                 text_color=color).pack(anchor="w", padx=theme.PAD_CARD, pady=(6, 0))
    ctk.CTkLabel(card, text=label, font=theme.FONT_SMALL,
                 text_color=theme.TEXT_SECONDARY).pack(anchor="w", padx=theme.PAD_CARD,
                                                       pady=(0, 2 if hint else 6))
    if hint:
        ctk.CTkLabel(card, text=hint, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w",
                                                           padx=theme.PAD_CARD,
                                                           pady=(0, 6))
    if command is not None:
        _clickable(card, command)


def _palette_colors(count):
    """按图表色板循环取色，让同类柱形呈现多色调而不杂乱。"""
    return [theme.CHART_PALETTE[index % len(theme.CHART_PALETTE)]
            for index in range(count)]


def _top_items(data, limit, other_label="其他"):
    """按数量降序保留前 limit 项，其余合并为「其他」。

    分类（单位 / 岗位 / 异常项）过多时，坐标轴标签会相互重叠并被裁切，
    这里做 Top-N 聚合，既保证图形完整可读，又不会丢失总量信息。
    """
    ordered = sorted(data, key=lambda item: item[1], reverse=True)
    if len(ordered) <= limit:
        return ordered
    rest = sum(count for _label, count in ordered[limit:])
    return ordered[:limit] + [(other_label, rest)]


def _short(label, limit=8):
    """截断过长的中文名，避免坐标轴标签横向溢出遮挡邻项。"""
    text = str(label)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _option_menu(parent, values, width=112):
    accent = theme.active_accent()
    widget = ctk.CTkOptionMenu(
        parent, values=values, width=width, height=34, font=theme.FONT_BODY,
        fg_color=accent, button_color=theme.hover(accent),
        button_hover_color=theme.active(accent),
        dropdown_fg_color=theme.SURFACE_CARD,
        dropdown_text_color=theme.TEXT_PRIMARY)
    return widget


def _empty_axes(ax, text="暂无数据"):
    """无数据时清空坐标轴并居中提示。"""
    ax.clear()
    ax.axis("off")
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=11,
            color=theme.TEXT_SECONDARY, transform=ax.transAxes)


def _finish_axes(ax, title=None, legend=False):
    # 标题默认不画：卡片头部已有同名标题，图表内再画一遍既重复又挤占本就有限的绘图区
    if title:
        ax.set_title(title, fontsize=11, color=theme.TEXT_PRIMARY, pad=8)
    ax.tick_params(labelsize=8, colors=theme.TEXT_SECONDARY)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(theme.BORDER)
    ax.grid(axis="y", color=theme.BORDER, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)
    if legend:
        ax.legend(fontsize=8, frameon=False)


# ================================================================ 综合看板
class DashboardPage(ctk.CTkFrame):
    """指标卡 + 四张统计图表，支持单位 / 人员类型 / 时间段过滤与自动刷新。"""

    TITLE = "综合看板"
    DESC = ("在平台人数与三类人员分布、房间占用率、红色预警总数；"
            "单位分布、健康异常构成、近 30 天流动趋势与内部人员在岗图。")

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self._axes = {}
        self._timer = None
        self._build()

    # ------------------------------------------------------------ 界面
    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        self.metrics = ctk.CTkFrame(self, fg_color="transparent")
        self.metrics.pack(fill="x", pady=(theme.GAP, 0))

        self._build_filters()
        self._build_charts()
        self.load_data()
        self._schedule_refresh()

    def _build_filters(self):
        filters = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))

        filter_label(filters, "所属单位").pack(side="left", padx=(theme.PAD_CARD, 6),
                                              pady=12)
        self.unit_menu = _option_menu(filters, ["全部"] + personnel_service.distinct_units(),
                                      width=150)
        self.unit_menu.pack(side="left")

        filter_label(filters, "人员类型").pack(side="left", padx=(16, 6))
        self.type_menu = _option_menu(filters, ["全部"] + list(config.PERSON_TYPES))
        self.type_menu.pack(side="left")

        filter_label(filters, "时间段").pack(side="left", padx=(16, 6))
        self.range_menu = _option_menu(filters, list(_TIME_RANGES), width=104)
        self.range_menu.pack(side="left")

        DynamicButton(filters, text="刷新", style="primary", width=84,
                      command=self.load_data).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_filters).pack(side="left")

        self.refresh_hint = ctk.CTkLabel(
            filters, text=f"每 {config.DASHBOARD_REFRESH_SECONDS} 秒自动刷新",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        self.refresh_hint.pack(side="right", padx=(0, theme.PAD_CARD))

    def _build_charts(self):
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        for index in range(2):
            grid.rowconfigure(index, weight=1)
            grid.columnconfigure(index, weight=1)

        self._chart_unit = self._chart_cell(grid, 0, 0, "单位分布（在平台人员）")
        self._chart_health = self._chart_cell(grid, 0, 1, "健康异常构成")
        self._chart_flow = self._chart_cell(grid, 1, 0, "流动趋势（上 / 下平台）")
        self._chart_internal = self._chart_cell(grid, 1, 1, "内部人员在岗分布",
                                                toggle=self._switch_internal)
        self.internal_by = "unit"

    def _chart_cell(self, parent, row, column, title, toggle=None):
        card = ctk.CTkFrame(parent, fg_color=theme.SURFACE_CARD,
                            corner_radius=theme.RADIUS_CARD)
        card.grid(row=row, column=column, sticky="nsew",
                  padx=(0, theme.GAP) if column == 0 else (0, 0),
                  pady=(0, theme.GAP) if row == 0 else (0, 0))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=theme.PAD_CARD, pady=(8, 0))
        ctk.CTkFrame(head, width=4, height=16, corner_radius=2,
                     fg_color=theme.SECONDARY).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(head, text=title, font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY).pack(side="left")
        if toggle is not None:
            self.internal_toggle = ctk.CTkSegmentedButton(
                head, values=["按单位", "按岗位"], font=theme.FONT_SMALL, height=26,
                selected_color=theme.SECONDARY, unselected_color=theme.SURFACE_MUTED,
                selected_hover_color=theme.hover(theme.SECONDARY),
                unselected_hover_color=theme.ROW_HOVER,
                text_color=theme.TEXT_PRIMARY, command=toggle)
            self.internal_toggle.set("按单位")
            self.internal_toggle.pack(side="right")

        holder = ctk.CTkFrame(card, fg_color="transparent")
        holder.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        if not HAS_MPL:
            ctk.CTkLabel(holder, text="未安装 matplotlib，图表不可用（统计数据可在预警看板查看）",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(
                pady=30)
            return None

        # 用约束布局（constrained layout）而非 tight_layout：图表卡高度随窗口变化，
        # tight_layout 只在调用那一刻按当时尺寸算一次边距，画布随后被拉伸时
        # 旋转标签仍会溢出被裁；约束布局在每次重绘按真实尺寸重新求解，标签始终完整。
        figure = Figure(figsize=(5.0, 2.3), dpi=96, facecolor=theme.SURFACE_CARD,
                        layout="constrained")
        axes = figure.add_subplot(111)
        canvas = FigureCanvasTkAgg(figure, master=holder)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._axes[title] = (figure, axes, canvas)
        return title

    # ------------------------------------------------------------ 数据
    def reset_filters(self):
        self.unit_menu.set("全部")
        self.type_menu.set("全部")
        self.range_menu.set("近 30 天")
        self.load_data()

    def _scope(self):
        unit = self.unit_menu.get()
        person_type = self.type_menu.get()
        return (None if unit in ("", "全部") else unit,
                None if person_type == "全部" else person_type)

    def load_data(self):
        unit, person_type = self._scope()
        self._render_metrics(unit, person_type)
        self._draw_unit(unit, person_type)
        self._draw_health()
        self._draw_flow()
        self._draw_internal()
        self._update_hint()

    def refresh_auto(self):
        """自动刷新入口：图表重绘后重新排程。"""
        self.load_data()
        self._schedule_refresh()

    def _schedule_refresh(self):
        self._cancel_timer()
        self._timer = self.after(config.DASHBOARD_REFRESH_SECONDS * 1000,
                                 self.refresh_auto)

    def _cancel_timer(self):
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except Exception:                          # noqa: BLE001 窗口已销毁
                pass
            self._timer = None

    def destroy(self):
        self._cancel_timer()
        super().destroy()

    def _update_hint(self):
        import datetime

        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.refresh_hint.configure(
            text=f"每 {config.DASHBOARD_REFRESH_SECONDS} 秒自动刷新｜最近刷新 {stamp}")

    # ------------------------------------------------------------ 指标卡
    def _render_metrics(self, unit, person_type):
        for child in self.metrics.winfo_children():
            child.destroy()
        data = dashboard_service.overview_metrics(unit=unit, person_type=person_type)
        # 三类人员指标卡可点击：直接跳到对应的人员台账页，省去左侧导航层层展开
        cards = [
            ("在平台人数", data["onboard"], theme.PRIMARY, None, None),
            ("内部人员", data["internal"], theme.SECONDARY, None, "onboard.internal"),
            ("外协人员", data["outsource"], theme.SECONDARY, None, "onboard.outsource"),
            ("甲方人员", data["party"], theme.SECONDARY, None, "onboard.party"),
            ("房间占用率", f"{data['room_rate']}%", theme.SUCCESS,
             f"{data['bed_used']}/{data['bed_total']} 床位", None),
            ("红色预警总数", data["red_total"],
             theme.DANGER if data["red_total"] else theme.SUCCESS, None, None),
        ]
        # 等宽铺排：uniform 让 6 列宽度一致，sticky 让各卡拉伸到同一行高
        for column in range(len(cards)):
            self.metrics.columnconfigure(column, weight=1, uniform="metric")
        for column, (label, value, color, hint, page) in enumerate(cards):
            command = (lambda key=page: self.app.select_page(key)) if page else None
            _metric_card(self.metrics, column, label, value, color, hint,
                         command=command)

    # ------------------------------------------------------------ 图表绘制
    def _draw_unit(self, unit, person_type):
        item = self._axes.get(self._chart_unit)
        if not item:
            return
        figure, axes, canvas = item
        data = dashboard_service.unit_distribution(unit=unit, person_type=person_type,
                                                   limit=_CHART_FETCH_LIMIT)
        if not data:
            _empty_axes(axes)
            canvas.draw_idle()
            return
        data = _top_items(data, 8)
        labels = [_short(label, 8) for label, _count in data]
        values = [count for _label, count in data]
        axes.clear()
        axes.bar(range(len(labels)), values, color=_palette_colors(len(labels)),
                 width=0.6)
        for index, value in enumerate(values):
            axes.text(index, value, str(value), ha="center", va="bottom", fontsize=7,
                      color=theme.TEXT_SECONDARY)
        _finish_axes(axes)
        # 分类较多时旋转 35° 并缩小字号，避免长中文单位名重叠或被底部裁切
        axes.set_xticks(range(len(labels)))
        axes.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
        canvas.draw_idle()

    def _draw_health(self):
        item = self._axes.get(self._chart_health)
        if not item:
            return
        figure, axes, canvas = item
        data = dashboard_service.health_composition()
        if not data:
            _empty_axes(axes, "暂无健康异常")
            canvas.draw_idle()
            return
        data = _top_items(data, 6)
        labels = [_short(label, 8) for label, _count in data]
        values = [count for _label, count in data]
        colors = list(_PIE_COLORS)[:len(values)]
        axes.clear()
        axes.axis("on")
        wedges, _texts, autotexts = axes.pie(
            values, autopct="%1.0f%%", startangle=90, colors=colors,
            textprops={"fontsize": 7, "color": theme.TEXT_PRIMARY})
        # 深色扇区上的百分比改用白字，浅色扇区保持深字，保证任何配色下都清晰
        for text, color in zip(autotexts, colors):
            text.set_color(theme.readable_on(color))
        axes.set_aspect("equal")
        # 图表区高度有限，分类名放到右侧图例，避免外置标签被上下边界裁切
        axes.legend(wedges, [f"{label} {value}" for label, value in zip(labels, values)],
                    loc="center left", bbox_to_anchor=(0.98, 0.5), fontsize=7,
                    frameon=False, labelcolor=theme.TEXT_PRIMARY)
        canvas.draw_idle()

    def _draw_flow(self):
        item = self._axes.get(self._chart_flow)
        if not item:
            return
        figure, axes, canvas = item
        days = _TIME_RANGES.get(self.range_menu.get(), config.DASHBOARD_FLOW_DAYS)
        trend = dashboard_service.flow_trend(days=days)
        axes.clear()
        axes.plot(trend["labels"], trend["checkin"], color=theme.SECONDARY,
                  linewidth=1.6, label="上平台")
        axes.plot(trend["labels"], trend["leave"], color=theme.WARNING,
                  linewidth=1.6, label="下平台")
        step = max(len(trend["labels"]) // 8, 1)
        axes.set_xticks(range(0, len(trend["labels"]), step))
        axes.set_xticklabels(trend["labels"][::step], rotation=0)
        _finish_axes(axes, legend=True)
        canvas.draw_idle()

    def _switch_internal(self, value):
        self.internal_by = "post" if value == "按岗位" else "unit"
        self._draw_internal()

    def _draw_internal(self):
        item = self._axes.get(self._chart_internal)
        if not item:
            return
        figure, axes, canvas = item
        data = dashboard_service.internal_onboard(by=self.internal_by,
                                                  limit=_CHART_FETCH_LIMIT)
        if not data:
            _empty_axes(axes, "暂无内部人员在岗数据")
            canvas.draw_idle()
            return
        data = _top_items(data, 10)
        labels = [_short(label, 12) for label, _count in data][::-1]
        values = [count for _label, count in data][::-1]
        axes.clear()
        axes.barh(range(len(labels)), values, color=_palette_colors(len(labels)),
                  height=0.6)
        for index, value in enumerate(values):
            axes.text(value, index, f" {value}", va="center", fontsize=7,
                      color=theme.TEXT_SECONDARY)
        _finish_axes(axes)
        axes.grid(axis="y", visible=False)
        axes.grid(axis="x", color=theme.BORDER, linewidth=0.6, alpha=0.6)
        # 缩小分类标签字号，分类较多时也不至于挤占柱形绘图区
        axes.set_yticks(range(len(labels)))
        axes.set_yticklabels(labels, fontsize=7)
        canvas.draw_idle()


# ================================================================ 预警看板
class WarningListPage(ctk.CTkFrame):
    """多来源预警统一聚合：按级别 / 来源 / 单位筛选，支持一键导出。"""

    TITLE = "预警看板"
    DESC = ("住井超期、健康异常、体检到期、药品效期与库存、设备维保五类预警"
            "统一聚合，红色优先排序，可按级别 / 来源 / 单位筛选并导出。")

    # 1366×768 小屏下实测表格行区可用宽度约 966px（列宽合计 + 每列 4px 间距须 ≤ 966）：
    # 「对象」与「编码 / 编号」合并为一列，加入 4 项关联人员信息后共 9 列，
    # 列宽按实测最长内容反推（如「王建国 / P20260001」158px → 158，
    # 「13800000000」110px → 110），合计 944px，保留约 20px 余量防字体回退撑宽。
    COLUMNS = [
        {"key": "level", "title": "级别", "width": 76, "tag": True, "level_key": "level"},
        {"key": "source", "title": "来源", "width": 72},
        {"key": "target_code", "title": "对象 / 工号", "width": 158},
        {"key": "person_type", "title": "人员类型", "width": 76},
        {"key": "post", "title": "岗位 / 工种", "width": 88},
        {"key": "phone", "title": "联系电话", "width": 110},
        {"key": "unit", "title": "所属单位", "width": 102},
        {"key": "resource", "title": "房间 / 救生艇", "width": 106},
        {"key": "detail", "title": "预警详情", "width": 120},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.rows = []
        self._build()
        self.load_data()

    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        self.metrics = ctk.CTkFrame(self, fg_color="transparent")
        self.metrics.pack(fill="x", pady=(theme.GAP, 0))

        filters = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))
        filter_label(filters, "级别").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.level_menu = _option_menu(
            filters, ["全部"] + list(config.DASHBOARD_WARNING_LEVELS), width=104)
        self.level_menu.pack(side="left")

        filter_label(filters, "来源").pack(side="left", padx=(16, 6))
        self.source_menu = _option_menu(
            filters, ["全部"] + list(config.DASHBOARD_WARNING_SOURCES), width=112)
        self.source_menu.pack(side="left")

        filter_label(filters, "所属单位").pack(side="left", padx=(16, 6))
        self.unit_menu = _option_menu(
            filters, ["全部"] + personnel_service.distinct_units(), width=150)
        self.unit_menu.pack(side="left")

        DynamicButton(filters, text="查询", style="primary", width=84,
                      command=self.load_data).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_filters).pack(side="left")

        if self.user.can("dashboard.view"):
            DynamicButton(filters, text="导出预警", style="secondary", width=100,
                          command=self.export_warnings).pack(side="right",
                                                              padx=(0, theme.PAD_CARD))

        self.table = DataTable(self, self.COLUMNS, page_size=30)
        self.table.pack(fill="both", expand=True, pady=(theme.GAP, 0))

    def reset_filters(self):
        self.level_menu.set("全部")
        self.source_menu.set("全部")
        self.unit_menu.set("全部")
        self.load_data()

    def load_data(self):
        level = self.level_menu.get()
        source = self.source_menu.get()
        unit = self.unit_menu.get()
        self.rows = dashboard_service.unified_warnings(
            level=None if level in ("", "全部") else level,
            source=None if source in ("", "全部") else source,
            unit=None if unit in ("", "全部") else unit)
        self.table.set_data(self.rows)
        self._refresh_metrics()

    def _refresh_metrics(self):
        for child in self.metrics.winfo_children():
            child.destroy()
        counts = {"红色报警": 0, "黄色预警": 0, "提示": 0}
        for item in self.rows:
            if item["level"] in counts:
                counts[item["level"]] += 1
        cards = [("红色报警", counts["红色报警"], theme.DANGER),
                 ("黄色预警", counts["黄色预警"], theme.WARNING),
                 ("提示", counts["提示"], theme.SECONDARY),
                 ("预警合计", len(self.rows), theme.PRIMARY)]
        for column in range(len(cards)):
            self.metrics.columnconfigure(column, weight=1, uniform="metric")
        for column, (label, value, color) in enumerate(cards):
            _metric_card(self.metrics, column, label, value, color)

    def export_warnings(self):
        if not self.rows:
            warn(self, "当前没有可导出的预警记录", "提示")
            return
        path = excel_service.export_table("预警看板", "预警看板",
                                          config.DASHBOARD_EXPORT_COLUMNS, self.rows)
        info(self, f"已导出 {len(self.rows)} 条预警：\n{path}", "导出完成")