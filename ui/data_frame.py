# -*- coding: utf-8 -*-
"""数据管理页：数据导出、数据导入、数据备份三个分区。

分区按其权限项动态渲染：personnel.export / personnel.import / backup.manage。
导出用固定模板（五类数据集）并支持任意时间段过滤；导入仅人员，按表头智能识别。
"""

import os
from tkinter import filedialog

import customtkinter as ctk

import config
from services import data_service, system_service
from ui import theme
from ui.widgets import (Card, DataTable, DynamicButton, confirm, entry,
                        filter_label, info, page_header, warn)

# 预览表格可用宽度（1366×768 小屏实测），列宽合计 + 每列左右间距不得超出
_PREVIEW_LIMIT = 940


def _option_menu(parent, values, width=140, command=None):
    accent = theme.active_accent()
    menu = ctk.CTkOptionMenu(
        parent, values=list(values), width=width, height=34, font=theme.FONT_BODY,
        fg_color=accent, button_color=theme.hover(accent),
        button_hover_color=theme.active(accent),
        dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY,
        command=command)
    menu.set(values[0])
    return menu


def _preview_columns(columns):
    """把数据集列裁成适配小屏的预览列：返回 (列定义, 展示数, 总数)。"""
    chosen, used = [], 0
    for label, key in columns:
        width = min(180, max(76, len(str(label)) * 15 + 18))
        if chosen and used + width + 2 > _PREVIEW_LIMIT:
            break
        chosen.append({"key": key, "title": str(label), "width": width})
        used += width + 2
    return chosen, len(chosen), len(columns)


