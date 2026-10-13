"""启动器主界面：exe 双击（无子命令）时显示的引导界面。

提供四个入口按钮（打开配置 / 启动托盘 / 开始自动登录 / 使用教程），
复用配置界面的配色与圆角按钮样式。
"""
from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .config_gui import (
    C, F, GITHUB_URL, RoundedButton, STAR_HINT, TUTORIAL_TEXT, _open_url, _tool_root,
)


def _launch_subprocess(*args: str) -> None:
    """用独立进程启动某个子命令（frozen 用 exe，源码用 python -m）。"""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, *args]
    else:
        cmd = [sys.executable, "-m", "campus_auth", *args]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(cmd, cwd=str(_tool_root()), creationflags=creationflags)


class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("校园网自动登录")
        root.geometry("560x620")
        root.minsize(520, 580)
        root.configure(bg=C["card"])

        self._build()

    def _build(self) -> None:
        body = tk.Frame(self.root, bg=C["card"])
        body.pack(fill="both", expand=True, padx=36, pady=28)

        tk.Label(body, text="校园网自动登录", bg=C["card"], fg=C["text"],
                 font=(F["ui"], 22, "bold")).pack(anchor="w")
        tk.Label(body, text="配置一次，自动守护，断线重连", bg=C["card"], fg=C["muted"],
                 font=(F["ui"], 10)).pack(anchor="w", pady=(4, 24))

        # 主按钮：打开配置界面
        RoundedButton(body, "打开配置界面", self._open_config,
                      fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"],
                      bold=True, font_size=11, height=44).pack(fill="x", pady=6)

        RoundedButton(body, "启动系统托盘", self._start_tray, height=40).pack(fill="x", pady=6)
        RoundedButton(body, "开始自动登录", self._start_watch, height=40).pack(fill="x", pady=6)
        RoundedButton(body, "使用教程", self._show_tutorial, height=40).pack(fill="x", pady=6)

        # 底部信息
        footer = tk.Frame(body, bg=C["card"])
        footer.pack(side="bottom", fill="x")
        gh = tk.Label(footer, text=f"GitHub: {GITHUB_URL}", bg=C["card"], fg=C["primary"],
                      font=(F["ui"], 8, "underline"), cursor="hand2")
        gh.pack(anchor="w", pady=(0, 2))
        gh.bind("<Button-1>", lambda e: _open_url(GITHUB_URL))
        star_row = tk.Frame(footer, bg=C["card"])
        star_row.pack(anchor="w", pady=(0, 4))
        tk.Label(star_row, text="本软件完全免费，如果对你有所帮助，请为我点一个 ", bg=C["card"],
                 fg=C["text"], font=(F["ui"], 8)).pack(side="left")
        tk.Label(star_row, text="star", bg=C["card"], fg="#f5a623",
                 font=(F["ui"], 8, "bold")).pack(side="left")
        tk.Label(footer, text="免责声明：本软件完全免费，仅供学习交流，用于自动完成本人账号在所在校园网的认证。",
                 bg=C["card"], fg=C["muted"], font=(F["ui"], 7), wraplength=480,
                 justify="left").pack(anchor="w")

        # 退出按钮
        exit_row = tk.Frame(self.root, bg=C["card"])
        exit_row.pack(side="bottom", fill="x", padx=36, pady=(0, 20))
        RoundedButton(exit_row, "退出", self.root.destroy, font_size=9, padx=16).pack(side="right")

    # ---- 动作 ----

    def _open_config(self) -> None:
        self.root.destroy()
        from .config_gui import run_gui
        run_gui()

    def _start_tray(self) -> None:
        _launch_subprocess("tray")
        self.root.destroy()

    def _start_watch(self) -> None:
        _launch_subprocess("watch", "--startup")
        messagebox.showinfo("已开始", "自动登录已在后台启动。\n\n若未配置账号密码，请先「打开配置界面」完成配置。")

    def _show_tutorial(self) -> None:
        top = tk.Toplevel(self.root)
        top.title("使用教程")
        top.geometry("600x540")
        top.configure(bg=C["card"])
        top.transient(self.root)
        top.grab_set()

        tk.Label(top, text="使用教程", bg=C["card"], fg=C["text"],
                 font=(F["ui"], 18, "bold")).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(top, text="三步完成配置，让工具自动登录校园网",
                 bg=C["card"], fg=C["muted"], font=(F["ui"], 10)).pack(anchor="w", padx=24, pady=(0, 12))

        content = tk.Text(top, height=16, bg=C["card"], fg=C["text"], font=(F["ui"], 10),
                          relief="flat", wrap="word", spacing1=2, spacing3=6,
                          highlightthickness=0, cursor="arrow")
        content.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        content.insert("1.0", TUTORIAL_TEXT)
        content.configure(state="disabled")

        row = tk.Frame(top, bg=C["card"])
        row.pack(side="bottom", fill="x", padx=24, pady=(0, 20))
        RoundedButton(row, "知道了", top.destroy,
                      fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"],
                      bold=True).pack(side="right")


def run_launcher() -> int:
    from .config_gui import _enable_dpi_awareness
    _enable_dpi_awareness()
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
    return 0
