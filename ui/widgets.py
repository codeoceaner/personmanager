# -*- coding: utf-8 -*-
"""公共控件：动态按钮、状态标签、预警角标、卡片容器与数据表格。

多色调约定：卡片 / 表格 / 标题条统一由 accent 参数取模块辅助色，
语义色只出现在状态胶囊与角标上，保证深色表头 + 彩色强调条的整体观感一致。
"""

from tkinter import messagebox

import customtkinter as ctk

import config
from ui import theme


# ---------------------------------------------------------------- 动态按钮
class DynamicButton(ctk.CTkButton):
    """按钮动效：悬停渐亮并描边、按下加深下沉、禁用灰化、加载中禁重复提交。

    普通按钮在悬停 / 按下时用 6 帧补间做颜色过渡（约 100ms），
    描边（outline）按钮底色透明，仅用文字与描边取色。
    """

    ANIM_STEPS = 6          # 补间帧数
    ANIM_INTERVAL = 16      # 每帧间隔（毫秒）

    STYLES = {
        "primary": (theme.PRIMARY, theme.TEXT_ON_PRIMARY),
        "secondary": (theme.SECONDARY, "#FFFFFF"),
        "success": (theme.SUCCESS, "#FFFFFF"),
        "danger": (theme.DANGER, "#FFFFFF"),
        "warning": (theme.WARNING, "#FFFFFF"),
        "info": (theme.ACCENT_INDIGO, "#FFFFFF"),
        "teal": (theme.ACCENT_TEAL, "#FFFFFF"),
        "violet": (theme.ACCENT_VIOLET, "#FFFFFF"),
        "ghost": (theme.SURFACE_MUTED, theme.TEXT_PRIMARY),
    }
    # 描边风格：style 名 → 取色
    OUTLINE_STYLES = {
        "outline": theme.PRIMARY,
        "outline_secondary": theme.SECONDARY,
        "outline_success": theme.SUCCESS,
        "outline_danger": theme.DANGER,
        "outline_warning": theme.WARNING,
    }

    def __init__(self, master, text="", command=None, style="primary",
                 width=108, height=34, accent=None, **kwargs):
        self._outline = style in self.OUTLINE_STYLES
        if self._outline:
            base = accent or self.OUTLINE_STYLES[style]
            fg = base
            super().__init__(
                master, text=text, width=width, height=height,
                corner_radius=theme.RADIUS_BUTTON,
                fg_color="transparent", hover_color=theme.tint(base, 0.86),
                border_width=1, border_color=base,
                text_color=base, text_color_disabled=theme.DISABLED_TEXT,
                font=theme.FONT_BUTTON, command=self._on_click, **kwargs)
        else:
            base, fg = self.STYLES.get(style, self.STYLES["primary"])
            super().__init__(
                master, text=text, width=width, height=height,
                corner_radius=theme.RADIUS_BUTTON,
                fg_color=base, hover_color=theme.hover(base),
                text_color=fg, text_color_disabled=theme.DISABLED_TEXT,
                font=theme.FONT_BUTTON, command=self._on_click, **kwargs)

        self._accent = accent or base
        self._base_bg = base
        self._base_fg = fg
        self._shown_bg = base
        self._command = command
        self._loading = False
        self._normal_text = text
        self._pressed = False
        self._tween_token = 0

        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

    # ---- 交互反馈
    def _on_enter(self, _event=None):
        if self._is_disabled():
            return
        self.configure(cursor="hand2")
        if self._outline:
            return
        # 悬停：渐亮并加一圈同色描边，形成轻微「抬升」
        self.configure(border_width=1, border_color=theme.mix(self._base_bg,
                                                              "#FFFFFF", 0.42))
        self._tween(theme.hover(self._base_bg))

    def _on_leave(self, _event=None):
        if self._is_disabled():
            return
        self.configure(cursor="arrow", border_width=0)
        if self._outline:
            return
        self._pressed = False
        self._tween(self._base_bg)

    def _on_press(self, _event=None):
        if self._is_disabled():
            return
        self._pressed = True
        if self._outline:
            self.configure(border_width=2, border_color=theme.active(self._accent))
            return
        # 按下：加深并加粗描边，形成「下沉」反馈
        self.configure(border_width=2, border_color=theme.active(self._base_bg))
        self._tween(theme.active(self._base_bg), steps=3)

    def _on_release(self, _event=None):
        if self._is_disabled():
            return
        # customtkinter 的 CTkButton 把「鼠标点击派发 command」这一步放在它自己的
        # _on_release 里（self._canvas.bind("<ButtonRelease-1>", self._on_release)）。
        # 子类重写该方法后，父类那份派发会被顶掉，导致鼠标点击永远不触发 command。
        # 因此这里必须自行派发一次；用 _pressed 做守卫，兼容重复绑定/重复触发。
        was_pressed = self._pressed
        self._pressed = False
        if self._outline:
            self.configure(border_width=1, border_color=self._accent)
        else:
            self.configure(border_width=1, border_color=theme.mix(self._base_bg,
                                                                  "#FFFFFF", 0.42))
            self._tween(theme.hover(self._base_bg), steps=3)
        if was_pressed:
            self._on_click()

    def _is_disabled(self):
        return str(self.cget("state")) == "disabled"

    # ---- 颜色补间
    def _cancel_tween(self):
        self._tween_token += 1

    def _tween(self, target, steps=None, interval=None):
        """把底色从当前值平滑过渡到目标色（避免悬停时颜色跳变）。"""
        self._cancel_tween()
        start = self._shown_bg
        steps = steps or self.ANIM_STEPS
        interval = interval or self.ANIM_INTERVAL
        if start == target:
            return
        frames = [theme.mix(start, target, (index + 1) / steps) for index in range(steps)]
        token = self._tween_token

        def step(index=0):
            if token != self._tween_token:
                return
            try:
                if not self.winfo_exists():
                    return
            except Exception:                        # noqa: BLE001 控件已销毁
                return
            self._shown_bg = frames[index]
            self.configure(fg_color=frames[index])
            if index + 1 < len(frames):
                self.after(interval, lambda: step(index + 1))

        step()

    def _on_click(self):
        if self._loading or self._command is None:
            return
        self._command()

    # ---- 状态控制
    def set_loading(self, loading=True, loading_text="处理中…"):
        """加载中：文字替换并禁止重复提交。"""
        if loading:
            self._loading = True
            self._cancel_tween()
            self.configure(state="disabled", text=loading_text, border_width=0,
                           fg_color=theme.DISABLED_BG)
            self._shown_bg = theme.DISABLED_BG
        else:
            self._loading = False
            self.configure(state="normal", text=self._normal_text,
                           fg_color=self._base_bg)
            self._shown_bg = self._base_bg

    def set_enabled(self, enabled=True):
        """按权限 / 业务条件动态启停按钮。"""
        self._cancel_tween()
        if enabled:
            self.configure(state="normal", fg_color=self._base_bg,
                           text_color=self._base_fg,
                           border_color=self._accent if self._outline else self._base_bg)
            self._shown_bg = self._base_bg
        else:
            if self._outline:
                self.configure(state="disabled", border_color=theme.DISABLED_BG)
            else:
                self.configure(state="disabled", fg_color=theme.DISABLED_BG)
            self._shown_bg = theme.DISABLED_BG

    def set_text(self, text):
        """运行期更新按钮文字，同时保持加载态文案正确。"""
        self._normal_text = text
        if not self._loading:
            self.configure(text=text)


