# -*- coding: utf-8 -*-
"""健康管理：健康档案页（一人一档 + 体检报告归档）与日常监测页（8 项两级预警）。

阈值评估全部由 health_service 完成，界面只负责录入与呈现；
趋势折线图使用 matplotlib 嵌入，未安装时降级为文字提示。
"""

import os
from tkinter import filedialog

import customtkinter as ctk

import config
from services import (equipment_service, excel_service, health_service,
                      medicine_service, personnel_service)
from ui import theme
from ui.widgets import (Card, DataTable, DynamicButton, confirm, entry,
                        field_label, filter_label, info, page_header, warn)

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


# ---------------------------------------------------------------- 表单小工具
def _textbox(parent, height=56, width=300):
    return ctk.CTkTextbox(parent, height=height, width=width, font=theme.FONT_BODY,
                          fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
                          border_width=1, wrap="word")


def _detail_row(parent, label, value, color=None):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=3)
    ctk.CTkLabel(row, text=label, width=84, anchor="nw", font=theme.FONT_SMALL,
                 text_color=theme.TEXT_SECONDARY).pack(side="left")
    ctk.CTkLabel(row, text=str(value if value not in (None, "") else "—"),
                 anchor="w", justify="left", wraplength=160, font=theme.FONT_SMALL,
                 text_color=color or theme.TEXT_PRIMARY).pack(side="left", fill="x",
                                                              expand=True)


def _open_path(path):
    try:
        os.startfile(path)                             # 仅 Windows 平台
    except OSError:
        pass


# 监测汇总表导出列（中文表头, 字段名）
MONITOR_EXPORT_COLUMNS = [
    ("工号", "emp_no"), ("姓名", "name"), ("所属单位", "unit"),
    ("人员类型", "person_type"), ("监测日期", "check_date"),
    ("收缩压", "systolic"), ("舒张压", "diastolic"), ("血糖", "blood_sugar"),
    ("体重", "weight_kg"), ("同型半胱氨酸", "homocysteine"),
    ("总胆固醇", "cholesterol"), ("LDL-C", "ldl_c"), ("HDL-C", "hdl_c"),
    ("预警级别", "abnormal_level"), ("异常项", "abnormal_items"),
    ("记录人", "recorder"), ("备注", "note"),
]