class DataPage(ctk.CTkFrame):
    """数据导入 / 导出 / 备份的统一入口。"""

    TITLE = "数据管理"
    DESC = ("数据导入、数据导出（Excel / PDF）与数据备份：导出使用固定模板并可按任意"
            "时间段过滤；导入按表头智能识别需要的数据。")

    # (分区名, 所需权限, 构建方法名)
    TABS = (("数据导出", "personnel.export", "_build_export"),
            ("数据导入", "personnel.import", "_build_import"),
            ("数据备份", "backup.manage", "_build_backup"))

    BACKUP_COLUMNS = [
        {"key": "name", "title": "备份文件", "width": 260},
        {"key": "time", "title": "备份时间", "width": 180},
        {"key": "size_kb", "title": "大小(KB)", "width": 120, "anchor": "center"},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.options = data_service.dataset_options()
        self.name_to_key = {name: key for key, name, _label in self.options}
        self.preview_table = None
        self.preview_rows = []
        self._build()

    # ------------------------------------------------------------ 骨架
    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        self.available = [(name, method) for name, perm, method in self.TABS
                          if self.user.can(perm)]
        if not self.available:
            ctk.CTkLabel(self, text="当前账号没有数据管理权限", font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(pady=40)
            return

        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        bar.pack(fill="x", pady=(theme.GAP, 0))
        if len(self.available) > 1:
            self.tab_bar = ctk.CTkSegmentedButton(
                bar, values=[name for name, _m in self.available],
                font=theme.FONT_BODY, height=32, selected_color=theme.SECONDARY,
                unselected_color=theme.SURFACE_MUTED,
                selected_hover_color=theme.hover(theme.SECONDARY),
                unselected_hover_color=theme.ROW_HOVER,
                text_color=theme.TEXT_PRIMARY, command=self._switch)
            self.tab_bar.set(self.available[0][0])
            self.tab_bar.pack(side="left", padx=theme.PAD_CARD, pady=12)
        else:
            ctk.CTkLabel(bar, text=self.available[0][0], font=theme.FONT_SUBTITLE,
                         text_color=theme.TEXT_PRIMARY).pack(
                side="left", padx=theme.PAD_CARD, pady=12)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self._switch(self.available[0][0])

    def _switch(self, name):
        for child in self.body.winfo_children():
            child.destroy()
        self.preview_table = None
        method = dict(self.available).get(name)
        if method is None:
            return
        getattr(self, method)(self.body)

    # ============================================================ 数据导出
    def _build_export(self, parent):
        card = Card(parent, title="导出设置")
        card.pack(fill="x")

        names = [name for _key, name, _label in self.options]
        row = ctk.CTkFrame(card.body, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        filter_label(row, "数据集").pack(side="left")
        self.dataset_menu = _option_menu(row, names, width=170,
                                         command=self._on_dataset_change)
        self.dataset_menu.pack(side="left", padx=(6, 18))

        filter_label(row, "开始").pack(side="left")
        self.start_entry = entry(row, "YYYY-MM-DD", width=112)
        self.start_entry.pack(side="left", padx=(6, 18))
        filter_label(row, "结束").pack(side="left")
        self.end_entry = entry(row, "YYYY-MM-DD", width=112)
        self.end_entry.pack(side="left", padx=(6, 18))

        filter_label(row, "格式").pack(side="left")
        formats = ["Excel (.xlsx)"]
        if data_service.pdf_available():
            formats.append("PDF (.pdf)")
        self.fmt_menu = _option_menu(row, formats, width=118)
        self.fmt_menu.pack(side="left", padx=(6, 0))

        self.hint = ctk.CTkLabel(card.body, text="", font=theme.FONT_SMALL,
                                 text_color=theme.TEXT_SECONDARY, anchor="w",
                                 justify="left", wraplength=940)
        self.hint.pack(anchor="w", pady=(10, 0))

        acts = ctk.CTkFrame(card.body, fg_color="transparent")
        acts.pack(fill="x", pady=(10, 0))
        self.export_count = ctk.CTkLabel(acts, text="", font=theme.FONT_SMALL,
                                         text_color=theme.TEXT_SECONDARY)
        self.export_count.pack(side="left")
        DynamicButton(acts, text="重置", style="ghost", width=76,
                      command=self.reset_export).pack(side="right", padx=(8, 0))
        DynamicButton(acts, text="导出", style="primary", width=96,
                      command=self.do_export).pack(side="right", padx=(8, 0))
        DynamicButton(acts, text="刷新预览", style="secondary", width=100,
                      command=self.refresh_preview).pack(side="right")

        self.preview_holder = ctk.CTkFrame(parent, fg_color="transparent")
        self.preview_holder.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self._on_dataset_change(self.dataset_menu.get())

    def _current_key(self):
        return self.name_to_key.get(self.dataset_menu.get(), self.options[0][0])

    def _on_dataset_change(self, _name=None):
        key = self._current_key()
        item = next(i for i in data_service.DATASETS if i["key"] == key)
        columns, shown, total = _preview_columns(item["columns"])
        note = f"时间字段：{item['date_label']}（按该字段过滤时间段）"
        if shown < total:
            note += f"｜预览显示前 {shown} / {total} 列，导出文件包含全部列"
        self.hint.configure(text=note)

        if self.preview_table is not None:
            self.preview_table.destroy()
        self.preview_table = DataTable(self.preview_holder, columns,
                                       page_size=config.PAGE_SIZE)
        self.preview_table.pack(fill="both", expand=True)
        self.refresh_preview()

    def _read_range(self):
        return (self.start_entry.get().strip() or None,
                self.end_entry.get().strip() or None)

    def refresh_preview(self):
        try:
            result = data_service.collect(self._current_key(), *self._read_range())
        except ValueError as exc:
            warn(self, str(exc), "参数错误")
            return
        self.preview_rows = result["rows"]
        self.preview_table.set_data(self.preview_rows)
        label = data_service.range_label(*self._read_range())
        self.export_count.configure(
            text=f"{result['name']}：{len(self.preview_rows)} 条（{label}）")

    def do_export(self):
        fmt = "pdf" if self.fmt_menu.get().startswith("PDF") else "xlsx"
        try:
            path, count = data_service.export(self._current_key(), fmt,
                                              *self._read_range(),
                                              operator=self.user.username)
        except ValueError as exc:
            warn(self, str(exc), "参数错误")
            return
        except Exception as exc:                       # noqa: BLE001 文件写入异常需提示
            warn(self, f"导出失败：{exc}", "导出失败")
            return
        info(self, f"已导出 {count} 条记录：\n{path}", "导出完成")
        if confirm(self, "是否立即打开导出文件？", "导出完成"):
            self._open_path(path)

    def reset_export(self):
        self.start_entry.delete(0, "end")
        self.end_entry.delete(0, "end")
        self.dataset_menu.set(self.options[0][1])
        self._on_dataset_change()

    # ============================================================ 数据导入
    def _build_import(self, parent):
        card = Card(parent, title="人员批量导入")
        card.pack(fill="x")
        ctk.CTkLabel(
            card.body,
            text="选择人员类型后下载模板，按模板填写再导入。系统按表头自动识别需要的"
                 "数据：列顺序不同、多出无关列、常见表头别称（如「身份证号码」「手机号」）"
                 "均可识别；逐行校验，非法行不影响其它行导入并汇总错误报告。",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, anchor="w",
            justify="left", wraplength=940).pack(anchor="w")

        row = ctk.CTkFrame(card.body, fg_color="transparent")
        row.pack(fill="x", pady=(14, 0))
        filter_label(row, "人员类型").pack(side="left")
        self.type_menu = _option_menu(row, config.PERSON_TYPES, width=130)
        self.type_menu.pack(side="left", padx=(6, 12))
        DynamicButton(row, text="下载模板", style="secondary", width=104,
                      command=self.download_template).pack(side="left")
        DynamicButton(row, text="选择 Excel 并导入", style="primary", width=156,
                      command=self.do_import).pack(side="right")

    def download_template(self):
        try:
            path = data_service.template(self.type_menu.get())
        except Exception as exc:                       # noqa: BLE001 文件写入异常需提示
            warn(self, f"生成模板失败：{exc}", "生成失败")
            return
        info(self, f"已生成{self.type_menu.get()}导入模板：\n{path}", "模板已生成")

    def do_import(self):
        path = filedialog.askopenfilename(
            title="选择人员导入文件", filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            result = data_service.import_personnel(path, self.type_menu.get(),
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
        self.app.refresh_status()

    # ============================================================ 数据备份
    def _build_backup(self, parent):
        card = Card(parent, title="数据备份")
        card.pack(fill="x")
        ctk.CTkLabel(card.body,
                     text=f"每日首次启动自动备份到 backup/ 目录，保留最近 "
                          f"{config.BACKUP_KEEP} 份；恢复前会自动留存一份当前数据。",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
                     anchor="w", justify="left", wraplength=940).pack(anchor="w")
        bar = ctk.CTkFrame(card.body, fg_color="transparent")
        bar.pack(fill="x", pady=(12, 0))
        DynamicButton(bar, text="立即备份", style="primary", width=100,
                      command=self.create_backup).pack(side="left")
        DynamicButton(bar, text="刷新列表", style="ghost", width=100,
                      command=self.load_backups).pack(side="left", padx=(10, 0))
        DynamicButton(bar, text="恢复选中备份", style="danger", width=124,
                      command=self.restore_backup).pack(side="right")

        self.backup_table = DataTable(parent, self.BACKUP_COLUMNS, page_size=20,
                                      on_select=self._select_backup)
        self.backup_table.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self.backup_selected = None
        self.load_backups()

    def _select_backup(self, record):
        self.backup_selected = record

    def load_backups(self):
        self.backup_selected = None
        self.backup_table.set_data(system_service.list_backups())

    def create_backup(self):
        ok, message = system_service.create_backup(operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self.load_backups()

    def restore_backup(self):
        if not self.backup_selected:
            warn(self, "请先在列表中选择一个备份文件")
            return
        if not confirm(self, f"确定用 {self.backup_selected['name']} 覆盖当前数据库吗？\n"
                             "恢复前会自动备份当前数据，恢复后需重新查看各模块。",
                       "恢复确认"):
            return
        ok, message = system_service.restore_backup(self.backup_selected["name"],
                                                    operator=self.user.username)
        (info if ok else warn)(self, message)
        if ok:
            self.load_backups()
            self.app.refresh_status()

    # ------------------------------------------------------------ 工具
    @staticmethod
    def _open_path(path):
        try:
            os.startfile(path)                         # 仅 Windows 平台
        except OSError:
            pass