# -*- coding: utf-8 -*-
"""人员登离管理：人员登记页、人员离开页、内部/外协/甲方三类人员台账页。

登记保存即自动分配房间与救生艇；离开确认即释放床位与艇位；
三类人员页共用同一张人员表，按人员类型过滤，各自呈现独立的统计视图。
"""

import logging
import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

import config
from services import assign_service, excel_service, personnel_service
from ui import theme
from ui.widgets import (Card, DataTable, DynamicButton, confirm, entry,
                        field_label, filter_label, info, page_header, warn)

_logger = logging.getLogger("app")


# ---------------------------------------------------------------- 人员表单
class PersonForm(ctk.CTkFrame):
    """人员信息表单：登记页与新增 / 编辑对话框共用，字段取自 PERSON_FORM_FIELDS。"""

    def __init__(self, master, default_person_type=None, columns=2, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.columns = columns
        self.default_person_type = default_person_type or config.PERSON_TYPES[0]
        self.inputs = {}
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self):
        for index, (key, label, kind, values) in enumerate(config.PERSON_FORM_FIELDS):
            row, side = divmod(index, self.columns)
            base_col = side * 2
            field_label(self, label).grid(row=row, column=base_col,
                                          sticky="w", padx=(0, 6), pady=7)
            widget = self._make_input(kind, values)
            widget.grid(row=row, column=base_col + 1, sticky="w",
                        padx=(0, 24), pady=7)
            self.inputs[key] = widget
        self.inputs["gender"].configure(command=lambda _v: self.refresh_resources())

    def _make_input(self, kind, values=None):
        if kind == "entry":
            return entry(self)
        if kind == "option":
            menu = ctk.CTkOptionMenu(self, values=list(values), width=190, height=34,
                                     font=theme.FONT_BODY, fg_color=theme.SECONDARY,
                                     button_color=theme.hover(theme.SECONDARY),
                                     button_hover_color=theme.active(theme.SECONDARY),
                                     dropdown_fg_color=theme.SURFACE_CARD,
                                     dropdown_text_color=theme.TEXT_PRIMARY)
            menu.set(values[0])
            return menu
        if kind == "combo":
            units = list(config.COMMON_UNITS) + personnel_service.distinct_units()
            combo = ctk.CTkComboBox(self, values=units, width=190, height=34,
                                    font=theme.FONT_BODY, fg_color=theme.SURFACE_FORM,
                                    border_color=theme.BORDER,
                                    button_color=theme.SECONDARY,
                                    dropdown_fg_color=theme.SURFACE_CARD,
                                    dropdown_text_color=theme.TEXT_PRIMARY)
            combo.set(units[0])
            return combo
        if kind == "room":
            combo = ctk.CTkComboBox(self, values=assign_service.room_options(),
                                    width=190, height=34, font=theme.FONT_BODY,
                                    fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
                                    button_color=theme.SECONDARY,
                                    dropdown_fg_color=theme.SURFACE_CARD,
                                    dropdown_text_color=theme.TEXT_PRIMARY)
            combo.set("自动分配")
            return combo
        combo = ctk.CTkComboBox(self, values=assign_service.lifeboat_options(),
                                width=190, height=34, font=theme.FONT_BODY,
                                fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
                                button_color=theme.SECONDARY,
                                dropdown_fg_color=theme.SURFACE_CARD,
                                dropdown_text_color=theme.TEXT_PRIMARY)
        combo.set("自动分配")
        return combo

    # ------------------------------------------------------------ 取值 / 回填
    def value(self, key):
        return self.inputs[key].get()

    def get_data(self):
        return {key: self.value(key) for key in self.inputs
                if key not in ("room_no", "boat_no")}

    def room_text(self):
        return self.value("room_no")

    def boat_text(self):
        return self.value("boat_no")

    def set_room(self, text):
        self.inputs["room_no"].set(text)

    def set_boat(self, text):
        self.inputs["boat_no"].set(text)

    def refresh_resources(self):
        gender = self.value("gender")
        self.inputs["room_no"].configure(values=assign_service.room_options(gender))
        self.inputs["boat_no"].configure(values=assign_service.lifeboat_options())
        self.inputs["unit"].configure(
            values=list(config.COMMON_UNITS) + personnel_service.distinct_units())

    def reset(self):
        defaults = {
            "gender": config.GENDERS[0],
            "person_type": self.default_person_type,
            "unit": config.COMMON_UNITS[0],
            "onboard_time": personnel_service.now_text(),
            "room_no": "自动分配",
            "boat_no": "自动分配",
        }
        for key, widget in self.inputs.items():
            if isinstance(widget, ctk.CTkEntry):
                widget.delete(0, "end")
                if key in defaults:
                    widget.insert(0, defaults[key])
            else:
                widget.set(defaults.get(key, ""))
        self.refresh_resources()

    def set_values(self, data):
        for key, widget in self.inputs.items():
            value = data.get(key)
            if isinstance(widget, ctk.CTkEntry):
                widget.delete(0, "end")
                if value not in (None, ""):
                    widget.insert(0, str(value))
            else:
                widget.set("" if value in (None, "") else str(value))
        self.refresh_resources()
        for key in ("room_no", "boat_no"):
            if data.get(key):
                self.inputs[key].set(str(data[key]))