# ---------------------------------------------------------------- 状态标签
class StatusTag(ctk.CTkLabel):
    """状态胶囊：浅色底 + 同色描边 + 语义色文字，仅做小面积着色。"""

    def __init__(self, master, text, level="正常", width=None, **kwargs):
        color = theme.severity_color(level)
        super().__init__(
            master, text=text,
            width=width or (len(text) * 14 + 18), height=22,
            corner_radius=theme.RADIUS_TAG,
            fg_color=theme.tint(color, 0.88), text_color=color,
            font=theme.FONT_SMALL, **kwargs)
        self._level = level

    def set_level(self, text, level):
        color = theme.severity_color(level)
        self.configure(text=text, fg_color=theme.tint(color, 0.88),
                       text_color=color, width=len(text) * 14 + 18)
        self._level = level


# ---------------------------------------------------------------- 预警角标
class Badge(ctk.CTkLabel):
    """导航项右侧的预警条数角标；数量为 0 时隐藏，计数变化时闪一下。"""

    def __init__(self, master, count=0, level="红色报警", **kwargs):
        super().__init__(master, text="", width=24, height=18,
                         corner_radius=9, font=theme.FONT_SMALL,
                         text_color="#FFFFFF", **kwargs)
        self._count = None
        self._level = level
        self._token = 0
        self.set_count(count, level)

    def set_count(self, count, level="红色报警"):
        self._level = level
        if not count:
            self._count = 0
            self._token += 1
            self.configure(text="", fg_color="transparent", width=1)
            return
        changed = self._count != count
        self._count = count
        self.configure(text=str(count) if count < 100 else "99+",
                       fg_color=theme.severity_color(level), width=24)
        if changed:
            self._flash()

    def _flash(self):
        """计数变化时用两帧高亮提示，避免用户错过预警增减。"""
        self._token += 1
        token = self._token
        color = theme.severity_color(self._level)
        bright = theme.shade(color, -0.25)

        def step(index=0):
            if token != self._token:
                return
            try:
                if not self.winfo_exists():
                    return
            except Exception:                        # noqa: BLE001 控件已销毁
                return
            self.configure(fg_color=bright if index == 0 else color)
            if index == 0:
                self.after(140, lambda: step(1))

        step()


