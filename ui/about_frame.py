# -*- coding: utf-8 -*-
"""作者页面：展示软件版权归属、使用致谢与技术支持联系方式。

对全部登录用户可见，不依赖任何业务权限；内容为静态信息，无需数据库查询。
"""

import customtkinter as ctk

import config
from ui import theme
from ui.widgets import Card, page_header


class AboutPage(ctk.CTkFrame):
    """软件版权与联系方式。"""

    TITLE = "作者信息"
    DESC = "软件版权归属、使用致谢与技术支持联系方式。"

    COPYRIGHT = "本软件版权归 平湖秋月 所有"
    WELCOME = "欢迎大家使用。"
    CONTACT = "使用中有任何问题，请联系：lizhiqiang087@sinopec.cn"

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        page_header(self, self.TITLE, self.DESC).pack(fill="x")

        card = Card(self, title="关于本软件", accent=theme.module_color("about"))
        card.pack(fill="x", pady=(theme.GAP, 0))

        ctk.CTkLabel(card.body, text=f"{config.APP_NAME}  V{config.APP_VERSION}",
                     font=theme.FONT_SUBTITLE, text_color=theme.TEXT_PRIMARY,
                     anchor="w").pack(anchor="w", pady=(2, 12))

        for text, color in ((self.COPYRIGHT, theme.TEXT_PRIMARY),
                            (self.WELCOME, theme.TEXT_PRIMARY),
                            (self.CONTACT, theme.TEXT_SECONDARY)):
            ctk.CTkLabel(card.body, text=text, font=theme.FONT_BODY,
                         text_color=color, anchor="w").pack(anchor="w", pady=(0, 8))