# -*- coding: utf-8 -*-
"""医疗物资管理：药品库存台账、医疗设备台账、效期与库存预警三个页面。

业务规则全部由 medicine_service / equipment_service 承担，界面只负责录入与呈现。
"""

import customtkinter as ctk

import config
from services import equipment_service, excel_service, medicine_service, personnel_service
from ui import theme
from ui.widgets import (Card, DataTable, DynamicButton, StatusTag, confirm, entry,
                        filter_label, info, page_header, warn)


# ---------------------------------------------------------------- 表单小工具
def _build_fields(parent, specs, inputs, columns=2):
    """按字段定义批量生成「标签 + 输入控件」，控件写入 inputs 字典。"""
    for index, (key, label, kind, options) in enumerate(specs):
        row, col = divmod(index, columns)
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=row, column=col, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(cell, text=label, font=theme.FONT_SMALL, width=132, anchor="w",
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        if kind in ("option", "boat", "combo"):
            values = list(options) if options else equipment_service.boat_options()
            if kind == "combo":
                widget = ctk.CTkComboBox(
                    cell, values=values, width=210, height=32, font=theme.FONT_BODY,
                    fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
                    button_color=theme.SECONDARY, dropdown_fg_color=theme.SURFACE_CARD,
                    dropdown_text_color=theme.TEXT_PRIMARY)
            else:
                if kind == "boat":
                    values = [""] + values
                widget = ctk.CTkOptionMenu(
                    cell, values=values, width=210, height=32, font=theme.FONT_BODY,
                    fg_color=theme.SECONDARY, button_color=theme.hover(theme.SECONDARY),
                    button_hover_color=theme.active(theme.SECONDARY),
                    dropdown_fg_color=theme.SURFACE_CARD,
                    dropdown_text_color=theme.TEXT_PRIMARY)
                widget.set(values[0])
        else:
            widget = entry(cell, "", width=210)
        widget.pack(anchor="w")
        inputs[key] = widget


def _dialog_shell(window, title, width, height):
    """在给定对话框窗口内构建「顶部标题条 + 可滚动内容区」，返回 (窗口, body)。"""
    window.title(title)
    window.resizable(False, False)
    window.transient(window.master.winfo_toplevel())
    window.geometry(f"{width}x{height}")
    head = ctk.CTkFrame(window, fg_color=theme.PRIMARY, corner_radius=0, height=58)
    head.pack(fill="x")
    head.pack_propagate(False)
    ctk.CTkLabel(head, text=title, font=theme.FONT_SUBTITLE,
                 text_color=theme.TEXT_ON_PRIMARY).pack(pady=(16, 0))
    body = ctk.CTkScrollableFrame(window, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=20, pady=14)
    window.after(120, window.focus_force)
    return window, body


def _detail_row(parent, label, value, color=None):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=2)
    ctk.CTkLabel(row, text=label, width=76, anchor="nw", font=theme.FONT_SMALL,
                 text_color=theme.TEXT_SECONDARY).pack(side="left")
    ctk.CTkLabel(row, text=str(value if value not in (None, "") else "—"),
                 anchor="w", justify="left", wraplength=250, font=theme.FONT_SMALL,
                 text_color=color or theme.TEXT_PRIMARY).pack(side="left", fill="x",
                                                              expand=True)


def _person_option_map():
    """在平台人员下拉：显示文本 → 人员 id。"""
    rows, _total = personnel_service.list_personnel(page=1, page_size=2000,
                                                    only_onboard=True)
    mapping = {}
    for row in rows:
        mapping[f"{row['emp_no']} {row['name']}"] = row["id"]
    return mapping