# ---------------------------------------------------------------- 卡片容器
class Card(ctk.CTkFrame):
    """白色圆角卡片，带左侧色条标题与浅描边；内容放入 self.body。"""

    def __init__(self, master, title=None, accent=None, **kwargs):
        self.accent = accent or theme.active_accent()
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", theme.BORDER_LIGHT)
        super().__init__(master, fg_color=theme.SURFACE_CARD,
                         corner_radius=theme.RADIUS_CARD, **kwargs)
        if title:
            header = ctk.CTkFrame(self, fg_color="transparent")
            header.pack(fill="x", padx=theme.PAD_CARD, pady=(12, 6))
            ctk.CTkFrame(header, width=4, height=18, corner_radius=2,
                         fg_color=self.accent).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(header, text=title, font=theme.FONT_SUBTITLE,
                         text_color=theme.TEXT_PRIMARY).pack(side="left")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True,
                       padx=theme.PAD_CARD, pady=(4, theme.PAD_CARD))


# ---------------------------------------------------------------- 数据表格
class DataTable(ctk.CTkFrame):
    """自绘数据表格：多色调表头 + 斑马纹 + 悬停 / 选中高亮 + 分页。

    columns 每项: {"key", "title", "width", "anchor"?, "tag"?, "level_key"?}
    tag=True 时该列渲染为状态胶囊，颜色取自 level_key 对应字段。
    accent 决定表头色调与选中行的强调描边。
    """

    SCROLLBAR_OFFSET = 18   # 补偿滚动条宽度，保证表头与数据列对齐
    # 列间距：1366×768 小屏下表格可用宽度约 947px，列宽合计 + 每列左右间距若超出，
    # 最右列会被行边框裁掉（状态胶囊只剩半个字）。间距取 2px 以为列内容让出空间。
    CELL_PADX = 2

    def __init__(self, master, columns, page_size=None, on_select=None,
                 accent=None, empty_text="暂无数据", **kwargs):
        super().__init__(master, fg_color=theme.SURFACE_CARD,
                         corner_radius=theme.RADIUS_CARD,
                         border_width=1, border_color=theme.BORDER_LIGHT, **kwargs)
        self.columns = columns
        self.page_size = page_size or config.PAGE_SIZE
        self.on_select = on_select
        self.accent = accent or theme.active_accent()
        self.empty_text = empty_text
        self._rows = []
        self._page = 1
        self._selected = None
        self._row_frames = {}
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self):
        pad = (10, 10 + self.SCROLLBAR_OFFSET)

        # 顶部强调条：与页面标题条同色，形成模块色调呼应
        ctk.CTkFrame(self, height=theme.ACCENT_BAR, corner_radius=0,
                     fg_color=self.accent).pack(fill="x", padx=pad, pady=(8, 0))

        header_bg = theme.mix(theme.PRIMARY, self.accent, 0.24)
        header = ctk.CTkFrame(self, fg_color=header_bg, height=34,
                              corner_radius=theme.RADIUS_TAG)
        header.pack(fill="x", padx=pad, pady=(2, 0))
        header.pack_propagate(False)
        for index, col in enumerate(self.columns):
            ctk.CTkLabel(header, text=col["title"], width=col["width"],
                         anchor=col.get("anchor", "w"), bg_color=header_bg,
                         font=(theme.FONT_FAMILY, 12, "bold"),
                         text_color=theme.TEXT_ON_PRIMARY,
                         ).grid(row=0, column=index, sticky="w", padx=self.CELL_PADX, pady=3)

        footer = ctk.CTkFrame(self, fg_color=theme.SURFACE_SUNKEN,
                              corner_radius=theme.RADIUS_TAG)
        # 页脚先以 side="bottom" 占位、滚动体再填充剩余高度；若顺序颠倒，
        # expand 的滚动体会把页脚挤出可视区并把自身压成 1px（表格区空白）。
        footer.pack(side="bottom", fill="x", padx=12, pady=(6, 10))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=pad, pady=(6, 0))

        self.count_label = ctk.CTkLabel(footer, text="共 0 条", font=theme.FONT_SMALL,
                                        text_color=theme.TEXT_SECONDARY)
        self.count_label.pack(side="left", padx=(10, 0), pady=4)

        self.next_button = DynamicButton(footer, text="下一页", style="outline_secondary",
                                         width=76, height=26, command=self.next_page)
        self.next_button.pack(side="right", padx=(0, 8), pady=4)
        self.page_label = ctk.CTkLabel(footer, text="第 1/1 页", font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_SECONDARY)
        self.page_label.pack(side="right", padx=10)
        self.prev_button = DynamicButton(footer, text="上一页", style="outline_secondary",
                                         width=76, height=26, command=self.prev_page)
        self.prev_button.pack(side="right", padx=(0, 8), pady=4)

    # ------------------------------------------------------------ 数据
    def set_data(self, rows):
        self._rows = list(rows or [])
        self._page = 1
        self._selected = None
        self._render()

    def get_selected(self):
        if self._selected is None:
            return None
        return self._rows[self._selected]

    def clear_selection(self):
        if self._selected is not None:
            self._paint(self._selected, self._row_frames[self._selected][2], False)
            self._selected = None

    # ------------------------------------------------------------ 渲染
    def _render(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        self._row_frames.clear()

        start = (self._page - 1) * self.page_size
        current = self._rows[start:start + self.page_size]

        if not current:
            # 提示间距不宜过大：矮窗口 / 表格区较小时，过大的 pady 会把空状态文字挤出可视区
            ctk.CTkLabel(self.body, text=self.empty_text, font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(pady=14)
            self._update_footer()
            return

        for offset, row in enumerate(current):
            index = start + offset
            base = (theme.SURFACE_CARD if offset % 2 == 0
                    else theme.stripe(self.accent, 0.955))
            row_frame = ctk.CTkFrame(self.body, fg_color=base,
                                     corner_radius=theme.RADIUS_TAG, height=34,
                                     border_width=0)
            row_frame.pack(fill="x", pady=1)
            row_frame.pack_propagate(False)

            cells = []
            for column_index, col in enumerate(self.columns):
                value = row.get(col["key"], "")
                if col.get("tag"):
                    cell = StatusTag(row_frame, text=str(value or "—"),
                                     level=row.get(col.get("level_key", ""), "正常"),
                                     width=col["width"])
                    cell.configure(bg_color=base)
                else:
                    # 空值统一渲染为空白：str(None) 会在表格里出现字面量 "None"
                    cell = ctk.CTkLabel(row_frame,
                                        text="" if value is None else str(value),
                                        width=col["width"],
                                        anchor=col.get("anchor", "w"), bg_color=base,
                                        font=theme.FONT_BODY,
                                        text_color=theme.TEXT_PRIMARY)
                cell.grid(row=0, column=column_index, sticky="w", padx=self.CELL_PADX)
                cells.append(cell)

            self._row_frames[index] = (row_frame, cells, base)
            # _e 必须带默认值：绑定的 Tcl 命令名与 after 计时器回调共用
            # "地址+函数名" 命名空间，页面切换销毁控件后可能被复用，
            # 导致计时器以 0 参数回调这里而抛出 missing '_e'。
            for widget in [row_frame] + cells:
                widget.bind("<Button-1>", lambda _e=None, i=index: self._select(i))
                widget.bind("<Enter>", lambda _e=None, i=index: self._hover(i, True))
                widget.bind("<Leave>", lambda _e=None, i=index: self._hover(i, False))

        self._update_footer()

    def _paint(self, index, color, selected=False):
        frame, cells, _base = self._row_frames.get(index, (None, [], None))
        if frame is None:
            return
        frame.configure(fg_color=color,
                        border_width=1 if selected else 0,
                        border_color=self.accent if selected else color)
        for cell in cells:
            cell.configure(bg_color=color)

    def _hover(self, index, entering):
        if index == self._selected or index not in self._row_frames:
            return
        base = self._row_frames[index][2]
        self._paint(index, theme.ROW_HOVER if entering else base)

    def _select(self, index):
        if self._selected == index:
            return
        if self._selected is not None and self._selected in self._row_frames:
            self._paint(self._selected, self._row_frames[self._selected][2], False)
        self._selected = index
        self._paint(index, theme.ROW_SELECTED, True)
        if self.on_select:
            self.on_select(self._rows[index])

    # ------------------------------------------------------------ 分页
    @property
    def total_pages(self):
        return max((len(self._rows) + self.page_size - 1) // self.page_size, 1)

    def prev_page(self):
        if self._page > 1:
            self._page -= 1
            self._selected = None
            self._render()

    def next_page(self):
        if self._page < self.total_pages:
            self._page += 1
            self._selected = None
            self._render()

    def _update_footer(self):
        self.count_label.configure(text=f"共 {len(self._rows)} 条")
        self.page_label.configure(text=f"第 {self._page}/{self.total_pages} 页")
        self.prev_button.set_enabled(self._page > 1)
        self.next_button.set_enabled(self._page < self.total_pages)


# ---------------------------------------------------------------- 通用工具
def page_header(parent, title, desc, accent=None, tag=None):
    """页面顶部标题条：顶部多色调强调条 + 模块标签 + 标题与说明。"""
    accent = accent or theme.active_accent()
    header = ctk.CTkFrame(parent, fg_color=theme.SURFACE_CARD,
                          corner_radius=theme.RADIUS_CARD,
                          border_width=1, border_color=theme.BORDER_LIGHT)
    ctk.CTkFrame(header, height=theme.ACCENT_BAR, corner_radius=0,
                 fg_color=accent).pack(fill="x")

    title_row = ctk.CTkFrame(header, fg_color="transparent")
    title_row.pack(fill="x", padx=theme.PAD_CARD, pady=(10, 2))
    ctk.CTkLabel(title_row, text=title, font=theme.FONT_SUBTITLE,
                 text_color=theme.TEXT_PRIMARY).pack(side="left")
    if tag:
        ctk.CTkLabel(title_row, text=tag, font=theme.FONT_SMALL, height=20,
                     corner_radius=theme.RADIUS_TAG, fg_color=theme.tint(accent, 0.86),
                     text_color=accent, padx=8).pack(side="left", padx=(10, 0))

    ctk.CTkLabel(header, text=desc, font=theme.FONT_SMALL,
                 text_color=theme.TEXT_SECONDARY, justify="left",
                 anchor="w").pack(anchor="w", padx=theme.PAD_CARD, pady=(0, 12))
    return header


def section_label(parent, text, color=None):
    """分区小标题：深色加粗小字，用于卡片内分组。"""
    return ctk.CTkLabel(parent, text=text, font=(theme.FONT_FAMILY, 12, "bold"),
                        text_color=color or theme.TEXT_PRIMARY, anchor="w")


def chip(parent, text, color=None, width=None):
    """小标签：模块 / 分类标记，浅底 + 同色文字。"""
    color = color or theme.SECONDARY
    item = ctk.CTkLabel(parent, text=text, font=theme.FONT_SMALL, height=20,
                        corner_radius=theme.RADIUS_TAG, fg_color=theme.tint(color, 0.86),
                        text_color=color, padx=8)
    if width:
        item.configure(width=width)
    return item


def divider(parent):
    """极浅分隔线。"""
    return ctk.CTkFrame(parent, height=1, corner_radius=0, fg_color=theme.DIVIDER)


def field_label(parent, text):
    return ctk.CTkLabel(parent, text=text, font=theme.FONT_BODY,
                        text_color=theme.TEXT_PRIMARY, width=118, anchor="w")


def filter_label(parent, text):
    """筛选栏内联标签：宽度随文字自适应，避免固定宽挤占横向空间把按钮挤出可视区。"""
    return ctk.CTkLabel(parent, text=text, font=theme.FONT_BODY,
                        text_color=theme.TEXT_PRIMARY)


def entry(parent, placeholder="", width=190, show=None):
    """输入框：聚焦时描边转为次级色，提供轻量交互反馈。"""
    widget = ctk.CTkEntry(parent, placeholder_text=placeholder, width=width, height=34,
                          show=show, font=theme.FONT_BODY,
                          fg_color=theme.SURFACE_FORM, border_color=theme.BORDER)
    widget.bind("<FocusIn>",
                lambda _e=None: widget.configure(border_color=theme.SECONDARY,
                                                 border_width=2), add="+")
    widget.bind("<FocusOut>",
                lambda _e=None: widget.configure(border_color=theme.BORDER,
                                                 border_width=1), add="+")
    return widget


def confirm(parent, message, title="操作确认"):
    """破坏性操作二次确认，统一返回布尔值。"""
    return messagebox.askyesno(title, message, parent=parent)


def warn(parent, message, title="提示"):
    messagebox.showwarning(title, message, parent=parent)


def info(parent, message, title="提示"):
    messagebox.showinfo(title, message, parent=parent)


def center_on_screen(window, width, height):
    """窗口居中，适配 1366×768 及以上分辨率。"""
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    x = max((screen_w - width) // 2, 0)
    y = max((screen_h - height) // 2, 0)
    window.geometry(f"{width}x{height}+{x}+{y}")