# ---------------------------------------------------------------- 健康档案页
class HealthProfilePage(ctk.CTkFrame):
    """一人一档：基础体征、体检信息、既往史、慢病标记与体检报告归档。"""

    TITLE = "健康档案"
    DESC = "一人一档：基础体征、体检信息、既往史与慢病标记；超过 6 个月未体检自动提示到期。"

    COLUMNS = [
        {"key": "emp_no", "title": "工号", "width": 76},
        {"key": "name", "title": "姓名", "width": 72},
        {"key": "gender", "title": "性别", "width": 40},
        {"key": "unit", "title": "所属单位", "width": 112},
        {"key": "blood_type", "title": "血型", "width": 40},
        {"key": "last_checkup_date", "title": "最近体检", "width": 92},
        {"key": "checkup_level", "title": "体检状态", "width": 66,
         "tag": True, "level_key": "checkup_level"},
        {"key": "chronic_text", "title": "慢病标记", "width": 127},
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
        self._build_filters()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(theme.GAP, 0))

        # 固定宽度的详情面板先以 side="right" 占位，否则会被 expand 的表格挤成 1px
        right = ctk.CTkFrame(body, fg_color=theme.SURFACE_CARD, width=282,
                             corner_radius=theme.RADIUS_CARD)
        right.pack(side="right", fill="both", padx=(theme.GAP, 0))
        right.pack_propagate(False)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        self.table = DataTable(left, self.COLUMNS, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)

        self._build_detail(right)

    def _build_filters(self):
        filters = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                               corner_radius=theme.RADIUS_CARD)
        filters.pack(fill="x", pady=(theme.GAP, 0))

        filter_label(filters, "关键字").pack(side="left", padx=(theme.PAD_CARD, 6), pady=12)
        self.keyword_entry = entry(filters, "工号 / 姓名", width=150)
        self.keyword_entry.pack(side="left")

        filter_label(filters, "所属单位").pack(side="left", padx=(16, 6))
        self.unit_combo = ctk.CTkComboBox(
            filters, values=["全部"] + personnel_service.distinct_units(), width=140,
            height=34, font=theme.FONT_BODY, fg_color=theme.SURFACE_FORM,
            border_color=theme.BORDER, button_color=theme.SECONDARY,
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.unit_combo.pack(side="left")
        self.unit_combo.set("全部")

        filter_label(filters, "人员类型").pack(side="left", padx=(16, 6))
        self.type_menu = ctk.CTkOptionMenu(
            filters, values=["全部"] + list(config.PERSON_TYPES), width=112, height=34,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.type_menu.pack(side="left")

        self.missing_only = ctk.CTkCheckBox(
            filters, text="仅未建档案", font=theme.FONT_BODY, width=110, height=26,
            checkbox_width=20, checkbox_height=20, text_color=theme.TEXT_PRIMARY,
            fg_color=theme.SECONDARY, hover_color=theme.hover(theme.SECONDARY))
        self.missing_only.pack(side="left", padx=(16, 0))

        DynamicButton(filters, text="查询", style="primary", width=84,
                      command=self.load_data).pack(side="left", padx=(14, 8))
        DynamicButton(filters, text="重置", style="ghost", width=76,
                      command=self.reset_filters).pack(side="left")

        if self.user.can("health.create"):
            DynamicButton(filters, text="批量导入报告", style="secondary", width=112,
                          command=self.import_reports).pack(side="right",
                                                            padx=(0, theme.PAD_CARD))

    def _build_detail(self, parent):
        ctk.CTkLabel(parent, text="档案详情", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w",
                                                         padx=theme.PAD_CARD,
                                                         pady=(12, 4))
        self.detail = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.detail.pack(fill="both", expand=True, padx=theme.PAD_CARD, pady=(0, 6))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", padx=theme.PAD_CARD, pady=(0, 12))
        self.edit_button = DynamicButton(actions, text="编辑档案", style="primary",
                                         width=112, command=self.edit_profile)
        self.report_button = DynamicButton(actions, text="上传报告", style="secondary",
                                           width=112, command=self.upload_report)
        self.open_button = DynamicButton(actions, text="打开报告", style="ghost",
                                         width=112, command=self.open_report)
        self.confirm_button = DynamicButton(actions, text="确认解析", style="success",
                                            width=112, command=self.confirm_parse)
        for index, button in enumerate((self.edit_button, self.report_button,
                                        self.open_button, self.confirm_button)):
            button.grid(row=index // 2, column=index % 2, padx=(0, 8), pady=4, sticky="w")

        can_write = self.user.can("health.create") or self.user.can("health.update")
        if not can_write:
            self.edit_button.set_enabled(False)
            self.report_button.set_enabled(False)
            self.confirm_button.set_enabled(False)
        self._render_detail(None)

    # ------------------------------------------------------------ 数据
    def reset_filters(self):
        self.keyword_entry.delete(0, "end")
        self.unit_combo.set("全部")
        self.type_menu.set("全部")
        self.missing_only.deselect()
        self.load_data()

    def load_data(self):
        unit = self.unit_combo.get()
        person_type = self.type_menu.get()
        self.rows = health_service.list_profiles(
            keyword=self.keyword_entry.get().strip() or None,
            unit=None if unit in ("", "全部") else unit,
            person_type=None if person_type == "全部" else person_type,
            only_onboard=True, only_missing=bool(self.missing_only.get()))
        self.table.set_data(self.rows)
        self.current = None
        self._render_detail(None)

    def _on_select(self, record):
        self.current = record
        self._render_detail(record)

    def _render_detail(self, record):
        for child in self.detail.winfo_children():
            child.destroy()
        self.open_button.set_enabled(False)
        self.confirm_button.set_enabled(False)

        if record is None:
            ctk.CTkLabel(self.detail, text="请选择左侧人员查看健康档案",
                         font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=16)
            return

        ctk.CTkLabel(self.detail, text=f"{record['name']}（{record['emp_no']}）",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 2))
        if not record["has_profile"]:
            ctk.CTkLabel(self.detail, text="尚未建立健康档案，请点击「编辑档案」录入。",
                         font=theme.FONT_SMALL, wraplength=260, justify="left",
                         text_color=theme.WARNING).pack(anchor="w", pady=(0, 6))

        _detail_row(self.detail, "所属单位", record.get("unit"))
        _detail_row(self.detail, "人员类型", record.get("person_type"))

        self._section("基础体征")
        _detail_row(self.detail, "身高 / 体重",
                    f"{record.get('height_cm') or '—'} cm / "
                    f"{record.get('weight_kg') or '—'} kg")
        _detail_row(self.detail, "BMI",
                    record.get("bmi"),
                    theme.severity_color(health_service.evaluate_indicators(
                        {"bmi": record.get("bmi")})[0]))
        blood = record.get("blood_type") or "—"
        rh = record.get("rh_type") or "—"
        _detail_row(self.detail, "血型", f"{blood} ｜ Rh {rh}")

        self._section("体检信息")
        _detail_row(self.detail, "最近体检", record.get("last_checkup_date"))
        _detail_row(self.detail, "体检机构", record.get("checkup_org"))
        _detail_row(self.detail, "体检状态", record.get("checkup_level"),
                    theme.severity_color(record.get("checkup_level")))
        _detail_row(self.detail, "解析状态", record.get("parse_status"))
        has_report = bool(record.get("checkup_report_path"))
        _detail_row(self.detail, "报告文件",
                    "已归档" if has_report else "未上传")
        self.open_button.set_enabled(has_report)
        self.confirm_button.set_enabled(record.get("parse_status") == "待核对")

        self._section("既往史")
        _detail_row(self.detail, "病史", record.get("medical_history"))
        _detail_row(self.detail, "手术史", record.get("surgery_history"))
        _detail_row(self.detail, "过敏史", record.get("allergy_history"))

        self._section("慢病标记")
        _detail_row(self.detail, "慢病", record.get("chronic_text"))
        if record.get("occupational_disease"):
            _detail_row(self.detail, "职业病", record.get("occupational_desc"))

    def _section(self, title):
        ctk.CTkFrame(self.detail, height=1, fg_color=theme.BORDER).pack(fill="x",
                                                                        pady=(10, 6))
        ctk.CTkLabel(self.detail, text=title, font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 2))

    # ------------------------------------------------------------ 动作
    def _require_selection(self):
        if self.current is None:
            warn(self, "请先在左侧选中一名人员", "提示")
            return None
        return self.current

    def edit_profile(self):
        record = self._require_selection()
        if record is None:
            return
        dialog = ProfileDialog(self, self.user, record)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.load_data()

    def upload_report(self):
        record = self._require_selection()
        if record is None:
            return
        path = filedialog.askopenfilename(
            title=f"选择 {record['name']} 的体检报告",
            filetypes=[("体检报告", "*.pdf *.jpg *.jpeg *.png"),
                       ("所有文件", "*.*")])
        if not path:
            return
        ok, message = health_service.attach_report(
            record["id"], path, record.get("last_checkup_date"),
            self.user.username)
        if not ok:
            warn(self, message, "归档失败")
            return
        info(self, message, "报告已归档")
        self.load_data()

    def open_report(self):
        record = self._require_selection()
        if record is None or not record.get("checkup_report_path"):
            return
        path = health_service.report_abs_path(record["checkup_report_path"])
        if not path.exists():
            warn(self, "报告文件已不存在，请重新上传", "打开失败")
            return
        _open_path(path)

    def confirm_parse(self):
        record = self._require_selection()
        if record is None:
            return
        if not confirm(self, f"确认 {record['name']} 的体检解析结果无误？\n"
                             "确认后该档案标记为「已确认」。", "解析确认"):
            return
        ok, message = health_service.confirm_parse(record["id"], self.user.username)
        if not ok:
            warn(self, message, "操作失败")
            return
        info(self, message, "确认完成")
        self.load_data()

    def import_reports(self):
        folder = filedialog.askdirectory(title="选择存放体检报告的文件夹")
        if not folder:
            return
        ok, message, results = health_service.import_report_folder(
            folder, self.user.username)
        if not ok:
            warn(self, message, "批量导入失败")
            return
        failures = [item for item in results if not item["ok"]]
        lines = [message]
        for item in failures[:5]:
            lines.append(f"· {item['file']}：{item['message']}")
        if len(failures) > 5:
            lines.append(f"· 其余 {len(failures) - 5} 份失败明细略")
        info(self, "\n".join(lines), "批量导入完成")
        self.load_data()


# ---------------------------------------------------------------- 档案编辑对话框
class ProfileDialog(ctk.CTkToplevel):
    """健康档案新增 / 编辑对话框。"""

    def __init__(self, master, user, record):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.record = record
        self.profile = health_service.get_profile(record["id"]) or {}
        self.success = False
        self.inputs = {}
        self.chronic = {}
        self.history = {}

        self.title("健康档案")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.geometry("760x660")
        self._build()
        self.after(120, self.focus_force)

    def _build(self):
        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=62)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text=f"健康档案 — {self.record['name']}"
                                f"（{self.record['emp_no']}）",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(16, 0))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=14)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")
        self._build_basic(top)
        self._build_checkup(top)

        self._build_history(body)
        self._build_chronic(body)

        self.hint = ctk.CTkLabel(body, text="身高体重用于自动计算 BMI；"
                                            "体检日期超过 6 个月将提示到期。",
                                 font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        self.hint.pack(anchor="w", pady=(10, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(12, 0))
        self.submit_button = DynamicButton(buttons, text="保存", style="primary",
                                           width=120, command=self._submit)
        self.submit_button.pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))

        self._fill()

    def _build_basic(self, parent):
        box = Card(parent, title="基础体征")
        box.pack(side="left", fill="both", expand=True)
        form = box.body

        field_label(form, "身高 (cm)").grid(row=0, column=0, sticky="w", pady=6)
        self.inputs["height_cm"] = entry(form, "如 175", width=130)
        self.inputs["height_cm"].grid(row=0, column=1, sticky="w")

        field_label(form, "体重 (kg)").grid(row=1, column=0, sticky="w", pady=6)
        self.inputs["weight_kg"] = entry(form, "如 70", width=130)
        self.inputs["weight_kg"].grid(row=1, column=1, sticky="w")

        field_label(form, "BMI（自动）").grid(row=2, column=0, sticky="w", pady=6)
        self.bmi_label = ctk.CTkLabel(form, text="—", font=theme.FONT_BODY,
                                      text_color=theme.SECONDARY)
        self.bmi_label.grid(row=2, column=1, sticky="w")

        field_label(form, "血型").grid(row=3, column=0, sticky="w", pady=6)
        self.inputs["blood_type"] = ctk.CTkOptionMenu(
            form, values=list(config.BLOOD_TYPES), width=130, height=32,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.inputs["blood_type"].grid(row=3, column=1, sticky="w")

        field_label(form, "Rh").grid(row=4, column=0, sticky="w", pady=6)
        self.inputs["rh_type"] = ctk.CTkOptionMenu(
            form, values=list(config.RH_TYPES), width=130, height=32,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.inputs["rh_type"].grid(row=4, column=1, sticky="w")

        for key in ("height_cm", "weight_kg"):
            self.inputs[key].bind("<KeyRelease>", lambda _e=None: self._refresh_bmi())

    def _build_checkup(self, parent):
        box = Card(parent, title="体检信息")
        box.pack(side="left", fill="both", expand=True, padx=(theme.GAP, 0))
        form = box.body

        field_label(form, "最近体检日期").grid(row=0, column=0, sticky="w", pady=6)
        self.inputs["last_checkup_date"] = entry(form, "2026-10-01", width=150)
        self.inputs["last_checkup_date"].grid(row=0, column=1, sticky="w")

        field_label(form, "体检机构").grid(row=1, column=0, sticky="w", pady=6)
        self.inputs["checkup_org"] = entry(form, "如 海洋钻井职工医院", width=150)
        self.inputs["checkup_org"].grid(row=1, column=1, sticky="w")

        self.report_label = ctk.CTkLabel(
            form, text="报告文件：—", font=theme.FONT_SMALL, wraplength=200,
            justify="left", text_color=theme.TEXT_SECONDARY)
        self.report_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_history(self, parent):
        box = Card(parent, title="既往史")
        box.pack(fill="x", pady=(theme.GAP, 0))
        form = box.body
        specs = [("medical_history", "过往病史"), ("surgery_history", "手术史"),
                 ("allergy_history", "过敏史")]
        for index, (key, label) in enumerate(specs):
            ctk.CTkLabel(form, text=label, font=theme.FONT_BODY, width=84, anchor="w",
                         text_color=theme.TEXT_PRIMARY).grid(row=index, column=0,
                                                             sticky="nw", pady=6)
            textbox = _textbox(form, height=52, width=560)
            textbox.grid(row=index, column=1, sticky="w", pady=6)
            self.history[key] = textbox

    def _build_chronic(self, parent):
        box = Card(parent, title="慢病标记")
        box.pack(fill="x", pady=(theme.GAP, 0))
        form = box.body

        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(anchor="w")
        for key, label in config.CHRONIC_KEYS:
            check = ctk.CTkCheckBox(
                row, text=label, font=theme.FONT_BODY, width=96, height=26,
                checkbox_width=20, checkbox_height=20, text_color=theme.TEXT_PRIMARY,
                fg_color=theme.SECONDARY, hover_color=theme.hover(theme.SECONDARY))
            check.pack(side="left", padx=(0, 10))
            self.chronic[key] = check

        sub = ctk.CTkFrame(form, fg_color="transparent")
        sub.pack(fill="x", pady=(8, 0))
        field_label(sub, "职业病描述").pack(side="left")
        self.inputs["occupational_desc"] = entry(sub, "勾选职业病时填写病种", width=420)
        self.inputs["occupational_desc"].pack(side="left")

    # ------------------------------------------------------------ 取值 / 回填
    def _refresh_bmi(self):
        bmi = health_service.calc_bmi(self.inputs["height_cm"].get(),
                                      self.inputs["weight_kg"].get())
        self.bmi_label.configure(text=f"{bmi}" if bmi else "—")

    def _fill(self):
        profile = self.profile
        for key in ("height_cm", "weight_kg", "last_checkup_date", "checkup_org",
                    "occupational_desc"):
            value = profile.get(key)
            if value not in (None, ""):
                self.inputs[key].insert(0, str(value))
        self.inputs["blood_type"].set(profile.get("blood_type") or config.BLOOD_TYPES[0])
        self.inputs["rh_type"].set(profile.get("rh_type") or config.RH_TYPES[0])
        for key, _label in config.CHRONIC_KEYS:
            if profile.get(key):
                self.chronic[key].select()
        for key, textbox in self.history.items():
            value = profile.get(key)
            if value:
                textbox.insert("1.0", str(value))
        report = profile.get("checkup_report_path")
        self.report_label.configure(
            text=f"报告文件：{report.split('/')[-1] if report else '未上传'}")
        self._refresh_bmi()

    def _form_data(self):
        data = {key: widget.get() for key, widget in self.inputs.items()}
        for key, check in self.chronic.items():
            data[key] = 1 if check.get() else 0
        for key, textbox in self.history.items():
            data[key] = textbox.get("1.0", "end").strip()
        return data

    def _submit(self):
        self.submit_button.set_loading(True)
        ok, message = health_service.save_profile(
            self.record["id"], self._form_data(), self.user.username)
        self.submit_button.set_loading(False)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "保存成功")
        self.destroy()


# ---------------------------------------------------------------- 趋势图
class _TrendChart(ctk.CTkFrame):
    """个人指标趋势折线图，异常点按级别标色。"""

    def __init__(self, master):
        super().__init__(master, fg_color=theme.SURFACE_CARD,
                         corner_radius=theme.RADIUS_CARD)
        if HAS_MPL:
            self.figure = Figure(figsize=(4.6, 2.8), dpi=100)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self)
            self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)
            self.draw("趋势", [], None)
        else:
            ctk.CTkLabel(self, text="未安装 matplotlib，趋势图不可用",
                         font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY).pack(expand=True)

    def draw(self, title, points, level_of):
        if not HAS_MPL:
            return
        self.figure.clear()
        axes = self.figure.add_subplot(111)
        if not points:
            axes.text(0.5, 0.5, "暂无监测数据", ha="center", va="center",
                      fontsize=10, color=theme.TEXT_SECONDARY)
            axes.set_axis_off()
        else:
            dates = [point[0] for point in points]
            values = [point[1] for point in points]
            axes.plot(range(len(values)), values, color=theme.SECONDARY,
                      linewidth=1.6, marker="o", markersize=5)
            if level_of:
                for index, value in enumerate(values):
                    level = level_of(value)
                    if level != "正常":
                        axes.plot([index], [value], marker="o", linewidth=0,
                                  color=theme.severity_color(level), markersize=8)
            step = max(len(dates) // 6, 1)
            ticks = list(range(0, len(dates), step))
            axes.set_xticks(ticks)
            axes.set_xticklabels([dates[i][5:] for i in ticks], fontsize=8)
            axes.tick_params(labelsize=8)
            axes.grid(True, color=theme.BORDER_LIGHT, linewidth=0.8)
            axes.set_title(title, fontsize=10, color=theme.TEXT_PRIMARY)
        self.figure.tight_layout()
        self.canvas.draw_idle()


# ---------------------------------------------------------------- 日常监测页
class MonitorPage(ctk.CTkFrame):
    """日常监测：8 项指标录入，越限自动两级预警，附历史记录与趋势图。"""

    TITLE = "日常监测"
    DESC = "录入 8 项监测指标，任一越限即自动标注黄色 / 红色预警，并可查看个人历史趋势。"

    COLUMNS = [
        {"key": "check_date", "title": "监测日期", "width": 92},
        {"key": "systolic", "title": "收缩压", "width": 66, "anchor": "center"},
        {"key": "diastolic", "title": "舒张压", "width": 66, "anchor": "center"},
        {"key": "blood_sugar", "title": "血糖", "width": 60, "anchor": "center"},
        {"key": "weight_kg", "title": "体重", "width": 60, "anchor": "center"},
        {"key": "homocysteine", "title": "同型半胱氨酸", "width": 96, "anchor": "center"},
        {"key": "cholesterol", "title": "总胆固醇", "width": 78, "anchor": "center"},
        {"key": "ldl_c", "title": "LDL-C", "width": 66, "anchor": "center"},
        {"key": "hdl_c", "title": "HDL-C", "width": 66, "anchor": "center"},
        {"key": "abnormal_level", "title": "预警级别", "width": 92,
         "tag": True, "level_key": "abnormal_level"},
        {"key": "abnormal_items", "title": "异常项", "width": 250},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.person_map = {}
        self.current_id = None
        self._build()
        self._load_persons()
        # 初始渲染空状态，避免表格数据区留白（未选人员时显示「暂无数据」）
        self.refresh_history()

    # ------------------------------------------------------------ 界面
    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        top = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        top.pack(fill="x", pady=(theme.GAP, 0))

        pick = ctk.CTkFrame(top, fg_color="transparent")
        pick.pack(fill="x", padx=theme.PAD_CARD, pady=(12, 0))
        field_label(pick, "选择人员").pack(side="left", padx=(0, 6))
        self.person_combo = ctk.CTkComboBox(
            pick, values=[""], width=280, height=34, font=theme.FONT_BODY,
            fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
            button_color=theme.SECONDARY, dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.person_combo.pack(side="left")
        DynamicButton(pick, text="载入", style="primary", width=84,
                      command=self.load_person).pack(side="left", padx=(10, 0))
        self.keyword_entry = entry(pick, "工号 / 姓名筛选", width=160)
        self.keyword_entry.pack(side="left", padx=(16, 6))
        DynamicButton(pick, text="筛选", style="ghost", width=76,
                      command=self._load_persons).pack(side="left")
        self.person_hint = ctk.CTkLabel(pick, text="", font=theme.FONT_SMALL,
                                        text_color=theme.TEXT_SECONDARY)
        self.person_hint.pack(side="left", padx=(14, 0))

        form = ctk.CTkFrame(top, fg_color="transparent")
        form.pack(fill="x", padx=theme.PAD_CARD, pady=(6, 0))
        self.inputs = {}
        for index, (key, label, unit) in enumerate(config.MONITOR_FIELDS):
            row, col = divmod(index, 4)
            cell = ctk.CTkFrame(form, fg_color="transparent")
            cell.grid(row=row, column=col, sticky="w", padx=(0, 18), pady=2)
            ctk.CTkLabel(cell, text=f"{label}（{unit}）", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_PRIMARY).pack(anchor="w")
            widget = entry(cell, "—", width=150)
            widget.pack(anchor="w", pady=(2, 0))
            self.inputs[key] = widget

        meta = ctk.CTkFrame(top, fg_color="transparent")
        meta.pack(fill="x", padx=theme.PAD_CARD, pady=(6, 0))
        field_label(meta, "监测日期").pack(side="left", padx=(0, 6))
        self.date_entry = entry(meta, "", width=140)
        self.date_entry.pack(side="left")
        field_label(meta, "备注").pack(side="left", padx=(16, 6))
        self.note_entry = entry(meta, "可选", width=300)
        self.note_entry.pack(side="left")
        self.save_button = DynamicButton(meta, text="保存监测", style="primary",
                                         width=112, command=self.save)
        self.save_button.pack(side="left", padx=(16, 0))
        self.batch_button = DynamicButton(meta, text="批量录入", style="secondary",
                                          width=112, command=self.batch_entry)
        self.batch_button.pack(side="left", padx=(8, 0))
        if not self.user.can("check.create"):
            self.save_button.set_enabled(False)
            self.batch_button.set_enabled(False)

        self.form_hint = ctk.CTkLabel(top, text="", font=theme.FONT_SMALL,
                                      wraplength=1100, justify="left",
                                      text_color=theme.TEXT_SECONDARY)
        self.form_hint.pack(anchor="w", padx=theme.PAD_CARD, pady=(6, 8))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="both", expand=True, pady=(theme.GAP, 0))

        # 固定宽度的趋势面板先以 side="right" 占位，避免被 expand 的表格挤成 1px
        right = ctk.CTkFrame(bottom, fg_color="transparent", width=430)
        right.pack(side="right", fill="both", padx=(theme.GAP, 0))
        right.pack_propagate(False)
        selector = ctk.CTkFrame(right, fg_color="transparent")
        selector.pack(fill="x")
        ctk.CTkLabel(selector, text="趋势指标", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY).pack(side="left")
        self.indicator_menu = ctk.CTkOptionMenu(
            selector, values=[label for _k, label, _u in config.MONITOR_FIELDS],
            width=170, height=32, font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY, command=lambda _v: self._draw_trend())
        self.indicator_menu.pack(side="right")
        self.chart = _TrendChart(right)
        self.chart.pack(fill="both", expand=True, pady=(8, 0))

        left = ctk.CTkFrame(bottom, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        # 操作行先以 side="bottom" 占位，表格再填充剩余高度（否则表格体被压成 1px）
        actions = ctk.CTkFrame(left, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(theme.GAP, 0))
        ctk.CTkLabel(actions, text="选中一条记录可删除",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        if self.user.can("check.delete"):
            DynamicButton(actions, text="删除记录", style="danger", width=112,
                          command=self.delete_selected).pack(side="right")
        if self.user.can("check.view"):
            DynamicButton(actions, text="导出汇总表", style="info", width=112,
                          command=self.export_summary).pack(side="right",
                                                            padx=(0, 8))
        self.table = DataTable(left, self.COLUMNS, page_size=20)
        self.table.pack(fill="both", expand=True)

        self.date_entry.insert(0, personnel_service.now_text()[:10])

    # ------------------------------------------------------------ 人员选择
    def _load_persons(self):
        rows, _total = personnel_service.list_personnel(
            page=1, page_size=2000, only_onboard=True,
            keyword=self.keyword_entry.get().strip() or None)
        self.person_map = {}
        for row in rows:
            display = f"{row['emp_no']} {row['name']}（{row['unit'] or '—'}）"
            self.person_map[display] = row["id"]
        values = list(self.person_map.keys()) or ["（无在平台人员）"]
        self.person_combo.configure(values=values)
        self.person_combo.set(values[0])

    def load_person(self):
        display = self.person_combo.get()
        person_id = self.person_map.get(display)
        if person_id is None:
            warn(self, "请先选择一名在平台人员", "提示")
            return
        self.current_id = person_id
        self.person_hint.configure(text=f"当前人员：{display}")
        self.refresh_history()

    def refresh_history(self):
        if self.current_id is None:
            self.table.set_data([])
            self.chart.draw("趋势", [], None)
            return
        rows = health_service.list_checks(person_id=self.current_id, limit=200)
        self.table.set_data(rows)
        self._draw_trend()

    def _draw_trend(self):
        if self.current_id is None:
            return
        label = self.indicator_menu.get()
        key = next((k for k, text, _u in config.MONITOR_FIELDS if text == label),
                   config.MONITOR_FIELDS[0][0])
        points = health_service.check_trend(self.current_id, key)
        indicator = config.HEALTH_INDICATOR_MAP.get(key)
        level_of = None
        if indicator:
            level_of = lambda value: health_service._level_of(indicator, value)  # noqa: SLF001
        unit = next((u for k, _t, u in config.MONITOR_FIELDS if k == key), "")
        self.chart.draw(f"{label}（{unit}）", points, level_of)

    # ------------------------------------------------------------ 录入
    def save(self):
        if self.current_id is None:
            warn(self, "请先选择一名人员", "提示")
            return
        values = {key: widget.get() for key, widget in self.inputs.items()}
        self.save_button.set_loading(True)
        ok, message, _level = health_service.save_check(
            self.current_id, values, self.user.username,
            note=self.note_entry.get().strip(),
            check_date=self.date_entry.get())
        self.save_button.set_loading(False)

        if not ok:
            self.form_hint.configure(text=message, text_color=theme.DANGER)
            return
        is_warning = "正常" not in message
        self.form_hint.configure(text=message,
                                 text_color=theme.WARNING if is_warning
                                 else theme.SUCCESS)
        for widget in self.inputs.values():
            widget.delete(0, "end")
        self.note_entry.delete(0, "end")
        self.refresh_history()

    def delete_selected(self):
        record = self.table.get_selected()
        if record is None:
            warn(self, "请先选中要删除的监测记录", "提示")
            return
        if not confirm(self, f"确认删除 {record['name']} {record['check_date']} "
                             f"的监测记录？", "删除确认"):
            return
        ok, message = health_service.delete_check(record["id"], self.user.username)
        if not ok:
            warn(self, message, "删除失败")
            return
        info(self, message, "删除完成")
        self.refresh_history()

    # ------------------------------------------------------------ 批量录入 / 导出
    def batch_entry(self):
        dialog = BatchMonitorDialog(self, self.user)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.saved:
            today = dialog.check_date or personnel_service.now_text()[:10]
            self.date_entry.delete(0, "end")
            self.date_entry.insert(0, today)
            self.refresh_history()

    def export_summary(self):
        dialog = MonitorExportDialog(self)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.exported:
            self.form_hint.configure(
                text=f"监测汇总表已导出（{dialog.exported} 条）：{dialog.path}",
                text_color=theme.SUCCESS)


# ---------------------------------------------------------------- 批量录入对话框
class BatchMonitorDialog(ctk.CTkToplevel):
    """批量录入：勾选在平台人员后，一次性录入多人当日 8 项监测数据。

    逐行提交，单行校验失败不影响其他行；未填写任何指标的检测行自动跳过。
    """

    MAX_PERSONS = 200

    def __init__(self, master, user):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.saved = 0
        self.check_date = personnel_service.now_text()[:10]
        self._persons = []
        self._checks = {}
        self._entries = {}
        self._build()

    def _build(self):
        self.title("日常监测 · 批量录入")
        self.transient(self.master.winfo_toplevel())
        self.geometry("1180x720")
        self.minsize(980, 600)

        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=58)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="日常监测 · 批量录入（一次录入多人当日数据）",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(16, 0))

        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        bar.pack(fill="x", padx=16, pady=(12, 0))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=theme.PAD_CARD, pady=10)

        field_label(inner, "监测日期").pack(side="left", padx=(0, 6))
        self.date_entry = entry(inner, "", width=130)
        self.date_entry.pack(side="left")
        self.date_entry.insert(0, self.check_date)

        field_label(inner, "所属单位").pack(side="left", padx=(16, 6))
        self.unit_combo = ctk.CTkComboBox(
            inner, values=["全部"] + personnel_service.distinct_units(), width=140,
            height=34, font=theme.FONT_BODY, fg_color=theme.SURFACE_FORM,
            border_color=theme.BORDER, button_color=theme.SECONDARY,
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.unit_combo.pack(side="left")
        self.unit_combo.set("全部")

        field_label(inner, "关键字").pack(side="left", padx=(16, 6))
        self.keyword_entry = entry(inner, "工号 / 姓名", width=140)
        self.keyword_entry.pack(side="left")

        DynamicButton(inner, text="加载人员", style="primary", width=96,
                      command=self._load_persons).pack(side="left", padx=(12, 0))
        DynamicButton(inner, text="全选", style="ghost", width=68,
                      command=lambda: self._toggle_all(True)).pack(side="left",
                                                                   padx=(8, 0))
        DynamicButton(inner, text="清空", style="ghost", width=68,
                      command=lambda: self._toggle_all(False)).pack(side="left",
                                                                    padx=(8, 0))
        DynamicButton(inner, text="生成录入表", style="secondary", width=112,
                      command=self._build_grid).pack(side="left", padx=(8, 0))

        self.pick_card = Card(self, title="① 勾选需要录入的人员")
        self.pick_card.pack(fill="x", padx=16, pady=(12, 0))
        self.pick_list = ctk.CTkScrollableFrame(self.pick_card.body, height=140,
                                                fg_color="transparent")
        self.pick_list.pack(fill="x")

        self.grid_card = Card(self, title="② 填写监测数据（整行留空表示不录入该人员）")
        self.grid_card.pack(fill="both", expand=True, padx=16, pady=(12, 0))
        self.grid_body = ctk.CTkScrollableFrame(self.grid_card.body,
                                                fg_color="transparent")
        self.grid_body.pack(fill="both", expand=True)
        self.grid_hint = ctk.CTkLabel(self.grid_card.body, text="",
                                      font=theme.FONT_SMALL,
                                      text_color=theme.TEXT_SECONDARY)
        self.grid_hint.pack(anchor="w", pady=(6, 0))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=12)
        self.save_button = DynamicButton(bottom, text="保存全部", style="primary",
                                         width=120, command=self._submit)
        self.save_button.pack(side="right")
        DynamicButton(bottom, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))
        self.status = ctk.CTkLabel(bottom, text="", font=theme.FONT_SMALL,
                                   text_color=theme.TEXT_SECONDARY)
        self.status.pack(side="left")

        self._load_persons()
        self.after(120, self.focus_force)

    # ------------------------------------------------------------ 人员勾选
    def _load_persons(self):
        unit = self.unit_combo.get()
        rows, _total = personnel_service.list_personnel(
            page=1, page_size=2000, only_onboard=True,
            keyword=self.keyword_entry.get().strip() or None,
            unit=None if unit in ("", "全部") else unit)
        self._persons = rows
        for widget in self.pick_list.winfo_children():
            widget.destroy()
        self._checks = {}
        self._entries = {}
        for widget in self.grid_body.winfo_children():
            widget.destroy()
        self.grid_hint.configure(text="", text_color=theme.TEXT_SECONDARY)

        if not rows:
            ctk.CTkLabel(self.pick_list, text="当前没有符合条件的在平台人员",
                         font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=8)
            return
        for row in rows:
            text = f"{row['emp_no']} {row['name']}（{row['unit'] or '—'}｜{row['person_type']}）"
            check = ctk.CTkCheckBox(
                self.pick_list, text=text, font=theme.FONT_BODY, height=26,
                checkbox_width=20, checkbox_height=20, text_color=theme.TEXT_PRIMARY,
                fg_color=theme.SECONDARY, hover_color=theme.hover(theme.SECONDARY))
            check.pack(anchor="w", pady=2)
            self._checks[row["id"]] = check

    def _toggle_all(self, value):
        for check in self._checks.values():
            check.select() if value else check.deselect()

    # ------------------------------------------------------------ 生成录入表
    def _build_grid(self):
        selected = [row for row in self._persons if self._checks[row["id"]].get()]
        for widget in self.grid_body.winfo_children():
            widget.destroy()
        self._entries = {}
        if not selected:
            self.grid_hint.configure(text="请先在上方勾选需要录入的人员。",
                                     text_color=theme.DANGER)
            return
        if len(selected) > self.MAX_PERSONS:
            warn(self, f"一次最多录入 {self.MAX_PERSONS} 人，请用单位 / 关键字缩小范围。",
                 "提示")
            return

        header = ctk.CTkFrame(self.grid_body, fg_color=theme.SURFACE_SUNKEN,
                              corner_radius=theme.RADIUS_TAG)
        header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(header, text="人员", width=170, anchor="w", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_PRIMARY).grid(row=0, column=0, padx=6, pady=4)
        for index, (_key, label, _unit) in enumerate(config.MONITOR_FIELDS, start=1):
            ctk.CTkLabel(header, text=label, width=88, anchor="center",
                         font=theme.FONT_SMALL,
                         text_color=theme.TEXT_PRIMARY).grid(row=0, column=index, padx=2)
        ctk.CTkLabel(header, text="备注", width=150, anchor="w", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_PRIMARY).grid(row=0, column=9, padx=6)

        for person in selected:
            row = ctk.CTkFrame(self.grid_body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"{person['emp_no']} {person['name']}",
                         width=170, anchor="w", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_PRIMARY).grid(row=0, column=0, padx=6)
            cells = {}
            for index, (key, _label, _unit) in enumerate(config.MONITOR_FIELDS, start=1):
                widget = entry(row, "", width=88)
                widget.grid(row=0, column=index, padx=2)
                cells[key] = widget
            note = entry(row, "", width=150)
            note.grid(row=0, column=9, padx=6)
            cells["__note__"] = note
            self._entries[person["id"]] = cells

        self.grid_hint.configure(
            text=f"已生成 {len(selected)} 人的录入表；配置了阈值的指标越限将自动标注预警。",
            text_color=theme.TEXT_SECONDARY)

    # ------------------------------------------------------------ 提交
    def _submit(self):
        if not self._entries:
            warn(self, "请先勾选人员并点击「生成录入表」", "提示")
            return
        entries = []
        for person in self._persons:
            cells = self._entries.get(person["id"])
            if not cells:
                continue
            values = {key: cells[key].get().strip()
                      for key, _label, _unit in config.MONITOR_FIELDS}
            entries.append({"person_id": person["id"], "values": values,
                            "note": cells["__note__"].get().strip()})

        self.save_button.set_loading(True)
        total, ok_count, fail_count, results = health_service.save_checks_batch(
            entries, self.user.username, check_date=self.date_entry.get())
        self.save_button.set_loading(False)

        if total == 0:
            self.status.configure(text="尚未填写任何人员的监测数据。",
                                  text_color=theme.DANGER)
            return
        self.saved = ok_count
        self.check_date = (self.date_entry.get().strip() or self.check_date)[:10]
        if fail_count:
            detail = "；".join(f"{r['name']}：{r['message']}"
                              for r in results if not r["ok"])
            self.status.configure(
                text=f"共 {total} 条，成功 {ok_count}，失败 {fail_count}",
                text_color=theme.WARNING)
            warn(self, f"成功 {ok_count} 条，失败 {fail_count} 条：\n{detail[:300]}",
                 "批量录入结果")
        else:
            self.status.configure(text=f"共 {total} 条，成功 {ok_count}，失败 0",
                                  text_color=theme.SUCCESS)
            info(self, f"已成功录入 {ok_count} 条监测记录", "保存完成")
            self.destroy()