# ================================================================ 药品库存台账
class MedicineStockPage(ctk.CTkFrame):
    TITLE = "药品库存台账"
    DESC = ("药品档案、入库 / 出库 / 盘点与库存查询；"
            "效期 ≤3 个月黄警、≤1 个月红警，已过期批次禁止出库。")

    COLUMNS = [
        {"key": "code", "title": "编码", "width": 88},
        {"key": "name", "title": "通用名", "width": 130},
        {"key": "spec", "title": "规格", "width": 86},
        {"key": "category", "title": "类别", "width": 60},
        {"key": "is_prescription_text", "title": "处方药", "width": 74,
         "tag": True, "level_key": "is_prescription_text"},
        {"key": "total_quantity", "title": "库存量", "width": 66, "anchor": "center"},
        {"key": "stock_lower", "title": "下限", "width": 54, "anchor": "center"},
        {"key": "nearest_expire", "title": "最近效期", "width": 96},
        {"key": "expire_status", "title": "效期状态", "width": 88,
         "tag": True, "level_key": "expire_status"},
        {"key": "stock_status", "title": "库存状态", "width": 88,
         "tag": True, "level_key": "stock_status"},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.rows = []
        self.current = None
        self._build()
        self.load_data()

    # ------------------------------------------------------------ 界面
    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        filters = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))
        filter_label(filters, "关键字").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.keyword_entry = entry(filters, "编码 / 通用名 / 厂家", width=176)
        self.keyword_entry.pack(side="left")
        filter_label(filters, "类别").pack(side="left", padx=(16, 6))
        self.category_menu = ctk.CTkOptionMenu(
            filters, values=["全部"] + list(config.MEDICINE_CATEGORIES), width=104,
            height=34, font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.category_menu.pack(side="left")
        self.show_disabled = ctk.CTkCheckBox(
            filters, text="含停用", font=theme.FONT_BODY, width=80, height=26,
            checkbox_width=20, checkbox_height=20, text_color=theme.TEXT_PRIMARY,
            fg_color=theme.SECONDARY, hover_color=theme.hover(theme.SECONDARY))
        self.show_disabled.pack(side="left", padx=(16, 0))
        self.warning_only = ctk.CTkCheckBox(
            filters, text="仅显示预警", font=theme.FONT_BODY, width=104, height=26,
            checkbox_width=20, checkbox_height=20, text_color=theme.TEXT_PRIMARY,
            fg_color=theme.SECONDARY, hover_color=theme.hover(theme.SECONDARY))
        self.warning_only.pack(side="left", padx=(12, 0))

        DynamicButton(filters, text="查询", style="primary", width=84,
                      command=self.load_data).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_filters).pack(side="left")
        if self.user.can("medicine.view"):
            DynamicButton(filters, text="导出库存", style="secondary", width=100,
                          command=self.export_stock).pack(side="right",
                                                           padx=(0, theme.PAD_CARD))
        if self.user.can("medicine.create"):
            DynamicButton(filters, text="新增药品", style="primary", width=100,
                          command=self.add_medicine).pack(side="right", padx=(0, 8))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(theme.GAP, 0))

        # 固定宽度的详情面板先以 side="right" 占位，否则会被 expand 的表格挤成 1px
        right = ctk.CTkFrame(body, fg_color=theme.SURFACE_CARD, width=404,
                             corner_radius=theme.RADIUS_CARD)
        right.pack(side="right", fill="both", padx=(theme.GAP, 0))
        right.pack_propagate(False)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        self.table = DataTable(left, self.COLUMNS, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)

        self._build_detail(right)

    def _build_detail(self, parent):
        ctk.CTkLabel(parent, text="药品详情与批次", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w",
                                                         padx=theme.PAD_CARD,
                                                         pady=(12, 4))
        self.detail = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.detail.pack(fill="both", expand=True, padx=theme.PAD_CARD, pady=(0, 6))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", padx=theme.PAD_CARD, pady=(0, 12))
        self.edit_button = DynamicButton(actions, text="编辑档案", style="primary",
                                         width=118, command=self.edit_medicine)
        self.toggle_button = DynamicButton(actions, text="停用 / 启用", style="ghost",
                                           width=118, command=self.toggle_medicine)
        self.delete_button = DynamicButton(actions, text="删除", style="danger",
                                           width=118, command=self.delete_medicine)
        self.in_button = DynamicButton(actions, text="入库", style="success",
                                       width=118, command=self.stock_in)
        self.out_button = DynamicButton(actions, text="出库", style="warning",
                                        width=118, command=self.stock_out)
        self.check_button = DynamicButton(actions, text="盘点", style="secondary",
                                          width=118, command=self.stock_check)
        buttons = (self.edit_button, self.toggle_button, self.delete_button,
                   self.in_button, self.out_button, self.check_button)
        for index, button in enumerate(buttons):
            button.grid(row=index // 3, column=index % 3, padx=(0, 8), pady=4, sticky="w")

        self._can_edit = self.user.can("medicine.update")
        self._can_delete = self.user.can("medicine.delete")
        self._can_manage = self.user.can("supply.manage")
        self._render_detail(None)

    # ------------------------------------------------------------ 数据
    def reset_filters(self):
        self.keyword_entry.delete(0, "end")
        self.category_menu.set("全部")
        self.show_disabled.deselect()
        self.warning_only.deselect()
        self.load_data()

    def load_data(self):
        category = self.category_menu.get()
        self.rows = medicine_service.list_medicines(
            keyword=self.keyword_entry.get().strip() or None,
            category=None if category in ("", "全部") else category,
            only_active=not bool(self.show_disabled.get()),
            only_warning=bool(self.warning_only.get()))
        self.table.set_data(self.rows)
        self.current = None
        self._render_detail(None)

    def _on_select(self, record):
        self.current = record
        self._render_detail(record)

    def _render_detail(self, record):
        for child in self.detail.winfo_children():
            child.destroy()

        has = record is not None
        active = has and bool(record.get("status"))
        self.edit_button.set_enabled(has and self._can_edit)
        self.toggle_button.set_enabled(has and self._can_edit)
        self.delete_button.set_enabled(has and self._can_delete)
        self.in_button.set_enabled(active and self._can_manage)
        self.out_button.set_enabled(active and self._can_manage)
        self.check_button.set_enabled(has and self._can_manage)
        if not has:
            ctk.CTkLabel(self.detail, text="请选择左侧药品查看档案与批次",
                         font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=16)
            return

        ctk.CTkLabel(self.detail, text=f"{record['name']}（{record['code']}）",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        _detail_row(self.detail, "规格 / 剂型",
                    f"{record.get('spec') or '—'} / {record.get('dosage_form') or '—'}")
        _detail_row(self.detail, "单位 / 厂家",
                    f"{record.get('unit') or '—'} / {record.get('manufacturer') or '—'}")
        _detail_row(self.detail, "类别", record.get("category"))
        _detail_row(self.detail, "处方药", record.get("is_prescription_text"),
                    theme.severity_color(record.get("is_prescription_text")))
        _detail_row(self.detail, "库存量", f"{record['total_quantity']}"
                                           f"{record.get('unit') or ''}")
        _detail_row(self.detail, "下限 / 上限",
                    f"{record.get('stock_lower')} / {record.get('stock_upper')}")
        _detail_row(self.detail, "库存状态", record.get("stock_status"),
                    theme.severity_color(record.get("stock_status")))
        _detail_row(self.detail, "效期状态", record.get("expire_status"),
                    theme.severity_color(record.get("expire_status")))
        _detail_row(self.detail, "档案状态", record.get("status_text"),
                    theme.severity_color(record.get("status_text")))

        ctk.CTkFrame(self.detail, height=1, fg_color=theme.BORDER).pack(fill="x",
                                                                        pady=(10, 6))
        ctk.CTkLabel(self.detail, text="批次明细", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        batches = medicine_service.list_batches(record["id"])
        if not batches:
            ctk.CTkLabel(self.detail, text="暂无入库批次",
                         font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w")
        for batch in batches:
            line = ctk.CTkFrame(self.detail, fg_color=theme.SURFACE_FORM,
                                corner_radius=theme.RADIUS_TAG)
            line.pack(fill="x", pady=2)
            ctk.CTkLabel(
                line, text=f"{batch['batch_no']}｜{batch['quantity']}｜"
                           f"{batch['expire_date'] or '—'}",
                font=theme.FONT_SMALL, anchor="w", text_color=theme.TEXT_PRIMARY
            ).pack(side="left", padx=8, pady=4)
            StatusTag(line, text=batch["expire_status"],
                      level=batch["expire_status"]).pack(side="right", padx=8, pady=4)

        self.toggle_button.configure(
            text="停用药品" if record.get("status") else "启用药品")

    # ------------------------------------------------------------ 动作
    def _require_selection(self):
        if self.current is None:
            warn(self, "请先在左侧选中一种药品", "提示")
            return None
        return self.current

    def add_medicine(self):
        dialog = MedicineDialog(self, self.user, None)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def edit_medicine(self):
        record = self._require_selection()
        if record is None:
            return
        dialog = MedicineDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def toggle_medicine(self):
        record = self._require_selection()
        if record is None:
            return
        enable = not bool(record.get("status"))
        ok, message = medicine_service.set_medicine_status(
            record["id"], enable, self.user.username)
        if not ok:
            warn(self, message, "操作失败")
            return
        info(self, message, "操作完成")
        self.load_data()

    def delete_medicine(self):
        record = self._require_selection()
        if record is None:
            return
        if not confirm(self, f"确认删除药品「{record['name']}」？\n"
                             "已有出入库流水的药品无法删除，只能停用。", "删除确认"):
            return
        ok, message = medicine_service.delete_medicine(record["id"], self.user.username)
        if not ok:
            warn(self, message, "删除失败")
            return
        info(self, message, "删除完成")
        self.load_data()

    def stock_in(self):
        record = self._require_selection()
        if record is None:
            return
        dialog = StockInDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def stock_out(self):
        record = self._require_selection()
        if record is None:
            return
        dialog = StockOutDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def stock_check(self):
        record = self._require_selection()
        if record is None:
            return
        dialog = StockCheckDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def export_stock(self):
        if not self.rows:
            warn(self, "当前没有可导出的药品记录", "提示")
            return
        path = excel_service.export_table("药品库存台账", "药品库存台账",
                                          config.MEDICINE_EXPORT_COLUMNS, self.rows)
        info(self, f"已导出 {len(self.rows)} 条记录：\n{path}", "导出完成")


# ---------------------------------------------------------------- 药品档案对话框
class MedicineDialog(ctk.CTkToplevel):
    def __init__(self, master, user, record):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.record = record
        self.success = False
        self.inputs = {}
        self._build()

    def _build(self):
        title = "编辑药品档案" if self.record else "新增药品"
        _window, body = _dialog_shell(self, title, 660, 560)
        box = Card(body, title="药品档案")
        box.pack(fill="x")
        _build_fields(box.body, config.MEDICINE_FORM_FIELDS, self.inputs)

        hint = ctk.CTkLabel(body, text="编码唯一；库存下限用于库存预警，"
                                       "上限默认取下限的 3 倍。",
                            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        hint.pack(anchor="w", pady=(10, 0))
        self.hint = hint
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        DynamicButton(buttons, text="保存", style="primary", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))
        self._fill()

    def _fill(self):
        record = self.record or {}
        for key, _label, kind, options in config.MEDICINE_FORM_FIELDS:
            value = record.get(key)
            widget = self.inputs[key]
            if kind == "option":
                if key == "is_prescription":
                    widget.set("是" if value else "否")
                else:
                    widget.set(value or (list(options)[0] if options else ""))
            elif kind == "combo":
                if value:
                    widget.set(str(value))
            else:
                if value not in (None, ""):
                    widget.insert(0, str(value))
        if not self.record:
            self.inputs["stock_lower"].insert(0, str(config.STOCK_LOWER_DEFAULT))
            self.inputs["stock_upper"].insert(
                0, str(config.STOCK_LOWER_DEFAULT * config.STOCK_UPPER_RATIO))

    def _form_data(self):
        return {key: self.inputs[key].get()
                for key, _label, _kind, _options in config.MEDICINE_FORM_FIELDS}

    def _submit(self):
        ok, message = medicine_service.save_medicine(
            self.record["id"] if self.record else None, self._form_data(),
            self.user.username)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "保存成功")
        self.destroy()


# ---------------------------------------------------------------- 入库对话框
class StockInDialog(ctk.CTkToplevel):
    def __init__(self, master, user, medicine):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.medicine = medicine
        self.success = False
        self.inputs = {}
        self._build()

    def _build(self):
        _window, body = _dialog_shell(self, f"药品入库 — {self.medicine['name']}",
                                      620, 480)
        specs = [("batch_no", "批号 *", "entry", None),
                 ("quantity", "入库数量 *", "entry", None),
                 ("produce_date", "生产日期", "entry", None),
                 ("expire_date", "有效期 *", "entry", None),
                 ("supplier", "供应商", "entry", None),
                 ("location", "存放位置", "entry", None)]
        box = Card(body, title="入库信息")
        box.pack(fill="x")
        _build_fields(box.body, specs, self.inputs)

        hint = ctk.CTkLabel(body, text="有效期格式 2026-12-31；同批号将自动合并数量。",
                            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        hint.pack(anchor="w", pady=(10, 0))
        self.hint = hint
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        DynamicButton(buttons, text="确认入库", style="success", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))

    def _submit(self):
        data = {key: widget.get() for key, widget in self.inputs.items()}
        ok, message = medicine_service.stock_in(
            self.medicine["id"], data, self.user.username)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "入库成功")
        self.destroy()


# ---------------------------------------------------------------- 出库对话框
class StockOutDialog(ctk.CTkToplevel):
    def __init__(self, master, user, medicine, preset_person=None):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.medicine = medicine
        self.preset_person = preset_person
        self.success = False
        self.inputs = {}
        self.batch_map = {}
        self.person_map = _person_option_map()
        self._build()

    def _build(self):
        _window, body = _dialog_shell(self, f"药品出库 — {self.medicine['name']}",
                                      620, 500)

        self.batches = [batch for batch in medicine_service.list_batches(self.medicine["id"])
                        if batch["quantity"] > 0]

        box = Card(body, title="出库信息")
        box.pack(fill="x")
        form = box.body

        cell = ctk.CTkFrame(form, fg_color="transparent")
        cell.grid(row=0, column=0, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(cell, text="出库批号 *", font=theme.FONT_SMALL, width=132,
                     anchor="w", text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        labels = []
        for batch in self.batches:
            label = f"{batch['batch_no']}（库存 {batch['quantity']}）"
            if batch["expire_status"] == "已过期":
                label += " 已过期"
            self.batch_map[label] = batch["batch_no"]
            labels.append(label)
        self.batch_menu = ctk.CTkOptionMenu(
            cell, values=labels or ["（无可出库批次）"], width=210, height=32,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.batch_menu.pack(anchor="w")
        if labels:
            self.batch_menu.set(labels[0])

        qty_cell = ctk.CTkFrame(form, fg_color="transparent")
        qty_cell.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(qty_cell, text="出库数量 *", font=theme.FONT_SMALL, width=132,
                     anchor="w", text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        self.inputs["quantity"] = entry(qty_cell, "本次出库数量", width=210)
        self.inputs["quantity"].pack(anchor="w")

        person_cell = ctk.CTkFrame(form, fg_color="transparent")
        person_cell.grid(row=1, column=0, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(person_cell, text="领用人（可关联档案）", font=theme.FONT_SMALL,
                     width=132, anchor="w",
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        person_labels = ["（不关联人员）"] + list(self.person_map.keys())
        self.person_menu = ctk.CTkOptionMenu(
            person_cell, values=person_labels, width=210, height=32,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.person_menu.pack(anchor="w")
        preset_label = next((label for label, pid in self.person_map.items()
                             if pid == self.preset_person), None)
        self.person_menu.set(preset_label or person_labels[0])

        purpose_cell = ctk.CTkFrame(form, fg_color="transparent")
        purpose_cell.grid(row=1, column=1, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(purpose_cell, text="用途", font=theme.FONT_SMALL, width=132,
                     anchor="w", text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        self.purpose_entry = entry(purpose_cell, "如 慢病随访 / 急救", width=210)
        self.purpose_entry.pack(anchor="w")

        hint = ctk.CTkLabel(body, text="已过期批次禁止出库，请隔离销毁。",
                            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        hint.pack(anchor="w", pady=(10, 0))
        self.hint = hint
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        DynamicButton(buttons, text="确认出库", style="warning", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))

    def _submit(self):
        label = self.batch_menu.get()
        batch_no = self.batch_map.get(label, "")
        person_label = self.person_menu.get()
        data = {
            "batch_no": batch_no,
            "quantity": self.inputs["quantity"].get(),
            "person_id": self.person_map.get(person_label),
            "purpose": self.purpose_entry.get(),
        }
        ok, message = medicine_service.stock_out(
            self.medicine["id"], data, self.user.username)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "出库成功")
        self.destroy()


# ---------------------------------------------------------------- 盘点对话框
class StockCheckDialog(ctk.CTkToplevel):
    def __init__(self, master, user, medicine):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.medicine = medicine
        self.success = False
        self.batch_map = {}
        self._build()

    def _build(self):
        _window, body = _dialog_shell(self, f"药品盘点 — {self.medicine['name']}",
                                      600, 420)
        self.batches = medicine_service.list_batches(self.medicine["id"])

        box = Card(body, title="盘点信息")
        box.pack(fill="x")
        form = box.body

        cell = ctk.CTkFrame(form, fg_color="transparent")
        cell.grid(row=0, column=0, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(cell, text="盘点批号 *", font=theme.FONT_SMALL, width=132, anchor="w",
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        labels = []
        for batch in self.batches:
            label = f"{batch['batch_no']}（账面 {batch['quantity']}）"
            self.batch_map[label] = batch["batch_no"]
            labels.append(label)
        self.batch_menu = ctk.CTkOptionMenu(
            cell, values=labels or ["（无批次）"], width=210, height=32,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.batch_menu.pack(anchor="w")
        if labels:
            self.batch_menu.set(labels[0])

        qty = ctk.CTkFrame(form, fg_color="transparent")
        qty.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=6)
        ctk.CTkLabel(qty, text="实盘数量 *", font=theme.FONT_SMALL, width=132, anchor="w",
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        self.actual_entry = entry(qty, "实际清点数量", width=210)
        self.actual_entry.pack(anchor="w")

        hint = ctk.CTkLabel(body, text="实盘与账面不一致时自动生成盈亏记录。",
                            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        hint.pack(anchor="w", pady=(10, 0))
        self.hint = hint
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        DynamicButton(buttons, text="确认盘点", style="secondary", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))

    def _submit(self):
        data = {"batch_no": self.batch_map.get(self.batch_menu.get(), ""),
                "actual_quantity": self.actual_entry.get()}
        ok, message = medicine_service.stock_check(
            self.medicine["id"], data, self.user.username)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "盘点完成")
        self.destroy()


# ================================================================ 医疗设备台账
class EquipmentLedgerPage(ctk.CTkFrame):
    TITLE = "医疗设备台账"
    DESC = "设备档案、校准 / 维保到期提醒（提前 30 天黄警）与一艇一册急救设备核对。"

    COLUMNS = [
        {"key": "name", "title": "设备名称", "width": 118},
        {"key": "model", "title": "型号", "width": 92},
        {"key": "serial_no", "title": "设备编号", "width": 104},
        {"key": "manufacturer", "title": "生产厂家", "width": 130},
        {"key": "location", "title": "存放位置", "width": 96},
        {"key": "keeper", "title": "责任人", "width": 74},
        {"key": "status", "title": "状态", "width": 62,
         "tag": True, "level_key": "status"},
        {"key": "next_calibration", "title": "下次维保", "width": 96},
        {"key": "maintain_status", "title": "维保状态", "width": 84,
         "tag": True, "level_key": "maintain_status"},
        {"key": "keep_boat_no", "title": "配置艇", "width": 76},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.current = None
        self._build()
        self.load_data()

    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")
        filters = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))
        filter_label(filters, "关键字").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.keyword_entry = entry(filters, "名称 / 编号 / 型号 / 责任人", width=190)
        self.keyword_entry.pack(side="left")
        filter_label(filters, "状态").pack(side="left", padx=(16, 6))
        self.status_menu = ctk.CTkOptionMenu(
            filters, values=["全部"] + list(config.EQUIPMENT_STATUSES), width=96,
            height=34, font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.status_menu.pack(side="left")
        self.due_only = ctk.CTkCheckBox(
            filters, text="仅维保到期", font=theme.FONT_BODY, width=108, height=26,
            checkbox_width=20, checkbox_height=20, text_color=theme.TEXT_PRIMARY,
            fg_color=theme.SECONDARY, hover_color=theme.hover(theme.SECONDARY))
        self.due_only.pack(side="left", padx=(16, 0))

        DynamicButton(filters, text="查询", style="primary", width=84,
                      command=self.load_data).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_filters).pack(side="left")
        DynamicButton(filters, text="一艇一册", style="secondary", width=100,
                      command=self.boat_check).pack(side="right",
                                                     padx=(0, theme.PAD_CARD))
        if self.user.can("equipment.create"):
            DynamicButton(filters, text="新增设备", style="primary", width=100,
                          command=self.add_equipment).pack(side="right", padx=(0, 8))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        # 固定宽度的详情面板先以 side="right" 占位，否则会被 expand 的表格挤成 1px
        right = ctk.CTkFrame(body, fg_color=theme.SURFACE_CARD, width=372,
                             corner_radius=theme.RADIUS_CARD)
        right.pack(side="right", fill="both", padx=(theme.GAP, 0))
        right.pack_propagate(False)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        self.table = DataTable(left, self.COLUMNS, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)

        self._build_detail(right)

    def _build_detail(self, parent):
        ctk.CTkLabel(parent, text="设备详情", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w",
                                                         padx=theme.PAD_CARD,
                                                         pady=(12, 4))
        self.detail = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.detail.pack(fill="both", expand=True, padx=theme.PAD_CARD, pady=(0, 6))
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", padx=theme.PAD_CARD, pady=(0, 12))
        self.edit_button = DynamicButton(actions, text="编辑设备", style="primary",
                                         width=118, command=self.edit_equipment)
        self.delete_button = DynamicButton(actions, text="删除设备", style="danger",
                                           width=118, command=self.delete_equipment)
        self.edit_button.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.delete_button.grid(row=0, column=1, padx=(0, 8), sticky="w")
        if not self.user.can("equipment.update"):
            self.edit_button.set_enabled(False)
        if not self.user.can("equipment.delete"):
            self.delete_button.set_enabled(False)
        self._render_detail(None)

    def reset_filters(self):
        self.keyword_entry.delete(0, "end")
        self.status_menu.set("全部")
        self.due_only.deselect()
        self.load_data()

    def load_data(self):
        status = self.status_menu.get()
        self.rows = equipment_service.list_equipment(
            keyword=self.keyword_entry.get().strip() or None,
            status=None if status in ("", "全部") else status,
            only_due=bool(self.due_only.get()))
        self.table.set_data(self.rows)
        self.current = None
        self._render_detail(None)

    def _on_select(self, record):
        self.current = record
        self._render_detail(record)

    def _render_detail(self, record):
        for child in self.detail.winfo_children():
            child.destroy()
        self.edit_button.set_enabled(self.user.can("equipment.update"))
        self.delete_button.set_enabled(self.user.can("equipment.delete"))
        if record is None:
            ctk.CTkLabel(self.detail, text="请选择左侧设备查看档案",
                         font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=16)
            return
        ctk.CTkLabel(self.detail, text=f"{record['name']}（{record['serial_no']}）",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        _detail_row(self.detail, "型号 / 厂家",
                    f"{record.get('model') or '—'} / {record.get('manufacturer') or '—'}")
        _detail_row(self.detail, "购置 / 启用",
                    f"{record.get('purchase_date') or '—'} / "
                    f"{record.get('start_date') or '—'}")
        _detail_row(self.detail, "存放位置", record.get("location"))
        _detail_row(self.detail, "责任人", record.get("keeper"))
        _detail_row(self.detail, "状态", record.get("status"),
                    theme.severity_color(record.get("status")))
        _detail_row(self.detail, "上次校准", record.get("last_calibration"))
        _detail_row(self.detail, "下次校准", record.get("next_calibration"))
        _detail_row(self.detail, "维保状态", record.get("maintain_status"),
                    theme.severity_color(record.get("maintain_status")))
        _detail_row(self.detail, "配置救生艇", record.get("keep_boat_no"))
        _detail_row(self.detail, "使用记录", f"{record.get('use_count') or 0} 次")

    def _require_selection(self):
        if self.current is None:
            warn(self, "请先在左侧选中一台设备", "提示")
            return None
        return self.current

    def add_equipment(self):
        dialog = EquipmentDialog(self, self.user, None)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def edit_equipment(self):
        record = self._require_selection()
        if record is None:
            return
        dialog = EquipmentDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def delete_equipment(self):
        record = self._require_selection()
        if record is None:
            return
        if not confirm(self, f"确认删除设备「{record['name']}」？\n"
                             "已有使用记录的设备无法删除，只能改为报废。", "删除确认"):
            return
        ok, message = equipment_service.delete_equipment(record["id"], self.user.username)
        if not ok:
            warn(self, message, "删除失败")
            return
        info(self, message, "删除完成")
        self.load_data()

    def boat_check(self):
        dialog = BoatCheckDialog(self, self.user)
        dialog.grab_set()
        self.wait_window(dialog)


# ---------------------------------------------------------------- 设备档案对话框
class EquipmentDialog(ctk.CTkToplevel):
    def __init__(self, master, user, record):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.record = record
        self.success = False
        self.inputs = {}
        self._build()

    def _build(self):
        title = "编辑设备档案" if self.record else "新增设备"
        _window, body = _dialog_shell(self, title, 700, 620)
        box = Card(body, title="设备档案")
        box.pack(fill="x")
        _build_fields(box.body, config.EQUIPMENT_FORM_FIELDS, self.inputs)
        hint = ctk.CTkLabel(body, text="设备编号唯一；下次校准 / 维保用于到期提醒。",
                            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        hint.pack(anchor="w", pady=(10, 0))
        self.hint = hint
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        DynamicButton(buttons, text="保存", style="primary", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))
        self._fill()

    def _fill(self):
        record = self.record or {}
        for key, _label, kind, options in config.EQUIPMENT_FORM_FIELDS:
            value = record.get(key)
            widget = self.inputs[key]
            if kind == "option":
                widget.set(value or (list(options)[0] if options else ""))
            elif kind == "boat":
                widget.set(value or "")
            else:
                if value not in (None, ""):
                    widget.insert(0, str(value))

    def _form_data(self):
        return {key: self.inputs[key].get()
                for key, _label, _kind, _options in config.EQUIPMENT_FORM_FIELDS}

    def _submit(self):
        ok, message = equipment_service.save_equipment(
            self.record["id"] if self.record else None, self._form_data(),
            self.user.username)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "保存成功")
        self.destroy()


# ---------------------------------------------------------------- 一艇一册对话框
class BoatCheckDialog(ctk.CTkToplevel):
    def __init__(self, master, user):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self._build()

    def _build(self):
        _window, body = _dialog_shell(self, "一艇一册 — 急救设备核对", 780, 560)

        pick = ctk.CTkFrame(body, fg_color="transparent")
        pick.pack(fill="x")
        ctk.CTkLabel(pick, text="救生艇编号", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self.boat_menu = ctk.CTkOptionMenu(
            pick, values=equipment_service.boat_options() or ["（未配置）"], width=160,
            height=34, font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.boat_menu.pack(side="left")
        DynamicButton(pick, text="核对", style="primary", width=84,
                      command=self.load_checklist).pack(side="left", padx=(10, 0))
        self.summary = ctk.CTkLabel(pick, text="", font=theme.FONT_SMALL,
                                    text_color=theme.TEXT_SECONDARY)
        self.summary.pack(side="left", padx=(16, 0))

        columns = [
            {"key": "name", "title": "设备名称", "width": 130},
            {"key": "model", "title": "型号", "width": 100},
            {"key": "serial_no", "title": "设备编号", "width": 110},
            {"key": "status", "title": "状态", "width": 70, "tag": True,
             "level_key": "status"},
            {"key": "maintain_status", "title": "维保状态", "width": 90, "tag": True,
             "level_key": "maintain_status"},
        ]
        self.table = DataTable(body, columns, page_size=20)
        self.table.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self.load_checklist()

    def load_checklist(self):
        result = equipment_service.boat_checklist(self.boat_menu.get())
        self.table.set_data(result["rows"])
        if result["total"] == 0:
            self.summary.configure(text="该艇尚未配置设备", text_color=theme.TEXT_SECONDARY)
            return
        ok = result["abnormal"] == 0
        self.summary.configure(
            text=f"共 {result['total']} 台｜齐全 {result['normal']}｜异常 {result['abnormal']}"
                 f"（{'配置齐全' if ok else '存在非在用或维保异常设备'}）",
            text_color=theme.SUCCESS if ok else theme.DANGER)


# ================================================================ 效期与库存预警
class SupplyWarningPage(ctk.CTkFrame):
    TITLE = "效期与库存预警"
    DESC = ("药品效期（≤3 月黄警 / ≤1 月红警 / 已过期禁止出库）、"
            "库存下限预警与设备维保到期统一聚合，急救药品置顶。")

    COLUMNS = [
        {"key": "source", "title": "来源", "width": 88},
        {"key": "code", "title": "编码 / 编号", "width": 108},
        {"key": "name", "title": "名称", "width": 140},
        {"key": "category", "title": "类别", "width": 70},
        {"key": "batch_no", "title": "批号", "width": 96},
        {"key": "detail", "title": "预警详情", "width": 380},
        {"key": "level", "title": "级别", "width": 84, "tag": True, "level_key": "level"},
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
        filter_label(filters, "来源").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.source_menu = ctk.CTkOptionMenu(
            filters, values=["全部"] + list(config.SUPPLY_WARNING_SOURCES), width=112,
            height=34, font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.source_menu.pack(side="left")
        filter_label(filters, "级别").pack(side="left", padx=(16, 6))
        self.level_menu = ctk.CTkOptionMenu(
            filters, values=["全部", "红色报警", "黄色预警", "提示"], width=104,
            height=34, font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.level_menu.pack(side="left")
        DynamicButton(filters, text="查询", style="primary", width=84,
                      command=self.load_data).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_filters).pack(side="left")
        DynamicButton(filters, text="导出预警", style="secondary", width=100,
                      command=self.export_warnings).pack(side="right",
                                                          padx=(0, theme.PAD_CARD))

        self.table = DataTable(self, self.COLUMNS, page_size=30)
        self.table.pack(fill="both", expand=True, pady=(theme.GAP, 0))

    def _metric_card(self, label, value, color):
        card = ctk.CTkFrame(self.metrics, fg_color=theme.SURFACE_CARD,
                            corner_radius=theme.RADIUS_CARD,
                            border_width=1, border_color=theme.BORDER_LIGHT)
        card.pack(side="left", fill="x", expand=True, padx=(0, theme.GAP))
        ctk.CTkFrame(card, height=theme.ACCENT_BAR, corner_radius=0,
                     fg_color=color).pack(fill="x")
        ctk.CTkLabel(card, text=str(value), font=theme.FONT_METRIC,
                     text_color=color).pack(anchor="w", padx=theme.PAD_CARD,
                                            pady=(8, 0))
        ctk.CTkLabel(card, text=label, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w",
                                                           padx=theme.PAD_CARD,
                                                           pady=(0, 8))

    def reset_filters(self):
        self.source_menu.set("全部")
        self.level_menu.set("全部")
        self.load_data()

    def load_data(self):
        source = self.source_menu.get()
        level = self.level_menu.get()
        warnings = medicine_service.medicine_warnings(
            source=None if source in ("", "全部") else source,
            level=None if level in ("", "全部") else level)
        if source in ("", "全部", "设备维保"):
            warnings += equipment_service.equipment_warnings()
            if level not in ("", "全部"):
                warnings = [item for item in warnings if item["level"] == level]
            warnings.sort(key=lambda item: (
                0 if item.get("category") == "急救" else 1,
                0 if item["level"] == "红色报警" else 1,
                item["sort_urgency"]))
        self.rows = warnings
        self.table.set_data(warnings)
        self._refresh_metrics()

    def _refresh_metrics(self):
        for child in self.metrics.winfo_children():
            child.destroy()
        medicine = medicine_service.medicine_summary()
        equipment = equipment_service.equipment_summary()
        self._metric_card("药品红色报警", medicine["red"], theme.DANGER)
        self._metric_card("药品黄色预警", medicine["yellow"], theme.WARNING)
        self._metric_card("已过期批次", medicine["expired"], theme.DANGER)
        self._metric_card("设备维保异常",
                          equipment["red"] + equipment["yellow"], theme.WARNING)

    def export_warnings(self):
        if not self.rows:
            warn(self, "当前没有可导出的预警记录", "提示")
            return
        columns = [("来源", "source"), ("编码/编号", "code"), ("名称", "name"),
                   ("类别", "category"), ("批号", "batch_no"),
                   ("预警详情", "detail"), ("级别", "level")]
        path = excel_service.export_table("物资预警", "物资预警", columns, self.rows)
        info(self, f"已导出 {len(self.rows)} 条预警：\n{path}", "导出完成")