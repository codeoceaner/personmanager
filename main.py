# -*- coding: utf-8 -*-
"""海上平台人员动态管理系统 —— 程序入口。

启动顺序：初始化数据库 → 每日自动备份 → 内置账号 → 登录界面 → 主窗口。
"""

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _bootstrap_dirs():
    """把临时目录与 matplotlib 配置目录固定到程序目录下的纯英文路径。

    中文 Windows 用户名会让 %TEMP%、.matplotlib 等落在中文路径下，导致底层库
    （matplotlib / sqlite）静默失败。必须在导入任何第三方库之前执行。
    """
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent)
    for name, env in (("_tmp", "TEMP"), ("_mplconfig", "MPLCONFIGDIR")):
        target = base / name
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        os.environ[env] = str(target)
        if env == "TEMP":
            os.environ["TMP"] = str(target)


_bootstrap_dirs()

sys.path.insert(0, str(Path(__file__).resolve().parent))

import customtkinter as ctk  # noqa: E402

import config  # noqa: E402
from db import database  # noqa: E402
from services import assign_service, auth_service  # noqa: E402
from ui import theme  # noqa: E402
from ui.login_window import LoginFrame  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.widgets import center_on_screen  # noqa: E402

# ---------------------------------------------------------------- 运行日志
# 打包版为无控制台的 windowed 模式，异常会丢失。这里统一落盘到 data/logs/error.log，
# 并弹窗提示，避免"点了没反应、又看不到报错"的情况。
_logger = logging.getLogger("app")


def _setup_crash_log():
    log_dir = config.APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    if not _logger.handlers:
        handler = RotatingFileHandler(log_dir / "error.log", maxBytes=2_000_000,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        _logger.addHandler(handler)
    _logger.setLevel(logging.ERROR)


def _report_error(context, text):
    try:                                                # 写入失败（如目录只读）也不能影响弹窗
        _logger.error("%s\n%s", context, text)
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from tkinter import messagebox
        messagebox.showerror("程序异常", f"{context}\n\n{text[-1500:]}")
    except Exception:                                   # noqa: BLE001 弹窗失败时忽略
        pass


def _excepthook(exc_type, exc, tb):
    _report_error("未捕获异常", "".join(traceback.format_exception(exc_type, exc, tb)))


def _tk_callback_excepthook(self, exc, val, tb):
    """Tkinter 回调内异常会被 Tk 静默吞掉，这里改为落盘并提示。"""
    _report_error("界面回调异常", "".join(traceback.format_exception(exc, val, tb)))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.current_user = None

        self.title(f"{config.APP_NAME}  V{config.APP_VERSION}")
        self.configure(fg_color=theme.SURFACE_FORM)
        self.show_login()

    # ------------------------------------------------------------ 界面切换
    def _clear(self):
        for child in self.winfo_children():
            child.destroy()

    def show_login(self):
        self.current_user = None
        self._clear()
        self.resizable(False, False)
        self.minsize(*config.LOGIN_WINDOW_SIZE)
        center_on_screen(self, *config.LOGIN_WINDOW_SIZE)
        LoginFrame(self, on_success=self.on_login_success).pack(fill="both", expand=True)

    def on_login_success(self, user):
        self.current_user = user
        self._clear()
        self.resizable(True, True)
        # 窗口尺寸不超过屏幕可用区域，避免右侧按钮与底部状态栏被裁掉
        width = min(config.WINDOW_SIZE[0], self.winfo_screenwidth() - 40)
        height = min(config.WINDOW_SIZE[1], self.winfo_screenheight() - 80)
        self.minsize(min(config.WINDOW_MIN_SIZE[0], width),
                     min(config.WINDOW_MIN_SIZE[1], height))
        center_on_screen(self, width, height)
        MainWindow(self, user, on_logout=self.show_login).pack(fill="both", expand=True)


def main():
    theme.apply_theme()
    _setup_crash_log()
    sys.excepthook = _excepthook
    ctk.CTk.report_callback_exception = _tk_callback_excepthook

    database.init_database()
    database.auto_backup_daily()
    auth_service.ensure_default_admin()
    assign_service.seed_default_resources()

    App().mainloop()


if __name__ == "__main__":
    main()