# -*- coding: utf-8 -*-
"""系统设置（超级用户专属）：账号管理、参数配置、备份恢复、日志查看四个分区。

分区按其权限项动态渲染：user.manage / config.manage / backup.manage / log.view。
业务校验全部由 auth_service / system_service 承担，界面只负责录入与呈现。
"""

import customtkinter as ctk

import config
from services import auth_service, system_service
from ui import theme
from ui.widgets import (Card, DataTable, DynamicButton, confirm, entry, field_label,
                        info, page_header, warn)


def _shell(window, title, width, height):
    """在给定对话框窗口内构建「标题条 + 可滚动内容区」，返回内容区。"""
    window.title(title)
    window.resizable(False, False)
    window.transient(window.master.winfo_toplevel())
    window.geometry(f"{width}x{height}")
    head = ctk.CTkFrame(window, fg_color=theme.PRIMARY, corner_radius=0, height=54)
    head.pack(fill="x")
    head.pack_propagate(False)
    ctk.CTkLabel(head, text=title, font=theme.FONT_SUBTITLE,
                 text_color=theme.TEXT_ON_PRIMARY).pack(pady=(14, 0))
    body = ctk.CTkScrollableFrame(window, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=20, pady=14)
    window.after(120, window.focus_force)
    return body


def _option_menu(parent, values, width=140):
    accent = theme.active_accent()
    menu = ctk.CTkOptionMenu(
        parent, values=list(values), width=width, height=34, font=theme.FONT_BODY,
        fg_color=accent, button_color=theme.hover(accent),
        button_hover_color=theme.active(accent),
        dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
    menu.set(values[0])
    return menu


# ---------------------------------------------------------------- 通用表单对话框
class FormDialog(ctk.CTkToplevel):
    """通用表单对话框：specs = [(字段, 标签, 类型, 选项)]，类型为 entry / password / option。"""

    def __init__(self, master, title, specs, on_submit, width=400, height=330):
        super().__init__(master)
        self.on_submit = on_submit
        self.inputs = {}
        self.values = None
        body = _shell(self, title, width, height)
        for key, label, kind, options in specs:
            ctk.CTkLabel(body, text=label, font=theme.FONT_SMALL, anchor="w",
                         text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(8, 2))
            if kind == "option":
                widget = _option_menu(body, options, width=width - 84)
            else:
                widget = entry(body, "", width=width - 84,
                               show="*" if kind == "password" else None)
            widget.pack(fill="x")
            self.inputs[key] = widget

        bar = ctk.CTkFrame(body, fg_color="transparent")
        bar.pack(fill="x", pady=(18, 0))
        DynamicButton(bar, text="取消", style="ghost", width=90,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        DynamicButton(bar, text="确定", style="primary", width=90,
                      command=self._submit).pack(side="right")

    def _submit(self):
        parent = self.master
        data = {key: widget.get() for key, widget in self.inputs.items()}
        ok, message = self.on_submit(data)
        if not ok:
            warn(self, message)
            return
        self.values = data
        self.destroy()
        info(parent, message)


# ================================================================ 系统设置页
class SystemSettingsPage(ctk.CTkFrame):
    """四个分区共用一页，通过顶部分段按钮切换，按权限动态渲染。"""

    TITLE = "系统设置"
    DESC = ("超级用户专属：用户账号管理、健康阈值与预警参数配置、"
            "数据备份 / 恢复、操作与登录日志查看。")

    # (分区名, 所需权限, 构建方法名)
    TABS = (("账号管理", "user.manage", "_build_accounts"),
            ("参数配置", "config.manage", "_build_params"),
            ("备份恢复", "backup.manage", "_build_backup"),
            ("日志查看", "log.view", "_build_logs"))

    ACCOUNT_COLUMNS = [
        {"key": "username", "title": "账号", "width": 130},
        {"key": "role_label", "title": "角色", "width": 100},
        {"key": "status_text", "title": "状态", "width": 76,
         "tag": True, "level_key": "status_text"},
        {"key": "lock_text", "title": "锁定", "width": 76,
         "tag": True, "level_key": "lock_text"},
        {"key": "created_at", "title": "创建时间", "width": 158},
        {"key": "last_login", "title": "最近登录", "width": 158},
    ]

    OP_LOG_COLUMNS = [
        {"key": "op_time", "title": "时间", "width": 150},
        {"key": "operator", "title": "操作人", "width": 100},
        {"key": "module", "title": "模块", "width": 110},
        {"key": "action", "title": "操作", "width": 110},
        {"key": "target", "title": "对象", "width": 120},
        {"key": "detail", "title": "明细", "width": 320},
    ]

    LOGIN_LOG_COLUMNS = [
        {"key": "login_time", "title": "时间", "width": 150},
        {"key": "username", "title": "账号", "width": 120},
        {"key": "ip", "title": "来源", "width": 110},
        {"key": "result", "title": "结果", "width": 76,
         "tag": True, "level_key": "result"},
        {"key": "detail", "title": "明细", "width": 360},
    ]

    BACKUP_COLUMNS = [
        {"key": "name", "title": "备份文件", "width": 240},
        {"key": "time", "title": "备份时间", "width": 170},
        {"key": "size_kb", "title": "大小(KB)", "width": 110, "anchor": "center"},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.tables = {}
        self.current_rows = {}
        self.param_inputs = {}
        self.threshold_inputs = {}
        self.log_kind = "op"
        self._build()

    # ------------------------------------------------------------ 骨架
    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        self.available = [(name, method) for name, perm, method in self.TABS
                          if self.user.can(perm)]
        if not self.available:
            ctk.CTkLabel(self, text="当前账号没有系统设置权限",
                         font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(pady=40)
            return

        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        bar.pack(fill="x", pady=(theme.GAP, 0))
        if len(self.available) > 1:
            self.tab_bar = ctk.CTkSegmentedButton(
                bar, values=[name for name, _method in self.available],
                font=theme.FONT_BODY, height=32, selected_color=theme.SECONDARY,
                unselected_color=theme.SURFACE_MUTED,
                selected_hover_color=theme.hover(theme.SECONDARY),
                unselected_hover_color=theme.ROW_HOVER,
                text_color=theme.TEXT_PRIMARY, command=self._switch)
            self.tab_bar.set(self.available[0][0])
            self.tab_bar.pack(side="left", padx=theme.PAD_CARD, pady=12)
        else:
            ctk.CTkLabel(bar, text=self.available[0][0], font=theme.FONT_SUBTITLE,
                         text_color=theme.TEXT_PRIMARY).pack(side="left",
                                                             padx=theme.PAD_CARD,
                                                             pady=12)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self._switch(self.available[0][0])

    def _switch(self, name):
        """切换分区：清空内容区后直接构建（表格页需要直接铺满，不能套滚动框）。"""
        for child in self.body.winfo_children():
            child.destroy()
        method = dict(self.available).get(name)
        if method is None:
            return
        getattr(self, method)(self.body)

    # ============================================================ 账号管理
    def _build_accounts(self, parent):
        filters = ctk.CTkFrame(parent, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x")
        field_label(filters, "账号").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.account_keyword = entry(filters, "账号名称", width=150)
        self.account_keyword.pack(side="left")

        field_label(filters, "角色").pack(side="left", padx=(16, 6))
        self.account_role = _option_menu(
            filters, ["全部"] + [config.ROLE_LABELS[key] for key in config.ROLE_OPTIONS],
            width=110)
        self.account_role.pack(side="left")

        field_label(filters, "状态").pack(side="left", padx=(16, 6))
        self.account_status = _option_menu(filters, ["全部", "启用", "停用"], width=96)
        self.account_status.pack(side="left")

        DynamicButton(filters, text="查询", style="primary", width=84,
                      command=self.load_accounts).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_account_filters).pack(side="left")
        DynamicButton(filters, text="新增账号", style="primary", width=104,
                      command=self.add_account).pack(side="right",
                                                     padx=(0, theme.PAD_CARD))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", pady=(theme.GAP, 0))
        ctk.CTkLabel(actions, text="选中一行后可重置密码、调整角色或停用启用。",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        DynamicButton(actions, text="解锁账号", style="ghost", width=100,
                      command=self.unlock_account).pack(side="right", padx=(8, 0))
        DynamicButton(actions, text="停用 / 启用", style="secondary", width=112,
                      command=self.toggle_account).pack(side="right", padx=(8, 0))
        DynamicButton(actions, text="调整角色", style="secondary", width=100,
                      command=self.change_role).pack(side="right", padx=(8, 0))
        DynamicButton(actions, text="重置密码", style="warning", width=100,
                      command=self.reset_password).pack(side="right")

        self.tables["accounts"] = DataTable(parent, self.ACCOUNT_COLUMNS,
                                           on_select=self._select("accounts"))
        self.tables["accounts"].pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self.load_accounts()

    def _select(self, key):
        def _handler(record):
            self.current_rows[key] = record
        return _handler

    def reset_account_filters(self):
        self.account_keyword.delete(0, "end")
        self.account_role.set("全部")
        self.account_status.set("全部")
        self.load_accounts()

    def load_accounts(self):
        role_label = self.account_role.get()
        status_text = self.account_status.get()
        role = None
        if role_label != "全部":
            role = next((key for key, label in config.ROLE_LABELS.items()
                         if label == role_label), None)
        status = None
        if status_text != "全部":
            status = 1 if status_text == "启用" else 0
        self.tables["accounts"].set_data(auth_service.list_users(
            keyword=self.account_keyword.get().strip() or None, role=role,
            status=status))

    def _selected_account(self):
        record = self.current_rows.get("accounts")
        if not record:
            warn(self, "请先在列表中选择一个账号")
            return None
        return record

    def add_account(self):
        roles = [config.ROLE_LABELS[key] for key in config.ROLE_OPTIONS]
        dialog = FormDialog(self, "新增账号", [
            ("username", "账号名称 *", "entry", None),
            ("password", "初始密码 *", "password", None),
            ("confirm", "确认密码 *", "password", None),
            ("role", "账号角色 *", "option", roles),
        ], lambda data: self._submit_account(data))
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.values:
            self.load_accounts()

    def _submit_account(self, data):
        if data["password"] != data["confirm"]:
            return False, "两次输入的密码不一致"
        role = next((key for key, label in config.ROLE_LABELS.items()
                     if label == data["role"]), None)
        return auth_service.create_user(data["username"], data["password"], role,
                                       operator=self.user.username)

    def reset_password(self):
        record = self._selected_account()
        if record is None:
            return
        dialog = FormDialog(self, f"重置密码：{record['username']}", [
            ("password", "新密码 *", "password", None),
            ("confirm", "确认密码 *", "password", None),
        ], lambda data: self._submit_reset(record, data), height=280)
        dialog.grab_set()
        self.wait_window(dialog)

    def _submit_reset(self, record, data):
        if data["password"] != data["confirm"]:
            return False, "两次输入的密码不一致"
        return auth_service.reset_user_password(record["id"], data["password"],
                                                operator=self.user.username)

    def change_role(self):
        record = self._selected_account()
        if record is None:
            return
        roles = [config.ROLE_LABELS[key] for key in config.ROLE_OPTIONS]
        dialog = FormDialog(self, f"调整角色：{record['username']}", [
            ("role", "账号角色 *", "option", roles),
        ], lambda data: self._submit_role(record, data), height=240)
        dialog.inputs["role"].set(record["role_label"])
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.values:
            self.load_accounts()

    def _submit_role(self, record, data):
        role = next((key for key, label in config.ROLE_LABELS.items()
                     if label == data["role"]), None)
        return auth_service.update_user_role(record["id"], role,
                                             operator=self.user.username)

    def toggle_account(self):
        record = self._selected_account()
        if record is None:
            return
        enabled = record["status"] != 1
        action = "启用" if enabled else "停用"
        if not confirm(self, f"确定要{action}账号 {record['username']} 吗？", "账号操作"):
            return
        ok, message = auth_service.set_user_status(record["id"], enabled,
                                                   operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self.load_accounts()

    def unlock_account(self):
        record = self._selected_account()
        if record is None:
            return
        ok, message = auth_service.unlock_user(record["id"], operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self.load_accounts()

    # ============================================================ 参数配置
    def _build_params(self, parent):
        self.param_inputs = {}
        self.threshold_inputs = {}
        holder = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        holder.pack(fill="both", expand=True)
        self._build_run_params(holder)
        self._build_health_params(holder)

    def _build_run_params(self, parent):
        card = Card(parent, title="预警与运行参数")
        card.pack(fill="x")
        grid = ctk.CTkFrame(card.body, fg_color="transparent")
        grid.pack(fill="x")

        for index, item in enumerate(system_service.list_params()):
            row, column = divmod(index, 2)
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=row, column=column, sticky="w", padx=(0, 28), pady=6)
            ctk.CTkLabel(cell, text=f"{item['label']}（{item['unit']}）",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_PRIMARY,
                         width=170, anchor="w").pack(side="left")
            widget = entry(cell, "", width=90)
            widget.insert(0, "" if item["value"] is None else str(item["value"]))
            widget.pack(side="left")
            ctk.CTkLabel(cell, text=f"{item['min']}–{item['max']}", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(side="left", padx=(8, 0))
            self.param_inputs[item["key"]] = widget

        bar = ctk.CTkFrame(card.body, fg_color="transparent")
        bar.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(bar, text="住井与药品效期需保持大小关系：黄警 ≥ 红警（阈值越严数字越大）。",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        DynamicButton(bar, text="保存参数", style="primary", width=104,
                      command=self.save_params).pack(side="right")

    def _build_health_params(self, parent):
        card = Card(parent, title="健康指标阈值")
        card.pack(fill="x", pady=(theme.GAP, 0))
        grid = ctk.CTkFrame(card.body, fg_color="transparent")
        grid.pack(fill="x")

        headers = ("指标", "正常下限", "正常上限", "黄警阈值", "红警阈值")
        for column, title in enumerate(headers):
            ctk.CTkLabel(grid, text=title, font=theme.FONT_SMALL, width=110,
                         anchor="w", text_color=theme.TEXT_SECONDARY).grid(
                row=0, column=column, sticky="w", pady=(0, 4))

        for index, item in enumerate(system_service.health_thresholds(), start=1):
            ctk.CTkLabel(grid, text=f"{item['label']}（{item.get('unit', '')}）",
                         font=theme.FONT_SMALL, width=110, anchor="w",
                         text_color=theme.TEXT_PRIMARY).grid(row=index, column=0,
                                                             sticky="w", pady=4)
            fields = system_service.threshold_fields(item)
            inputs = {}
            for column, field in enumerate(fields, start=1):
                widget = entry(grid, "", width=86)
                value = item.get(field)
                widget.insert(0, "" if value is None else f"{value:g}")
                widget.grid(row=index, column=column, sticky="w", pady=4)
                inputs[field] = widget
            self.threshold_inputs[item["key"]] = inputs

        bar = ctk.CTkFrame(card.body, fg_color="transparent")
        bar.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(bar, text="低值异常指标（如高密度脂蛋白）按「红警 ≤ 黄警 ≤ 正常」填写。",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        DynamicButton(bar, text="保存阈值", style="primary", width=104,
                      command=self.save_health).pack(side="right")

    def save_params(self):
        values = {key: widget.get() for key, widget in self.param_inputs.items()}
        ok, message = system_service.save_params(values, operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self._switch("参数配置")

    def save_health(self):
        values = {key: {field: widget.get() for field, widget in inputs.items()}
                  for key, inputs in self.threshold_inputs.items()}
        ok, message = system_service.save_health_thresholds(
            values, operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self._switch("参数配置")

    # ============================================================ 备份恢复
    def _build_backup(self, parent):
        card = Card(parent, title="数据备份")
        card.pack(fill="x")
        ctk.CTkLabel(card.body,
                     text=f"每日首次启动自动备份到 backup/ 目录，保留最近 "
                          f"{config.BACKUP_KEEP} 份；恢复前会自动留存一份当前数据。",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
                     anchor="w", justify="left", wraplength=720).pack(anchor="w")
        bar = ctk.CTkFrame(card.body, fg_color="transparent")
        bar.pack(fill="x", pady=(12, 0))
        DynamicButton(bar, text="立即备份", style="primary", width=100,
                      command=self.create_backup).pack(side="left")
        DynamicButton(bar, text="刷新列表", style="ghost", width=100,
                      command=self.load_backups).pack(side="left", padx=(10, 0))
        DynamicButton(bar, text="恢复选中备份", style="danger", width=124,
                      command=self.restore_backup).pack(side="right")

        self.tables["backups"] = DataTable(parent, self.BACKUP_COLUMNS,
                                           on_select=self._select("backups"),
                                           page_size=20)
        self.tables["backups"].pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self.load_backups()

    def load_backups(self):
        self.tables["backups"].set_data(system_service.list_backups())

    def create_backup(self):
        ok, message = system_service.create_backup(operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self.load_backups()

    def restore_backup(self):
        record = self.current_rows.get("backups")
        if not record:
            warn(self, "请先在列表中选择一个备份文件")
            return
        if not confirm(self, f"确定用 {record['name']} 覆盖当前数据库吗？\n"
                             "恢复前会自动备份当前数据，恢复后需重新查看各模块。",
                       "恢复确认"):
            return
        ok, message = system_service.restore_backup(record["name"],
                                                    operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self.load_backups()
            self.app.refresh_status()

    # ============================================================ 日志查看
    def _build_logs(self, parent):
        is_op = self.log_kind == "op"
        bar = ctk.CTkFrame(parent, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        bar.pack(fill="x")
        self.log_segmented = ctk.CTkSegmentedButton(
            bar, values=["操作日志", "登录日志"], font=theme.FONT_BODY, height=32,
            selected_color=theme.SECONDARY, unselected_color=theme.SURFACE_MUTED,
            selected_hover_color=theme.hover(theme.SECONDARY),
            unselected_hover_color=theme.ROW_HOVER,
            text_color=theme.TEXT_PRIMARY, command=self._on_log_kind)
        self.log_segmented.set("操作日志" if is_op else "登录日志")
        self.log_segmented.pack(side="left", padx=theme.PAD_CARD, pady=12)

        field_label(bar, "关键字").pack(side="left", padx=(16, 6))
        self.log_keyword = entry(bar, "账号 / 对象 / 明细", width=200)
        self.log_keyword.pack(side="left")

        field_label(bar, "筛选").pack(side="left", padx=(16, 6))
        self.log_filter = _option_menu(bar, self._log_filter_values(), width=120)
        self.log_filter.pack(side="left")

        DynamicButton(bar, text="查询", style="primary", width=84,
                      command=self.load_logs).pack(side="left", padx=(14, 8))
        DynamicButton(bar, text="重置", style="ghost", width=76,
                      command=self.reset_log_filters).pack(side="left")

        self.log_total = ctk.CTkLabel(parent, text="", font=theme.FONT_SMALL,
                                      text_color=theme.TEXT_SECONDARY)
        self.log_total.pack(anchor="e", pady=(6, 0))
        self.log_table = DataTable(
            parent, self.OP_LOG_COLUMNS if is_op else self.LOGIN_LOG_COLUMNS,
            page_size=30)
        self.log_table.pack(fill="both", expand=True, pady=(4, 0))
        self.load_logs()

    def _log_filter_values(self):
        if self.log_kind == "op":
            return ["全部"] + system_service.op_log_modules()
        return ["全部", "成功", "失败"]

    def _on_log_kind(self, value):
        """切换日志类型：表格列不同，直接重建整个日志分区。"""
        self.log_kind = "op" if value == "操作日志" else "login"
        self._switch("日志查看")

    def reset_log_filters(self):
        self.log_keyword.delete(0, "end")
        self.log_filter.set("全部")
        self.load_logs()

    def load_logs(self):
        keyword = self.log_keyword.get().strip() or None
        selected = self.log_filter.get()
        choice = None if selected in ("", "全部") else selected
        if self.log_kind == "op":
            rows, total = system_service.list_op_logs(keyword=keyword, module=choice)
        else:
            rows, total = system_service.list_login_logs(keyword=keyword, result=choice)
        self.log_table.set_data(rows)
        self.log_total.configure(
            text=f"共 {total} 条，显示最近 {min(total, config.LOG_PAGE_SIZE)} 条")