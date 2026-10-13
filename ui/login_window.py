# -*- coding: utf-8 -*-
"""登录界面：账号密码登录、错误提示与锁定提示、首次登录强制改密。"""

import customtkinter as ctk

import config
from services import auth_service
from ui import theme
from ui.widgets import DynamicButton, center_on_screen


class LoginFrame(ctk.CTkFrame):
    """登录面板，登录成功后通过 on_success(user) 通知主程序切换界面。"""

    def __init__(self, master, on_success):
        super().__init__(master, fg_color=theme.SURFACE_FORM, corner_radius=0)
        self.on_success = on_success
        self._build()

    # ------------------------------------------------------------ 界面
    def _build(self):
        banner = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=132)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        ctk.CTkLabel(banner, text=config.APP_SHORT_NAME, font=theme.FONT_TITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=(34, 4))
        ctk.CTkLabel(banner, text=f"{config.COMPANY}  ·  V{config.APP_VERSION}",
                     font=theme.FONT_SMALL,
                     text_color=theme.NAV_TEXT).pack()

        form = ctk.CTkFrame(self, fg_color=theme.SURFACE_CARD,
                            corner_radius=theme.RADIUS_CARD)
        form.pack(fill="both", expand=True, padx=36, pady=28)

        ctk.CTkLabel(form, text="账号登录", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(form, text="请使用平台管理员分配的账号登录",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w", padx=24)

        self.username_entry = ctk.CTkEntry(
            form, placeholder_text="账号", height=38, font=theme.FONT_BODY,
            fg_color=theme.SURFACE_FORM, border_color=theme.BORDER)
        self.username_entry.pack(fill="x", padx=24, pady=(20, 10))

        self.password_entry = ctk.CTkEntry(
            form, placeholder_text="密码", show="●", height=38, font=theme.FONT_BODY,
            fg_color=theme.SURFACE_FORM, border_color=theme.BORDER)
        self.password_entry.pack(fill="x", padx=24)

        self.message_label = ctk.CTkLabel(form, text=" ", font=theme.FONT_SMALL,
                                          text_color=theme.DANGER, wraplength=300,
                                          justify="left")
        self.message_label.pack(fill="x", padx=24, pady=(8, 0))

        self.login_button = DynamicButton(form, text="登 录", style="primary",
                                          width=200, height=40, command=self._do_login)
        self.login_button.pack(fill="x", padx=24, pady=(6, 8))

        ctk.CTkLabel(form, text=f"连续 {config.LOGIN_MAX_FAIL} 次密码错误将锁定账号 "
                                f"{config.LOGIN_LOCK_MINUTES} 分钟",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(pady=(0, 18))

        self.username_entry.bind("<Return>", lambda _e=None: self.password_entry.focus_set())
        self.password_entry.bind("<Return>", lambda _e=None: self._do_login())
        self.username_entry.focus_set()

    # ------------------------------------------------------------ 登录逻辑
    def _do_login(self):
        self.login_button.set_loading(True, "登录中…")
        self.update_idletasks()
        user, message = auth_service.authenticate(
            self.username_entry.get(), self.password_entry.get())
        self.login_button.set_loading(False)

        if user is None:
            self._show_message(message)
            self.password_entry.delete(0, "end")
            self.password_entry.focus_set()
            return

        if user.must_change_pwd:
            if not self._force_change_password(user):
                self._show_message("首次登录需修改初始密码后才能进入系统")
                return

        self.on_success(user)

    def _force_change_password(self, user):
        dialog = ChangePasswordDialog(self, user, forced=True)
        dialog.grab_set()
        self.wait_window(dialog)
        return dialog.success

    def _show_message(self, text, color=None):
        self.message_label.configure(text=text, text_color=color or theme.DANGER)


class ChangePasswordDialog(ctk.CTkToplevel):
    """修改密码对话框：首次登录强制修改，也可由用户主动调用。"""

    def __init__(self, master, user, forced=False):
        super().__init__(master, fg_color=theme.SURFACE_FORM)
        self.user = user
        self.success = False

        self.title("修改密码")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        center_on_screen(self, 380, 400)
        self._build(forced)
        # 置顶显示，避免模态窗口被登录窗遮挡而被误认为"点了没反应"
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.after(120, self.focus_force)

    def _build(self, forced):
        head = ctk.CTkFrame(self, fg_color=theme.PRIMARY, corner_radius=0, height=64)
        head.pack(fill="x")
        head.pack_propagate(False)
        title = "首次登录必须修改初始密码" if forced else "修改密码"
        ctk.CTkLabel(head, text=title, font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_ON_PRIMARY).pack(pady=18)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=18)

        ctk.CTkLabel(body, text=f"当前账号：{self.user.username}",
                     font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY).pack(anchor="w")

        self.old_entry = self._entry(body, "原密码")
        self.new_entry = self._entry(body, "新密码")
        self.confirm_entry = self._entry(body, "确认新密码")

        ctk.CTkLabel(body, text=config.PASSWORD_RULE_TEXT, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))

        self.message_label = ctk.CTkLabel(body, text=" ", font=theme.FONT_SMALL,
                                          text_color=theme.DANGER, wraplength=310,
                                          justify="left")
        self.message_label.pack(anchor="w", pady=(6, 0))

        DynamicButton(body, text="确认修改", style="primary", width=200, height=38,
                      command=self._submit).pack(fill="x", pady=(8, 0))
        self.old_entry.focus_set()
        self.confirm_entry.bind("<Return>", lambda _e=None: self._submit())

    def _entry(self, parent, placeholder):
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder, show="●", height=36,
                             font=theme.FONT_BODY, fg_color=theme.SURFACE_CARD,
                             border_color=theme.BORDER)
        entry.pack(fill="x", pady=(12, 0))
        return entry

    def _submit(self):
        if self.new_entry.get() != self.confirm_entry.get():
            self.message_label.configure(text="两次输入的新密码不一致")
            return
        ok, message = auth_service.change_password(
            self.user.id, self.old_entry.get(), self.new_entry.get())
        if not ok:
            self.message_label.configure(text=message)
            return
        self.user.must_change_pwd = False
        self.success = True
        self.destroy()