# ---------------------------------------------------------------- 人员登记
class RegisterPage(ctk.CTkFrame):
    """人员登记：登记即建档，保存时自动分配房间与救生艇。"""

    TITLE = "人员登记"
    DESC = ("登记即建档，保存时自动分配房间与救生艇；"
            "住井达到 29/30 天（在平台满 28/29 个自然日）自动进入预警。")
    HINT = ("填写完成后点击「自动分配」可预览房间与救生艇，"
            "也可直接保存由系统自动匹配。")

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self._build()

    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        card = Card(self, title="人员信息")
        card.pack(fill="both", expand=True, pady=(theme.GAP, 0))

        # 操作行先以 side="bottom" 固定在卡片底部：表单字段较多时矮窗口下按钮也不会被挤出可视区
        actions = ctk.CTkFrame(card.body, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(10, 0))

        DynamicButton(actions, text="重置", style="ghost", width=88,
                      command=self.reset_form).pack(side="left", padx=(0, 10))
        DynamicButton(actions, text="自动分配", style="secondary", width=104,
                      command=self.preview_assign).pack(side="left", padx=(0, 10))
        self.save_button = DynamicButton(actions, text="保存登记", style="primary",
                                         width=120, command=self.save)
        self.save_button.pack(side="left")

        if not self.user.can("personnel.create"):
            self.save_button.set_enabled(False)

        # 表单放入可滚动区：字段较多时可滚动查看，且不会把固定底部的操作按钮挤出可视区
        scroll = ctk.CTkScrollableFrame(card.body, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self.form = PersonForm(scroll)
        self.form.pack(fill="x")

        self.hint = ctk.CTkLabel(scroll, text=self.HINT, font=theme.FONT_SMALL,
                                 text_color=theme.TEXT_SECONDARY)
        self.hint.pack(anchor="w", pady=(12, 0))

        self.form.reset()

    # ------------------------------------------------------------ 动作
    def reset_form(self):
        self.form.reset()
        self.hint.configure(text=self.HINT, text_color=theme.TEXT_SECONDARY)

    def preview_assign(self):
        room_no, boat_no, message = assign_service.auto_assign_preview(
            self.form.value("gender"), self.form.value("unit"))
        self.form.refresh_resources()
        if room_no is None:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.form.set_room(room_no)
        if boat_no:
            self.form.set_boat(boat_no)
        text = f"自动分配结果：房间 {room_no}"
        if boat_no:
            text += f"，救生艇 {boat_no}"
        self.hint.configure(text=text, text_color=theme.SUCCESS)

    def save(self):
        self.save_button.set_loading(True)
        try:
            ok, message, _person_id = personnel_service.register_person(
                self.form.get_data(), self.user.username,
                room_text=self.form.room_text(), boat_text=self.form.boat_text())
        except Exception as exc:                        # noqa: BLE001 兜底：不再静默失败
            _logger.exception("人员登记保存失败")
            messagebox.showerror("登记失败", f"程序内部错误，请把此信息反馈给管理员：\n\n{exc!r}")
            return
        finally:
            self.save_button.set_loading(False)

        if not ok:
            warn(self, message, "登记失败")
            return
        info(self, message, "登记成功")
        self.reset_form()
        self.app.refresh_status()


# ---------------------------------------------------------------- 人员离开
class LeavePage(ctk.CTkFrame):
    """人员离开：选中在平台人员办理离开，自动释放房间与救生艇。"""

    TITLE = "人员离开"
    DESC = "办理离开后自动释放房间床位与救生艇名额，并归档住井履历；已离开人员保留显示其下平台时间。"

    # 列宽按 1366×768 小屏（表格可用宽约 947px）反推：合计 + 列间距必须放得下，
    # 否则最右「住井状态」胶囊会被裁掉；「上/下平台时间」各需容纳 16 字符时间。
    COLUMNS = [
        {"key": "emp_no", "title": "工号", "width": 74},
        {"key": "name", "title": "姓名", "width": 58},
        {"key": "gender", "title": "性别", "width": 38},
        {"key": "unit", "title": "所属单位", "width": 100},
        {"key": "person_type", "title": "人员类型", "width": 78},
        {"key": "room_no", "title": "房间号", "width": 58},
        {"key": "boat_no", "title": "救生艇", "width": 56},
        {"key": "onboard_time", "title": "上平台时间", "width": 146},
        {"key": "actual_off_time", "title": "下平台时间", "width": 146},
        {"key": "onboard_days", "title": "住井天数", "width": 60, "anchor": "center"},
        {"key": "onboard_level", "title": "住井状态", "width": 78,
         "tag": True, "level_key": "onboard_level"},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self._build()
        self.load_data()

    # ------------------------------------------------------------ 界面
    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        filters = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))

        filter_label(filters, "人员类型").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.type_menu = ctk.CTkOptionMenu(
            filters, values=["全部"] + list(config.PERSON_TYPES), width=120, height=34,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.type_menu.pack(side="left")

        filter_label(filters, "所属单位").pack(side="left", padx=(20, 6))
        self.unit_combo = ctk.CTkComboBox(
            filters, values=["全部"] + personnel_service.distinct_units(), width=150,
            height=34, font=theme.FONT_BODY, fg_color=theme.SURFACE_FORM,
            border_color=theme.BORDER, button_color=theme.SECONDARY,
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.unit_combo.pack(side="left")
        self.unit_combo.set("全部")

        filter_label(filters, "关键字").pack(side="left", padx=(20, 6))
        self.keyword_entry = entry(filters, "工号 / 姓名", width=170)
        self.keyword_entry.pack(side="left")

        DynamicButton(filters, text="查询", style="primary", width=88,
                      command=self.load_data).pack(side="left", padx=(16, 8))
        DynamicButton(filters, text="重置", style="ghost", width=80,
                      command=self.reset_filters).pack(side="left")

        self.table = DataTable(self, self.COLUMNS, page_size=15)
        self.table.pack(fill="both", expand=True, pady=(theme.GAP, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", pady=(theme.GAP, 0))
        ctk.CTkLabel(actions, text="选中一名在平台人员后办理离开",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        if self.user.can("personnel.update"):
            DynamicButton(actions, text="离开登记", style="danger", width=120,
                          command=self.leave_selected).pack(side="right")

    # ------------------------------------------------------------ 数据
    def reset_filters(self):
        self.type_menu.set("全部")
        self.unit_combo.set("全部")
        self.keyword_entry.delete(0, "end")
        self.load_data()

    def load_data(self):
        person_type = self.type_menu.get()
        unit = self.unit_combo.get()
        rows, _total = personnel_service.list_personnel(
            page=1, page_size=2000,
            person_type=None if person_type == "全部" else person_type,
            unit=None if unit in ("", "全部") else unit,
            keyword=self.keyword_entry.get().strip() or None)
        self.table.set_data(rows)
        self.app.refresh_status()

    def leave_selected(self):
        record = self.table.get_selected()
        if record is None:
            warn(self, "请先选中要办理离开的人员", "提示")
            return
        if record.get("status") != config.PERSON_STATUS_ONBOARD:
            warn(self, f"{record['name']} 已于 "
                      f"{record.get('actual_off_time') or '此前'} 办理离开，无需重复操作",
                 "提示")
            return
        dialog = LeaveDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if not dialog.success:
            return
        self.load_data()


class LeaveDialog(ctk.CTkToplevel):
    """离开登记对话框。"""

    def __init__(self, master, user, record):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.record = record
        self.success = False

        self.title("人员离开登记")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.geometry("440x470")
        self._build()
        self.after(120, self.focus_force)

    def _build(self):
        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=82)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text=f"{self.record['name']}（{self.record['emp_no']}）",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(14, 2))
        ctk.CTkLabel(head,
                     text=f"房间 {self.record.get('room_no') or '—'} ｜ "
                          f"救生艇 {self.record.get('boat_no') or '—'} ｜ "
                          f"已住井 {self.record['onboard_days']} 天",
                     font=theme.FONT_SMALL,
                     text_color=theme.NAV_TEXT).pack()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=16)

        field_label(body, "离开时间 *").grid(row=0, column=0, sticky="w", pady=10)
        self.time_entry = entry(body, "", width=230)
        self.time_entry.insert(0, personnel_service.now_text())
        self.time_entry.grid(row=0, column=1, sticky="w", pady=10)

        field_label(body, "去向 *").grid(row=1, column=0, sticky="w", pady=10)
        self.destination_entry = entry(body, "如：陆地基地 / 倒班", width=230)
        self.destination_entry.grid(row=1, column=1, sticky="w", pady=10)

        field_label(body, "离开原因 *").grid(row=2, column=0, sticky="w", pady=10)
        self.reason_menu = ctk.CTkOptionMenu(
            body, values=list(config.LEAVE_REASONS), width=230, height=34,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.reason_menu.grid(row=2, column=1, sticky="w", pady=10)

        field_label(body, "经办人 *").grid(row=3, column=0, sticky="w", pady=10)
        self.operator_entry = entry(body, "", width=230)
        self.operator_entry.insert(0, self.user.username)
        self.operator_entry.grid(row=3, column=1, sticky="w", pady=10)

        field_label(body, "备注").grid(row=4, column=0, sticky="w", pady=10)
        self.note_entry = entry(body, "可选", width=230)
        self.note_entry.grid(row=4, column=1, sticky="w", pady=10)

        self.message_label = ctk.CTkLabel(body, text=" ", font=theme.FONT_SMALL,
                                          text_color=theme.DANGER, wraplength=360,
                                          justify="left")
        self.message_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="left", padx=(0, 10))
        self.submit_button = DynamicButton(buttons, text="确认离开", style="danger",
                                           width=120, command=self._submit)
        self.submit_button.pack(side="left")

    def _submit(self):
        self.submit_button.set_loading(True)
        ok, message = personnel_service.leave_person(
            self.record["id"], self.time_entry.get(),
            self.destination_entry.get(), self.reason_menu.get(),
            self.operator_entry.get().strip() or self.user.username,
            self.note_entry.get())
        self.submit_button.set_loading(False)
        if not ok:
            self.message_label.configure(text=message)
            return
        self.success = True
        info(self, message, "离开登记完成")
        self.destroy()


# ---------------------------------------------------------------- 新增 / 编辑
class PersonFormDialog(ctk.CTkToplevel):
    """人员新增 / 编辑对话框：mode 为 add 或 edit。"""

    def __init__(self, master, user, person_type, mode="add", person_id=None):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.person_type = person_type
        self.mode = mode
        self.person_id = person_id
        self.success = False

        self.title("新增人员" if mode == "add" else "编辑人员信息")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.geometry("780x600")
        self._build()
        self.after(120, self.focus_force)

    def _build(self):
        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=62)
        head.pack(fill="x")
        head.pack_propagate(False)
        title = f"新增{self.person_type}" if self.mode == "add" else "编辑人员信息"
        ctk.CTkLabel(head, text=title, font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(16, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=16)

        self.form = PersonForm(body, default_person_type=self.person_type)
        self.form.pack(fill="x")

        self.hint = ctk.CTkLabel(
            body, text="房间号与救生艇编号可留空由系统自动分配，"
                       "也可点击「自动分配」预览；在平台人员可调整房间与艇位。",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
            wraplength=700, justify="left")
        self.hint.pack(anchor="w", pady=(12, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(14, 0))
        self.submit_button = DynamicButton(buttons, text="保存", style="primary",
                                           width=120, command=self._submit)
        self.submit_button.pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))
        DynamicButton(buttons, text="自动分配", style="secondary", width=104,
                      command=self._preview).pack(side="right", padx=(0, 10))

        if self.mode == "edit":
            data = personnel_service.person_form_data(self.person_id)
            if data:
                self.form.set_values(data)
        else:
            self.form.reset()

    def _preview(self):
        room_no, boat_no, message = assign_service.auto_assign_preview(
            self.form.value("gender"), self.form.value("unit"))
        self.form.refresh_resources()
        if room_no is None:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.form.set_room(room_no)
        if boat_no:
            self.form.set_boat(boat_no)
        text = f"自动分配结果：房间 {room_no}"
        if boat_no:
            text += f"，救生艇 {boat_no}"
        self.hint.configure(text=text, text_color=theme.SUCCESS)

    def _submit(self):
        self.submit_button.set_loading(True)
        if self.mode == "add":
            ok, message, _person_id = personnel_service.register_person(
                self.form.get_data(), self.user.username,
                room_text=self.form.room_text(), boat_text=self.form.boat_text())
        else:
            ok, message = personnel_service.update_person(
                self.person_id, self.form.get_data(), self.user.username,
                room_text=self.form.room_text(), boat_text=self.form.boat_text())
        self.submit_button.set_loading(False)

        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "保存成功")
        self.destroy()