# ---------------------------------------------------------------- 汇总导出对话框
class MonitorExportDialog(ctk.CTkToplevel):
    """按单位 / 人员类型（可选日期范围）导出日常监测汇总表。"""

    def __init__(self, master):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.exported = 0
        self.path = None
        self._build()

    def _build(self):
        self.title("导出监测汇总表")
        self.resizable(False, False)
        self.transient(self.master.winfo_toplevel())
        self.geometry("540x400")
        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=58)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="导出日常监测汇总表", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(16, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        unit_row = ctk.CTkFrame(body, fg_color="transparent")
        unit_row.pack(fill="x", pady=6)
        field_label(unit_row, "所属单位").pack(side="left", padx=(0, 6))
        self.unit_combo = ctk.CTkComboBox(
            unit_row, values=["全部"] + personnel_service.distinct_units(), width=200,
            height=34, font=theme.FONT_BODY, fg_color=theme.SURFACE_FORM,
            border_color=theme.BORDER, button_color=theme.SECONDARY,
            dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.unit_combo.pack(side="left")
        self.unit_combo.set("全部")

        type_row = ctk.CTkFrame(body, fg_color="transparent")
        type_row.pack(fill="x", pady=6)
        field_label(type_row, "人员类型").pack(side="left", padx=(0, 6))
        self.type_menu = ctk.CTkOptionMenu(
            type_row, values=["全部"] + list(config.PERSON_TYPES), width=200, height=34,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.type_menu.pack(side="left")

        date_row = ctk.CTkFrame(body, fg_color="transparent")
        date_row.pack(fill="x", pady=6)
        field_label(date_row, "起始日期").pack(side="left", padx=(0, 6))
        self.start_entry = entry(date_row, "可留空", width=130)
        self.start_entry.pack(side="left")
        field_label(date_row, "结束日期").pack(side="left", padx=(12, 6))
        self.end_entry = entry(date_row, "可留空", width=130)
        self.end_entry.pack(side="left")

        self.hint = ctk.CTkLabel(body, text="留空表示不限；导出字段含人员信息、8 项指标、"
                                            "预警级别与异常项。",
                                 font=theme.FONT_SMALL, wraplength=480, justify="left",
                                 text_color=theme.TEXT_SECONDARY)
        self.hint.pack(anchor="w", pady=(10, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(14, 0))
        DynamicButton(buttons, text="导出", style="primary", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))
        self.after(120, self.focus_force)

    def _submit(self):
        unit = self.unit_combo.get()
        person_type = self.type_menu.get()
        start = self.start_entry.get().strip()
        end = self.end_entry.get().strip()
        for label, value in (("起始日期", start), ("结束日期", end)):
            if value and personnel_service.parse_datetime(value, with_time=False) is None:
                self.hint.configure(text=f"{label}格式应为 2026-10-01",
                                    text_color=theme.DANGER)
                return
        rows = health_service.monitor_summary(
            unit=None if unit in ("", "全部") else unit,
            person_type=None if person_type == "全部" else person_type,
            start=start[:10] or None, end=end[:10] or None)
        if not rows:
            self.hint.configure(text="所选条件下没有监测记录可导出。",
                                text_color=theme.DANGER)
            return
        path = excel_service.export_table("监测汇总表", "监测汇总",
                                          MONITOR_EXPORT_COLUMNS, rows)
        self.exported = len(rows)
        self.path = str(path)
        info(self, f"已导出 {len(rows)} 条监测记录：\n{path}", "导出完成")
        self.destroy()


# ---------------------------------------------------------------- 长期用药随访页
class MedicationPage(ctk.CTkFrame):
    """健康视角的药品管理：人员长期用药登记与随访，领用时联动扣减库存。"""

    TITLE = "药品管理"
    DESC = "人员长期用药登记与随访；与医疗物资的药品库存联动，领用时自动扣减。"

    COLUMNS = [
        {"key": "medicine_name", "title": "药品名称", "width": 150},
        {"key": "dosage", "title": "剂量", "width": 96},
        {"key": "frequency", "title": "频次", "width": 96},
        {"key": "start_date", "title": "开始日期", "width": 100},
        {"key": "follow_up", "title": "随访记录", "width": 230},
        {"key": "stock_text", "title": "库存联动", "width": 100, "tag": True,
         "level_key": "stock_level"},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.person_map = {}
        self.current_id = None
        self._build()
        self._load_persons()
        # 初始渲染空状态，避免表格数据区留白（未选人员时显示「暂无数据」）
        self.refresh()

    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        top = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        top.pack(fill="x", pady=(theme.GAP, 0))
        pick = ctk.CTkFrame(top, fg_color="transparent")
        pick.pack(fill="x", padx=theme.PAD_CARD, pady=12)
        field_label(pick, "选择人员").pack(side="left", padx=(0, 6))
        self.person_combo = ctk.CTkComboBox(
            pick, values=[""], width=280, height=34, font=theme.FONT_BODY,
            fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
            button_color=theme.SECONDARY, dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY)
        self.person_combo.pack(side="left")
        DynamicButton(pick, text="载入", style="primary", width=84,
                      command=self.load_person).pack(side="left", padx=(10, 0))
        self.keyword_entry = entry(pick, "工号 / 姓名筛选", width=160)
        self.keyword_entry.pack(side="left", padx=(16, 6))
        DynamicButton(pick, text="筛选", style="ghost", width=76,
                      command=self._load_persons).pack(side="left")
        self.person_hint = ctk.CTkLabel(pick, text="", font=theme.FONT_SMALL,
                                        text_color=theme.TEXT_SECONDARY)
        self.person_hint.pack(side="left", padx=(14, 0))

        # 操作行先以 side="bottom" 占位，表格再填充剩余高度（否则表格体被压成 1px）
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(theme.GAP, 0))
        self.hint = ctk.CTkLabel(actions, text="选中一条用药记录后可编辑或删除。",
                                 font=theme.FONT_SMALL,
                                 text_color=theme.TEXT_SECONDARY)
        self.hint.pack(side="left")
        self.dispense_button = DynamicButton(actions, text="领药扣减", style="warning",
                                             width=112, command=self.dispense)
        self.edit_button = DynamicButton(actions, text="编辑用药", style="secondary",
                                         width=112, command=self.edit_plan)
        self.delete_button = DynamicButton(actions, text="删除", style="danger",
                                           width=96, command=self.delete_plan)
        self.add_button = DynamicButton(actions, text="新增用药", style="primary",
                                        width=112, command=self.add_plan)
        for button in (self.dispense_button, self.edit_button, self.delete_button,
                       self.add_button):
            button.pack(side="right", padx=(8, 0))
        can_write = self.user.can("health.update")
        for button in (self.add_button, self.edit_button, self.delete_button):
            button.set_enabled(can_write)
        self.dispense_button.set_enabled(self.user.can("supply.manage"))
        self.current = None
        self.selected_plan = None

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        self.table = DataTable(body, self.COLUMNS, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 人员与数据
    def _load_persons(self):
        rows, _total = personnel_service.list_personnel(
            page=1, page_size=2000, only_onboard=True,
            keyword=self.keyword_entry.get().strip() or None)
        self.person_map = {}
        for row in rows:
            display = f"{row['emp_no']} {row['name']}（{row['unit'] or '—'}）"
            self.person_map[display] = row["id"]
        values = list(self.person_map.keys()) or ["（无在平台人员）"]
        self.person_combo.configure(values=values)
        self.person_combo.set(values[0])

    def load_person(self):
        display = self.person_combo.get()
        person_id = self.person_map.get(display)
        if person_id is None:
            warn(self, "请先选择一名在平台人员", "提示")
            return
        self.current_id = person_id
        self.person_hint.configure(text=f"当前人员：{display}")
        self.refresh()

    def refresh(self):
        if self.current_id is None:
            self.table.set_data([])
            return
        records = medicine_service.list_plans(person_id=self.current_id)
        for record in records:
            record["stock_text"] = "库存可领" if record["has_stock"] else "未建药品档案"
            record["stock_level"] = "正常" if record["has_stock"] else "提示"
        self.table.set_data(records)
        self.selected_plan = None

    def _on_select(self, record):
        self.selected_plan = record

    # ------------------------------------------------------------ 动作
    def add_plan(self):
        if self.current_id is None:
            warn(self, "请先选择一名人员", "提示")
            return
        dialog = PlanDialog(self, self.user, self.current_id, None)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.refresh()

    def edit_plan(self):
        if self.selected_plan is None:
            warn(self, "请先选中一条用药记录", "提示")
            return
        dialog = PlanDialog(self, self.user, self.current_id, self.selected_plan)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.refresh()

    def delete_plan(self):
        if self.selected_plan is None:
            warn(self, "请先选中一条用药记录", "提示")
            return
        if not confirm(self, f"确认删除 {self.selected_plan['medicine_name']} "
                             f"的用药登记？", "删除确认"):
            return
        ok, message = medicine_service.delete_plan(self.selected_plan["id"],
                                                   self.user.username)
        if not ok:
            warn(self, message, "删除失败")
            return
        info(self, message, "删除完成")
        self.refresh()

    def dispense(self):
        """领药扣减：按用药名称匹配药品档案，联动出库。"""
        if self.selected_plan is None:
            warn(self, "请先选中一条用药记录", "提示")
            return
        medicine = medicine_service.find_medicine_by_name(
            self.selected_plan["medicine_name"])
        if medicine is None:
            warn(self, f"药品台账中未找到「{self.selected_plan['medicine_name']}」，"
                       "请先在医疗物资管理中建立药品档案", "提示")
            return
        from ui.supply_frame import StockOutDialog
        dialog = StockOutDialog(self, self.user, medicine,
                                preset_person=self.current_id)
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.success:
            self.hint.configure(text="已完成领药扣减", text_color=theme.SUCCESS)


# ---------------------------------------------------------------- 用药登记对话框
class PlanDialog(ctk.CTkToplevel):
    def __init__(self, master, user, person_id, record):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.person_id = person_id
        self.record = record
        self.success = False
        self.inputs = {}
        self._build()

    def _build(self):
        person = personnel_service.get_person(self.person_id) or {}
        title = "编辑用药登记" if self.record else "新增用药登记"
        self.title(title)
        self.resizable(False, False)
        self.transient(self.master.winfo_toplevel())
        self.geometry("560x480")
        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=58)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text=f"{title} — {person.get('name', '')}",
                     font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(16, 0))
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=14)

        specs = [("medicine_name", "药品名称 *"), ("dosage", "剂量"),
                 ("frequency", "频次"), ("start_date", "开始日期"),
                 ("follow_up", "随访记录"), ("note", "备注")]
        form = Card(body, title="用药信息")
        form.pack(fill="x")
        for index, (key, label) in enumerate(specs):
            if key in ("follow_up", "note"):
                cell = ctk.CTkFrame(form.body, fg_color="transparent")
                cell.pack(fill="x", pady=5)
                ctk.CTkLabel(cell, text=label, font=theme.FONT_SMALL, width=96,
                             anchor="nw", text_color=theme.TEXT_PRIMARY).pack(side="left")
                textbox = ctk.CTkTextbox(cell, height=48, width=360, font=theme.FONT_BODY,
                                         fg_color=theme.SURFACE_FORM,
                                         border_color=theme.BORDER, border_width=1,
                                         wrap="word")
                textbox.pack(side="left")
                self.inputs[key] = textbox
            else:
                cell = ctk.CTkFrame(form.body, fg_color="transparent")
                cell.pack(fill="x", pady=5)
                ctk.CTkLabel(cell, text=label, font=theme.FONT_SMALL, width=96,
                             anchor="w", text_color=theme.TEXT_PRIMARY).pack(side="left")
                widget = entry(cell, "", width=360)
                widget.pack(side="left")
                self.inputs[key] = widget

        self.hint = ctk.CTkLabel(body, text="开始日期格式 2026-10-01；"
                                            "药品名称与库存台账一致时可直接领药扣减。",
                                 font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        self.hint.pack(anchor="w", pady=(10, 0))
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        DynamicButton(buttons, text="保存", style="primary", width=120,
                      command=self._submit).pack(side="right")
        DynamicButton(buttons, text="取消", style="ghost", width=88,
                      command=self.destroy).pack(side="right", padx=(0, 10))
        self._fill()
        self.after(120, self.focus_force)

    def _fill(self):
        record = self.record or {}
        for key in ("medicine_name", "dosage", "frequency", "start_date"):
            value = record.get(key)
            if value not in (None, ""):
                self.inputs[key].insert(0, str(value))
        for key in ("follow_up", "note"):
            value = record.get(key)
            if value:
                self.inputs[key].insert("1.0", str(value))

    def _submit(self):
        data = {"person_id": self.person_id}
        for key, widget in self.inputs.items():
            data[key] = (widget.get("1.0", "end").strip() if isinstance(widget, ctk.CTkTextbox)
                         else widget.get())
        ok, message = medicine_service.save_plan(
            self.record["id"] if self.record else None, data, self.user.username)
        if not ok:
            self.hint.configure(text=message, text_color=theme.DANGER)
            return
        self.success = True
        info(self, message, "保存成功")
        self.destroy()


# ---------------------------------------------------------------- 设备使用记录页
class EquipmentUsePage(ctk.CTkFrame):
    """健康视角的医疗设备管理：使用与检查记录，附维保到期提醒。"""

    TITLE = "医疗设备管理"
    DESC = "设备使用与检查记录（使用人 / 时间 / 项目 / 结论），并提醒校准、维保到期设备。"

    COLUMNS = [
        {"key": "equipment_name", "title": "设备名称", "width": 140},
        {"key": "serial_no", "title": "设备编号", "width": 110},
        {"key": "person_name", "title": "使用人", "width": 90},
        {"key": "use_time", "title": "使用时间", "width": 140},
        {"key": "item", "title": "检查项目", "width": 150},
        {"key": "result", "title": "结论", "width": 200},
        {"key": "operator", "title": "经办人", "width": 90},
    ]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.user = app.user
        self.equipment_map = {}
        self.person_map = {}
        self.current_id = None
        self._build()
        self._load_equipment()
        self._load_persons()
        self._load_warnings()
        # 初始渲染记录列表，避免表格数据区留白（无记录时显示「暂无数据」）
        self.refresh()

    def _build(self):
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        self.warning_card = Card(self, title="维保 / 校准到期提醒")
        self.warning_card.pack(fill="x", pady=(theme.GAP, 0))
        self.warning_body = self.warning_card.body

        top = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                           corner_radius=theme.RADIUS_CARD)
        top.pack(fill="x", pady=(theme.GAP, 0))

        pick = ctk.CTkFrame(top, fg_color="transparent")
        pick.pack(fill="x", padx=theme.PAD_CARD, pady=(12, 0))
        field_label(pick, "选择设备").pack(side="left", padx=(0, 6))
        self.equipment_combo = ctk.CTkComboBox(
            pick, values=[""], width=280, height=34, font=theme.FONT_BODY,
            fg_color=theme.SURFACE_FORM, border_color=theme.BORDER,
            button_color=theme.SECONDARY, dropdown_fg_color=theme.SURFACE_CARD,
            dropdown_text_color=theme.TEXT_PRIMARY,
            # 下拉选择即时生效，无需再点「载入」，避免选完设备仍被提示「请先选择一台设备」
            command=self.load_equipment)
        self.equipment_combo.pack(side="left")
        DynamicButton(pick, text="载入", style="primary", width=84,
                      command=self.load_equipment).pack(side="left", padx=(10, 0))
        self.keyword_entry = entry(pick, "设备名称 / 编号 / 使用人", width=176)
        self.keyword_entry.pack(side="left", padx=(16, 6))
        DynamicButton(pick, text="筛选", style="ghost", width=76,
                      command=self.refresh).pack(side="left")

        form = ctk.CTkFrame(top, fg_color="transparent")
        form.pack(fill="x", padx=theme.PAD_CARD, pady=(10, 12))
        self.inputs = {}
        fields = [("use_time", "使用时间", 190), ("item", "检查项目", 190)]
        for index, (key, label, width) in enumerate(fields):
            cell = ctk.CTkFrame(form, fg_color="transparent")
            cell.grid(row=0, column=index, sticky="w", padx=(0, 18))
            ctk.CTkLabel(cell, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_PRIMARY).pack(anchor="w")
            widget = entry(cell, "", width=width)
            widget.pack(anchor="w", pady=(2, 0))
            self.inputs[key] = widget

        person_cell = ctk.CTkFrame(form, fg_color="transparent")
        person_cell.grid(row=0, column=2, sticky="w", padx=(0, 18))
        ctk.CTkLabel(person_cell, text="使用人（可选）", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        self.person_menu = ctk.CTkOptionMenu(
            person_cell, values=["（不指定）"], width=190, height=34,
            font=theme.FONT_BODY, fg_color=theme.SECONDARY,
            button_color=theme.hover(theme.SECONDARY),
            button_hover_color=theme.active(theme.SECONDARY),
            dropdown_fg_color=theme.SURFACE_CARD, dropdown_text_color=theme.TEXT_PRIMARY)
        self.person_menu.pack(anchor="w", pady=(2, 0))

        result_cell = ctk.CTkFrame(form, fg_color="transparent")
        result_cell.grid(row=0, column=3, sticky="w", padx=(0, 18))
        ctk.CTkLabel(result_cell, text="结论", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w")
        self.inputs["result"] = entry(result_cell, "检查结论", width=190)
        self.inputs["result"].pack(anchor="w", pady=(2, 0))

        self.save_button = DynamicButton(form, text="登记记录", style="primary",
                                         width=112, command=self.save)
        self.save_button.grid(row=0, column=4, sticky="s", pady=(2, 0))
        if not self.user.can("equipment.update"):
            self.save_button.set_enabled(False)
        self.form_hint = ctk.CTkLabel(top, text="", font=theme.FONT_SMALL,
                                      wraplength=1100, justify="left",
                                      text_color=theme.TEXT_SECONDARY)
        self.form_hint.pack(anchor="w", padx=theme.PAD_CARD, pady=(0, 10))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="both", expand=True, pady=(theme.GAP, 0))
        actions = ctk.CTkFrame(bottom, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(theme.GAP, 0))
        ctk.CTkLabel(actions, text="选中一条记录可删除",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        if self.user.can("equipment.delete"):
            DynamicButton(actions, text="删除记录", style="danger", width=112,
                          command=self.delete_selected).pack(side="right")
        self.table = DataTable(bottom, self.COLUMNS, page_size=20)
        self.table.pack(fill="both", expand=True)

        self.inputs["use_time"].insert(0, personnel_service.now_text())

    # ------------------------------------------------------------ 数据
    def _load_equipment(self):
        rows = equipment_service.list_equipment()
        self.equipment_map = {}
        for row in rows:
            self.equipment_map[f"{row['name']}（{row['serial_no']}）"] = row["id"]
        values = list(self.equipment_map.keys()) or ["（无设备）"]
        self.equipment_combo.configure(values=values)
        self.equipment_combo.set(values[0])
        # 默认选中首台设备并同步 current_id：控件已显示设备时不应再要求用户额外点「载入」
        self.current_id = self.equipment_map.get(values[0])

    def _load_persons(self):
        rows, _total = personnel_service.list_personnel(
            page=1, page_size=2000, only_onboard=True)
        self.person_map = {}
        for row in rows:
            self.person_map[f"{row['emp_no']} {row['name']}"] = row["id"]
        self.person_menu.configure(values=["（不指定）"] + list(self.person_map.keys()))
        self.person_menu.set("（不指定）")

    def _load_warnings(self):
        for child in self.warning_body.winfo_children():
            child.destroy()
        warnings = equipment_service.equipment_warnings()
        if not warnings:
            ctk.CTkLabel(self.warning_body, text="全部设备维保正常。",
                         font=theme.FONT_SMALL,
                         text_color=theme.SUCCESS).pack(anchor="w", pady=4)
            return
        from ui.widgets import StatusTag
        for item in warnings[:6]:
            row = ctk.CTkFrame(self.warning_body, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"{item['name']}（{item['code']}）  {item['detail']}",
                         font=theme.FONT_SMALL, anchor="w",
                         text_color=theme.TEXT_PRIMARY).pack(side="left")
            StatusTag(row, text="已超期" if item["level"] == "红色报警" else "即将到期",
                      level=item["level"]).pack(side="right", padx=(8, 0))
        if len(warnings) > 6:
            ctk.CTkLabel(self.warning_body, text=f"其余 {len(warnings) - 6} 台略",
                         font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w")

    def _resolve_equipment(self):
        """把下拉框文本解析为设备 id：精确匹配优先，手输时按名称前缀容错（忽略编号后缀）。"""
        display = self.equipment_combo.get().strip()
        if display in self.equipment_map:
            return self.equipment_map[display]
        for key, value in self.equipment_map.items():
            if display and (key.startswith(display) or display.startswith(key)):
                return value
        return None

    def load_equipment(self):
        self.current_id = self._resolve_equipment()
        if self.current_id is None:
            warn(self, "请先选择一台设备", "提示")
            return
        self.refresh()

    def refresh(self):
        keyword = self.keyword_entry.get().strip() or None
        rows = equipment_service.list_uses(equipment_id=self.current_id, keyword=keyword)
        self.table.set_data(rows)

    def save(self):
        if self.current_id is None:
            # 兜底：下拉框已显示设备但 current_id 尚未同步时，按当前文本再解析一次
            self.current_id = self._resolve_equipment()
        if self.current_id is None:
            warn(self, "请先选择一台设备", "提示")
            return
        data = {"use_time": self.inputs["use_time"].get(),
                "item": self.inputs["item"].get(),
                "result": self.inputs["result"].get(),
                "person_id": self.person_map.get(self.person_menu.get())}
        ok, message = equipment_service.save_use(self.current_id, data, self.user.username)
        if not ok:
            self.form_hint.configure(text=message, text_color=theme.DANGER)
            return
        self.form_hint.configure(text=message, text_color=theme.SUCCESS)
        self.inputs["item"].delete(0, "end")
        self.inputs["result"].delete(0, "end")
        self.refresh()

    def delete_selected(self):
        record = self.table.get_selected()
        if record is None:
            warn(self, "请先选中要删除的使用记录", "提示")
            return
        if not confirm(self, f"确认删除 {record['equipment_name']} "
                             f"{record['use_time']} 的使用记录？", "删除确认"):
            return
        ok, message = equipment_service.delete_use(record["id"], self.user.username)
        if not ok:
            warn(self, message, "删除失败")
            return
        info(self, message, "删除完成")
        self.refresh()