# ---------------------------------------------------------------- 三类人员台账
CATEGORY_META = {
    "内部人员": {
        "desc": "内部人员台账：按姓名 / 所属单位 / 房间号 / 救生艇查询在平台与住井情况。",
        "metric_label": "涉及单位",
    },
    "外协人员": {
        "desc": "外协承包商人员台账：按姓名 / 所属单位 / 房间号 / 救生艇查询在平台与住井情况。",
        "metric_label": "涉及承包商",
    },
    "甲方人员": {
        "desc": "甲方来访人员台账：按姓名 / 所属单位 / 房间号 / 救生艇查询来访与住井情况。",
        "metric_label": "涉及单位",
    },
}


class CategoryPage(ctk.CTkFrame):
    """内部 / 外协 / 甲方人员台账：指标概览 + 查询 + 增删改 + 导入导出。"""

    # 列宽按 1366×768 小屏反推：列宽合计 + 列间距必须放得下，
    # 否则最右「住井状态」胶囊会被裁掉。
    COLUMNS = [
        {"key": "emp_no", "title": "工号", "width": 74},
        {"key": "name", "title": "姓名", "width": 58},
        {"key": "gender", "title": "性别", "width": 38},
        {"key": "unit", "title": "所属单位", "width": 104},
        {"key": "post", "title": "岗位 / 工种", "width": 80},
        {"key": "room_no", "title": "房间号", "width": 58},
        {"key": "boat_no", "title": "救生艇", "width": 56},
        {"key": "onboard_time", "title": "上平台时间", "width": 146},
        {"key": "actual_off_time", "title": "下平台时间", "width": 146},
        {"key": "onboard_days", "title": "住井天数", "width": 60, "anchor": "center"},
        {"key": "onboard_level", "title": "住井状态", "width": 78,
         "tag": True, "level_key": "onboard_level"},
    ]
    # 表格显式高度：整页可滚动后表格不参与 expand，需给定高度才能一次显示约 10 行记录
    TABLE_HEIGHT = 420

    def __init__(self, master, app, person_type):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.person_type = person_type
        self.meta = CATEGORY_META[person_type]
        self.rows = []
        self.metric_values = {}
        self.filter_inputs = {}
        self.columns = list(self.COLUMNS)
        self._build()
        self.load_data()

    # ------------------------------------------------------------ 界面
    def _build(self):
        # 页面整体可滚动：1366×768 小屏下「指标卡 + 表格 + 操作行」总高可能超出可视区，
        # 固定布局会把表格压到只剩两三行。整页滚动后各区块都完整可达。
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

        page_header(self.body, self.person_type,
                    self.meta["desc"]).pack(fill="x")
        self._build_stats(self.body)
        self._build_filters(self.body)

        # 滚动容器内表格不参与 expand：外层包裹固定高度，保证一次显示约 10 行记录
        holder = ctk.CTkFrame(self.body, fg_color="transparent",
                              height=self.TABLE_HEIGHT)
        holder.pack(fill="x", pady=(theme.GAP, 0))
        holder.pack_propagate(False)

        self.table = DataTable(holder, self.columns, page_size=15)
        self.table.pack(fill="both", expand=True)

        self._build_actions(self.body)

    def _build_stats(self, parent):
        strip = ctk.CTkFrame(parent, fg_color="transparent")
        strip.pack(fill="x", pady=(theme.GAP, 0))

        specs = [
            ("total", "总人数", theme.PRIMARY),
            ("onboard", "在平台", theme.SUCCESS),
            ("left", "已离开", theme.TEXT_SECONDARY),
            ("units", self.meta["metric_label"], theme.SECONDARY),
        ]
        for index, (key, label, color) in enumerate(specs):
            card = ctk.CTkFrame(strip, fg_color=theme.SURFACE_CARD,
                                corner_radius=theme.RADIUS_CARD)
            card.pack(side="left", fill="x", expand=True,
                      padx=(0 if index == 0 else theme.GAP, 0))
            ctk.CTkFrame(card, height=4, corner_radius=2,
                         fg_color=color).pack(fill="x", padx=theme.PAD_CARD,
                                              pady=(8, 4))
            value_label = ctk.CTkLabel(card, text="0", font=theme.FONT_METRIC,
                                       text_color=theme.TEXT_PRIMARY)
            value_label.pack(anchor="w", padx=theme.PAD_CARD)
            ctk.CTkLabel(card, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(
                anchor="w", padx=theme.PAD_CARD, pady=(0, 8))
            self.metric_values[key] = value_label

    def _build_filters(self, parent):
        filters = ctk.CTkFrame(parent, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))

        filter_label(filters, "状态").pack(side="left", padx=(theme.PAD_CARD, 6), pady=8)
        self.status_menu = ctk.CTkOptionMenu(
            filters, values=["全部", "在平台", "已离开"], width=90, height=34,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.status_menu.pack(side="left")

        # 四个查询条件均为模糊匹配：小区块宽度经 1366×768 反推，
        # 保证「查询 / 重置」按钮不会被挤出可视区。
        specs = (("name", "姓名", 90), ("unit", "所属单位", 118),
                 ("room_no", "房间号", 86), ("boat_no", "救生艇", 86))
        for key, label, width in specs:
            filter_label(filters, label).pack(side="left", padx=(10, 6))
            widget = entry(filters, "", width=width)
            widget.pack(side="left")
            self.filter_inputs[key] = widget

        DynamicButton(filters, text="查询", style="primary", width=78,
                      command=self.load_data).pack(side="left", padx=(12, 8))
        DynamicButton(filters, text="重置", style="ghost", width=74,
                      command=self.reset_filters).pack(side="left")

    def _build_actions(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        # 页面已整体可滚动，操作行按正常文档流排在表格下方，不再需要侵占可视区
        bar.pack(fill="x", pady=(theme.GAP, 0))
        ctk.CTkLabel(bar, text="选中一行后可编辑或删除；在平台人员须先办理离开再删除。",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")

        if self.user.can("personnel.export"):
            DynamicButton(bar, text="批量导出", style="ghost", width=100,
                          command=self.export_data).pack(side="right", padx=(10, 0))
        if self.user.can("personnel.import"):
            DynamicButton(bar, text="下载模板", style="ghost", width=100,
                          command=self.download_template).pack(side="right", padx=(10, 0))
            DynamicButton(bar, text="批量导入", style="secondary", width=100,
                          command=self.import_data).pack(side="right", padx=(10, 0))
        if self.user.can("personnel.delete"):
            DynamicButton(bar, text="删除", style="danger", width=88,
                          command=self.delete_selected).pack(side="right", padx=(10, 0))
        if self.user.can("personnel.update"):
            DynamicButton(bar, text="编辑", style="secondary", width=88,
                          command=self.edit_selected).pack(side="right", padx=(10, 0))
        if self.user.can("personnel.create"):
            DynamicButton(bar, text="新增人员", style="primary", width=104,
                          command=self.add_person).pack(side="right")

    # ------------------------------------------------------------ 数据
    def reset_filters(self):
        self.status_menu.set("全部")
        for widget in self.filter_inputs.values():
            widget.delete(0, "end")
        self.load_data()

    def load_data(self):
        status = self.status_menu.get()
        values = {key: widget.get().strip()
                  for key, widget in self.filter_inputs.items()}
        if status == "在平台":
            status_value = config.PERSON_STATUS_ONBOARD
        elif status == "已离开":
            status_value = config.PERSON_STATUS_LEFT
        else:
            status_value = None

        rows, _total = personnel_service.list_personnel(
            page=1, page_size=2000, person_type=self.person_type,
            name=values["name"] or None,
            unit=values["unit"] or None,
            room_no=values["room_no"] or None,
            boat_no=values["boat_no"] or None,
            status=status_value)

        self.rows = rows
        self.table.set_data(rows)

        stats = personnel_service.category_stats(self.person_type)
        self._refresh_metrics(stats)
        self.app.refresh_status()

    def _refresh_metrics(self, stats):
        self.metric_values["total"].configure(text=str(stats["total"]))
        self.metric_values["onboard"].configure(text=str(stats["onboard"]))
        self.metric_values["left"].configure(text=str(stats["left"]))
        self.metric_values["units"].configure(text=str(len(stats["by_unit"])))

    # ------------------------------------------------------------ 增删改
    def add_person(self):
        dialog = PersonFormDialog(self, self.user, self.person_type, mode="add")
        dialog.grab_set()
        self.wait_window(dialog)
        if not dialog.success:
            return
        self.load_data()

    def edit_selected(self):
        record = self.table.get_selected()
        if record is None:
            warn(self, "请先选中要编辑的人员", "提示")
            return
        dialog = PersonFormDialog(self, self.user, self.person_type, mode="edit",
                                  person_id=record["id"])
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def delete_selected(self):
        record = self.table.get_selected()
        if record is None:
            warn(self, "请先选中要删除的人员", "提示")
            return
        if record["status"] == config.PERSON_STATUS_ONBOARD:
            warn(self, f"{record['name']} 仍在平台，请先办理离开再删除", "无法删除")
            return
        if not confirm(self, f"确认删除 {record['name']}（{record['emp_no']}）？\n"
                             "删除后仅保留审计日志，不可恢复。", "删除确认"):
            return
        ok, message = personnel_service.soft_delete(record["id"], self.user.username)
        if not ok:
            warn(self, message, "删除失败")
            return
        info(self, message, "删除完成")
        self.load_data()

    # ------------------------------------------------------------ 导入导出
    def download_template(self):
        try:
            path = excel_service.export_template(self.person_type)
        except Exception as exc:                       # noqa: BLE001 文件写入异常需提示
            warn(self, f"生成模板失败：{exc}", "生成失败")
            return
        info(self, f"已生成{self.person_type}导入模板：\n{path}", "模板已生成")

    def import_data(self):
        path = filedialog.askopenfilename(
            title=f"选择{self.person_type}导入文件",
            filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            result = excel_service.import_records(path, self.person_type,
                                                  self.user.username)
        except Exception as exc:                       # noqa: BLE001 文件格式异常需提示
            warn(self, f"导入失败：{exc}", "导入失败")
            return

        lines = [f"共读取 {result['total']} 行，成功 {result['ok']} 行，"
                 f"失败 {result['fail']} 行"]
        if result["report_path"]:
            lines.append(f"错误明细：{result['report_path'].name}")
        info(self, "\n".join(lines), "导入完成")
        if result["report_path"] and confirm(self, "是否打开导入错误报告？",
                                             "导入错误报告"):
            self._open_path(result["report_path"])
        self.load_data()

    def export_data(self):
        if not self.rows:
            warn(self, "当前无可导出的数据", "提示")
            return
        try:
            path = excel_service.export_records(self.rows, self.person_type)
        except Exception as exc:                       # noqa: BLE001 文件写入异常需提示
            warn(self, f"导出失败：{exc}", "导出失败")
            return
        info(self, f"已导出 {len(self.rows)} 条记录：\n{path}", "导出完成")
        if confirm(self, "是否立即打开导出文件？", "导出完成"):
            self._open_path(path)

    @staticmethod
    def _open_path(path):
        try:
            os.startfile(path)                         # 仅 Windows 平台
        except OSError:
            pass