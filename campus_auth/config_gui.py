"""配置界面：用可视化表单填写门户画像，生成 portal.json。

纯标准库 tkinter 实现，可打包成独立 exe（不要求目标用户安装 Python）。
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .portal import DEFAULT_PROFILE, deep_merge

# 认证引擎模式
MODES = ("workflow", "simple")

# --------------------------------------------------------------------------
# 配色与字体（简约现代 / iOS 系统风格）
# --------------------------------------------------------------------------
C = {
    "page": "#f2f2f7",       # 系统背景（浅灰，近白）
    "card": "#ffffff",       # 卡片
    "primary": "#007aff",    # 强调蓝
    "primary_hover": "#0066d6",
    "text": "#1c1c1e",       # 主文字（近黑）
    "muted": "#8e8e93",      # 次要文字
    "border": "#e5e5ea",     # 分隔线
    "input": "#ffffff",      # 输入框背景
    "tab": "#f2f2f7",        # 未选中标签
    "white": "#ffffff",
}
F = {
    "ui": "Microsoft YaHei UI",
    "mono": "Consolas",
}


# --------------------------------------------------------------------------
# 圆角组件（tkinter 无原生圆角，用 Canvas 自绘）
# --------------------------------------------------------------------------

def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """在 canvas 上画一个圆角矩形（smooth 多边形近似圆角）。"""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


class RoundedButton(tk.Canvas):
    """圆角按钮：Canvas 自绘，支持 hover 与点击。"""

    def __init__(self, parent, text, command=None, *, fill=C["card"], fg=C["text"],
                 border=C["border"], hover_fill="#f2f2f7", hover_border=C["primary"],
                 radius=10, bold=False, font_size=10, padx=24, height=36):
        self._text = text
        self._command = command
        self._fill = fill
        self._fg = fg
        self._border = border
        self._hover_fill = hover_fill
        self._hover_border = hover_border
        self._radius = radius
        self._font = (F["ui"], font_size, "bold" if bold else "normal")
        self._hovered = False

        import tkinter.font as tkfont
        font_obj = tkfont.Font(family=F["ui"], size=font_size, weight="bold" if bold else "normal")
        self._btn_w = font_obj.measure(text) + padx * 2
        self._btn_h = height
        super().__init__(parent, width=self._btn_w, height=self._btn_h, bg=C["page"],
                         highlightthickness=0, bd=0, cursor="hand2")

        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_enter)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._repaint()

    def _fill_now(self):
        return self._hover_fill if self._hovered else self._fill

    def _border_now(self):
        return self._hover_border if self._hovered else self._border

    def _repaint(self) -> None:
        self.delete("all")
        # 未映射时 winfo_width()/winfo_height() 返回 1，回退到构造尺寸
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            w = self._btn_w
        if h <= 1:
            h = self._btn_h
        _round_rect(self, 1, 1, w - 1, h - 1, self._radius,
                    fill=self._fill_now(), outline=self._border_now(), width=1)
        self.create_text(w // 2, h // 2, text=self._text, fill=self._fg, font=self._font)

    def _on_configure(self, event) -> None:
        self._repaint()

    def _on_enter(self, event=None) -> None:
        self._hovered = True
        self._repaint()

    def _on_leave(self, event=None) -> None:
        self._hovered = False
        self._repaint()

    def _on_release(self, event=None) -> None:
        if self._command:
            self._command()
        self._hovered = False
        self._repaint()

# 各字段的中文说明（key 为扁平字段路径，value 为显示标签）
_FIELD_LABELS = {
    "portal.host": "门户主机（IP 或域名）",
    "portal.port": "端口",
    "portal.scheme": "协议（http/https）",
    "portal.entry_path": "登录入口路径",
    "endpoints.query_terminal": "终端信息接口",
    "endpoints.online_info": "在线判定接口",
    "endpoints.service_selection": "服务列表接口",
    "endpoints.service_login": "服务登录接口",
    "endpoints.operator_login": "运营商确认接口",
    "endpoints.set_service": "确认服务接口",
    "endpoints.get_current_node": "取当前节点接口",
    "endpoints.update_session": "提交账号密码接口",
    "session.mode": "会话获取方式（captive/manual）",
    "session.field_name": "sessionId 参数名",
    "session.flow_key": "工作流 flowKey",
    "session.redirect_probe_url": "captive 探测 URL",
    "workflow.auth_type": "账号密码认证的 authType 值",
    "workflow.result_value": "result 字段的成功值",
    "workflow.credential_fields.username": "账号字段名",
    "workflow.credential_fields.password": "密码字段名",
    "workflow.credential_fields.auth_type": "authType 字段名",
    "workflow.service_fields.session_id": "服务请求的 sessionId 字段名",
    "workflow.service_fields.service": "服务名字段名",
    "simple_login.login_path": "登录接口路径",
    "simple_login.method": "请求方法（POST/GET）",
    "simple_login.username_field": "账号字段名",
    "simple_login.password_field": "密码字段名",
    "online_check.path_field": "在线判定字段路径（点号分隔）",
    "online_check.success_value": "在线成功值",
    "connectivity.probe_hosts": "外网探测站点（逗号分隔）",
    "connectivity.probe_port": "外网探测端口",
}


def _get(data: dict, dotted: str, default=""):
    current = data
    for key in dotted.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def _set(data: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    current = data
    for key in keys[:-1]:
        nxt = current.setdefault(key, {})
        if not isinstance(nxt, dict):
            nxt = current[key] = {}
        current = nxt
    current[keys[-1]] = value


def _parse_address(text: str) -> tuple[str, int, str]:
    """把用户填的地址解析成 (host, port, scheme)。支持 10.0.0.1 / http://host / host:8080。"""
    import urllib.parse
    text = text.strip()
    if "://" not in text:
        text = "http://" + text
    parts = urllib.parse.urlsplit(text)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    scheme = parts.scheme or "http"
    return host, port, scheme


# 预设门户模板：傻瓜式用户只需选类型 + 填地址，其余字段自动填好。
# 值 None 表示"沿用内置默认（锐捷 SAM+）"。
PORTAL_TEMPLATES: dict[str, dict | None] = {
    "锐捷 SAM+（工作流）": None,
    "通用（简单登录）": {
        "auth_mode": "simple",
        "simple_login": {
            "login_path": "",
            "method": "POST",
            "username_field": "username",
            "password_field": "password",
            "extra_fields": {},
        },
        "online_check": {"path_field": "", "success_value": "success"},
    },
    "自定义（手动填写）": None,
}

# 使用教程内容
TUTORIAL_TEXT = """这个工具帮你自动登录校园网：配置一次，即可后台静默守护、断线自动重连。

① 填写门户地址
   输入你学校认证页的地址，
   例如 10.0.0.1 或 portal.school.edu.cn

② 自动探测类型
   点「自动探测类型」，自动识别锐捷 SAM+ / 深澜 等厂商

③ 一键生成配置
   点「一键生成配置」，接口路径、字段名等细节自动填好

④ 开始自动登录
   点底部「开始自动登录」，填写账号、密码和运营商，
   程序即在后台开始守护，断线会自动重连

⑤ 开机自启（可选）
   勾选「开机自启」，以后重启电脑会自动以托盘图标运行

需要改接口路径、字段名等细节？
点「高级设置」展开全部字段。

──────
免责声明：本工具仅供学习交流，用于自动完成本人账号在所在校园网的认证，请遵守所在学校网络使用规定；使用产生的一切后果由使用者自行承担。"""

# 首次使用标记：放在用户配置目录，看到教程后不再自动弹出
TUTORIAL_MARKER = Path.home() / ".campus-auth" / ".tutorial_shown"

# GitHub 主页地址
GITHUB_URL = "https://github.com/JianHeShui/campus-auth"
# GitHub 下的一行宣传语
STAR_HINT = "本软件完全免费，如果对你有所帮助，请为我点一个 star，谢谢喵"


def _open_url(url: str) -> None:
    """用默认浏览器打开链接（一键跳转）。"""
    import webbrowser
    webbrowser.open(url)


def _tool_root() -> Path:
    """工具目录：打包后为 exe 所在目录，源码运行为项目根目录。"""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _credentials_file_hint() -> str:
    """凭据文件路径（用于提示用户）。"""
    from .config import CREDENTIALS_FILE
    return str(CREDENTIALS_FILE)


class ConfigWindow:
    """门户画像配置窗口。"""

    def __init__(self, root: tk.Tk, profile_path: str | None = None):
        self.root = root
        self.profile_path = Path(profile_path) if profile_path else None
        self.vars: dict[str, tk.StringVar] = {}
        self.extra_fields_text: tk.Text | None = None
        self.error_markers_text: tk.Text | None = None
        self.preview_text: tk.Text | None = None
        self.template_var: tk.StringVar | None = None
        self.address_var: tk.StringVar | None = None
        self.advanced_visible = False

        root.title("校园网认证 · 门户配置")
        root.geometry("1140x920")
        root.minsize(1080, 860)
        root.configure(bg=C["page"])

        self._apply_theme()
        self._build_header()
        self._build_quick_start()
        self._build_advanced_toggle()
        self._build_notebook()
        self._build_footer()
        self._load(DEFAULT_PROFILE)
        self.refresh_preview()
        # 首次使用自动弹出教程
        if not TUTORIAL_MARKER.exists():
            self.root.after(400, self._show_tutorial)

    # ---- 主题 ----

    def _apply_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=(F["ui"], 10), background=C["page"], foreground=C["text"])

        # 卡片式面板
        style.configure("Card.TFrame", background=C["card"])
        style.configure("Page.TFrame", background=C["page"])

        # 标签
        style.configure("TLabel", background=C["page"], foreground=C["text"])
        style.configure("Card.TLabel", background=C["card"], foreground=C["text"])
        style.configure("Muted.TLabel", background=C["page"], foreground=C["muted"], font=(F["ui"], 9))
        style.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"], font=(F["ui"], 9))
        style.configure("Section.TLabel", background=C["card"], foreground=C["text"],
                        font=(F["ui"], 11, "bold"))

        # 输入框
        style.configure("TEntry", fieldbackground=C["input"], foreground=C["text"],
                        bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                        padding=7)
        style.map("TEntry", bordercolor=[("focus", C["primary"])], lightcolor=[("focus", C["primary"])],
                  darkcolor=[("focus", C["primary"])])

        # 下拉框
        style.configure("TCombobox", fieldbackground=C["input"], foreground=C["text"],
                        background=C["white"], bordercolor=C["border"], lightcolor=C["border"],
                        darkcolor=C["border"], padding=6)

        # 按钮
        style.configure("TButton", background=C["card"], foreground=C["text"],
                        bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                        padding=(16, 8), font=(F["ui"], 10))
        style.map("TButton",
                  background=[("active", "#f2f2f7"), ("pressed", "#e9e9ee")],
                  bordercolor=[("active", C["primary"])], lightcolor=[("active", C["primary"])],
                  darkcolor=[("active", C["primary"])])

        # 主按钮（蓝色填充）
        style.configure("Primary.TButton", background=C["primary"], foreground=C["white"],
                        bordercolor=C["primary"], padding=(20, 9), font=(F["ui"], 10, "bold"))
        style.map("Primary.TButton",
                  background=[("active", C["primary_hover"]), ("pressed", C["primary_hover"])],
                  bordercolor=[("active", C["primary_hover"])])

        # 标签页
        style.configure("TNotebook", background=C["page"], borderwidth=0, tabmargins=(0, 8, 0, 0))
        style.configure("TNotebook.Tab", background=C["tab"], foreground=C["muted"],
                        padding=(18, 9), font=(F["ui"], 10))
        style.map("TNotebook.Tab",
                  background=[("selected", C["card"])],
                  foreground=[("selected", C["primary"])])

        # 复选框（白底）
        style.configure("Card.TCheckbutton", background=C["card"], foreground=C["text"])

    # ---- 结构 ----

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=C["card"])
        header.pack(fill="x")
        title_row = tk.Frame(header, bg=C["card"])
        title_row.pack(fill="x", padx=24, pady=(18, 2))
        tk.Label(title_row, text="门户配置", bg=C["card"], fg=C["text"],
                 font=(F["ui"], 21, "bold")).pack(side="left")
        RoundedButton(title_row, "使用教程", self._show_tutorial, font_size=9, padx=18).pack(side="right")
        tk.Label(header, text="填写你所在学校的门户信息，自动生成 portal.json",
                 bg=C["card"], fg=C["muted"], font=(F["ui"], 10)).pack(anchor="w", padx=24, pady=(0, 6))
        gh = tk.Label(header, text=f"GitHub: {GITHUB_URL}", bg=C["card"], fg=C["primary"],
                      font=(F["ui"], 9, "underline"), cursor="hand2")
        gh.pack(anchor="w", padx=24, pady=(0, 2))
        gh.bind("<Button-1>", lambda e: _open_url(GITHUB_URL))
        # 彩色 star 文案：分段用不同颜色拼接
        star_row = tk.Frame(header, bg=C["card"])
        star_row.pack(anchor="w", padx=24, pady=(0, 12))
        tk.Label(star_row, text="本软件完全免费，如果对你有所帮助，请为我点一个 ", bg=C["card"],
                 fg=C["text"], font=(F["ui"], 9)).pack(side="left")
        tk.Label(star_row, text="star", bg=C["card"], fg="#f5a623",
                 font=(F["ui"], 9, "bold")).pack(side="left")
        tk.Label(star_row, text="，谢谢喵", bg=C["card"], fg="#ff6b9d",
                 font=(F["ui"], 9)).pack(side="left")
        # 底部分隔线
        tk.Frame(header, bg=C["border"], height=1).pack(fill="x")

    def _show_tutorial(self) -> None:
        """弹出使用教程窗口。"""
        top = tk.Toplevel(self.root)
        top.title("使用教程")
        top.geometry("600x540")
        top.configure(bg=C["card"])
        top.transient(self.root)
        top.grab_set()

        # 底部按钮行：先 pack 到 bottom，确保始终可见
        row = tk.Frame(top, bg=C["card"])
        row.pack(side="bottom", fill="x", padx=24, pady=(0, 20))
        self.dont_show_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="下次不再自动弹出", variable=self.dont_show_var,
                       bg=C["card"], fg=C["text"], activebackground=C["card"],
                       activeforeground=C["text"], selectcolor=C["card"],
                       font=(F["ui"], 10), highlightthickness=0).pack(side="left")
        RoundedButton(row, "知道了", self._close_tutorial,
                      fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"],
                      bold=True).pack(side="right")

        # 标题、副标题、正文（在底部按钮行之上）
        tk.Label(top, text="使用教程", bg=C["card"], fg=C["text"],
                 font=(F["ui"], 18, "bold")).pack(side="top", anchor="w", padx=24, pady=(20, 4))
        tk.Label(top, text="三步完成配置，让工具自动登录校园网",
                 bg=C["card"], fg=C["muted"], font=(F["ui"], 10)).pack(side="top", anchor="w", padx=24, pady=(0, 12))

        content = tk.Text(top, height=12, bg=C["card"], fg=C["text"], font=(F["ui"], 10),
                          relief="flat", wrap="word", spacing1=2, spacing3=6,
                          highlightthickness=0, cursor="arrow")
        content.pack(side="top", fill="both", expand=True, padx=24, pady=(0, 12))
        content.insert("1.0", TUTORIAL_TEXT)
        content.configure(state="disabled")

    def _close_tutorial(self) -> None:
        """关闭教程；勾选「下次不再自动弹出」时写入首次标记。"""
        if getattr(self, "dont_show_var", None) is None or self.dont_show_var.get():
            try:
                TUTORIAL_MARKER.parent.mkdir(parents=True, exist_ok=True)
                TUTORIAL_MARKER.touch()
            except OSError:
                pass  # 写标记失败不阻塞使用，只是下次仍会弹
        # 关闭当前教程 Toplevel
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel) and child.title() == "使用教程":
                child.destroy()

    def _build_quick_start(self) -> None:
        """傻瓜式快速开始：选类型 + 填地址，一键生成。"""
        wrap = ttk.Frame(self.root, style="Page.TFrame")
        wrap.pack(fill="x", padx=18, pady=(16, 0))
        card = ttk.Frame(wrap, style="Card.TFrame", padding=20)
        card.pack(fill="x")

        ttk.Label(card, text="快速开始", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(card, text="只需两步：选择门户类型，填写门户网页地址",
                  style="CardMuted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 10))

        # 第一行：类型 + 地址
        ttk.Label(card, text="门户类型", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
        self.template_var = tk.StringVar(value=list(PORTAL_TEMPLATES.keys())[0])
        ttk.Combobox(card, textvariable=self.template_var, values=list(PORTAL_TEMPLATES.keys()),
                     state="readonly", width=22).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(card, text="门户地址", style="Card.TLabel").grid(row=2, column=2, sticky="w", padx=(16, 10), pady=4)
        self.address_var = tk.StringVar(value=DEFAULT_PROFILE["portal"]["host"])
        ttk.Entry(card, textvariable=self.address_var, width=30).grid(row=2, column=3, sticky="we", pady=4)
        card.columnconfigure(3, weight=1)

        # 第二行：说明 + 按钮
        ttk.Label(card, text="示例：10.0.0.1  或  portal.school.edu.cn  或  https://portal.school.edu.cn:8443",
                  style="CardMuted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 8))
        btn_row = tk.Frame(card, bg=C["card"])
        btn_row.grid(row=3, column=2, columnspan=2, sticky="e", pady=(4, 8))
        RoundedButton(btn_row, "自动探测类型", self._auto_detect, font_size=9).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, "一键生成配置", self._quick_generate,
                      fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"],
                      bold=True).pack(side="left")

        # 第三行：开机自启
        from .startup import startup_enabled
        self.autostart_var = tk.BooleanVar(value=startup_enabled())
        tk.Checkbutton(card, text="开机自启（登录 Windows 后自动连接校园网）",
                       variable=self.autostart_var, command=self._toggle_autostart,
                       bg=C["card"], fg=C["text"], activebackground=C["card"],
                       activeforeground=C["text"], selectcolor=C["card"],
                       font=(F["ui"], 10), highlightthickness=0).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _toggle_autostart(self) -> None:
        """开机自启开关：写入/删除注册表启动项。"""
        from .startup import set_startup, startup_enabled
        try:
            set_startup(self.autostart_var.get())
        except OSError as exc:
            messagebox.showerror("开机自启", f"设置失败：{exc}")
            self.autostart_var.set(startup_enabled())

    def _build_advanced_toggle(self) -> None:
        """高级设置折叠开关。"""
        bar = tk.Frame(self.root, bg=C["page"])
        bar.pack(fill="x", padx=18, pady=(10, 0))
        self.advanced_btn = RoundedButton(bar, "高级设置 ▸", self._toggle_advanced, font_size=9)
        self.advanced_btn.pack(side="left")

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_wrap.pack(fill="both", expand=True, padx=18, pady=(8, 8),
                                    before=self.footer_widget)
            self.advanced_btn._text = "高级设置 ▾"
        else:
            self.advanced_wrap.pack_forget()
            self.advanced_btn._text = "高级设置 ▸"
        self.advanced_btn._repaint()

    def _apply_template_and_address(self, template_name: str | None, address: str | None) -> None:
        """按模板 + 地址生成配置数据并回填表单（不弹窗）。"""
        template = PORTAL_TEMPLATES.get(template_name or "", {})
        if template is None:
            data = json.loads(json.dumps(DEFAULT_PROFILE, ensure_ascii=False))
        else:
            data = deep_merge(DEFAULT_PROFILE, json.loads(json.dumps(template, ensure_ascii=False)))
        if address and address.strip():
            host, port, scheme = _parse_address(address)
            if host:
                data["portal"]["host"] = host
                data["portal"]["port"] = port
                data["portal"]["scheme"] = scheme
        self._load(data)
        self.refresh_preview()

    def _quick_generate(self) -> None:
        """按所选模板 + 地址生成配置。"""
        self._apply_template_and_address(
            self.template_var.get() if self.template_var else None,
            self.address_var.get() if self.address_var else None)
        messagebox.showinfo("已生成", "配置已按所选模板生成。\n\n如需修改接口路径、字段名等细节，请点「高级设置」。\n确认无误后点底部「保存 JSON」。")

    def _auto_detect(self) -> None:
        """后台探测门户类型，识别后自动填充模板。"""
        address = self.address_var.get().strip() if self.address_var else ""
        if not address:
            messagebox.showwarning("提示", "请先填写门户地址")
            return
        import queue
        import threading
        from .detect import probe_portal
        q: "queue.Queue" = queue.Queue()

        def worker() -> None:
            try:
                q.put(probe_portal(address))
            except Exception as exc:  # 探测任何异常都不崩界面
                q.put({"recognized": False, "type": None, "template": None, "mode": "simple",
                       "message": f"探测失败：{exc}", "evidence": []})
        threading.Thread(target=worker, daemon=True).start()
        self._poll_detect(q)

    def _poll_detect(self, q) -> None:
        try:
            result = q.get_nowait()
        except Exception:
            self.root.after(200, lambda: self._poll_detect(q))
            return
        self._on_detect_result(result)

    def _on_detect_result(self, result: dict) -> None:
        template = result.get("template")
        if template and self.template_var is not None:
            self.template_var.set(template)
        self._apply_template_and_address(
            template if template else (self.template_var.get() if self.template_var else None),
            self.address_var.get() if self.address_var else None)
        evidence = result.get("evidence") or []
        detail = "\n".join(evidence[:6]) if evidence else ""
        messagebox.showinfo("探测结果", f"{result.get('message', '')}\n\n{detail}")

    def _build_notebook(self) -> None:
        self.advanced_wrap = ttk.Frame(self.root, style="Page.TFrame")
        # 默认不 pack，由「高级设置」开关控制

        self.notebook = ttk.Notebook(self.advanced_wrap)
        self.notebook.pack(fill="both", expand=True)

        self.tab_basic = self._make_tab("基本信息")
        self.tab_workflow = self._make_tab("工作流接口")
        self.tab_simple = self._make_tab("通用登录")
        self.tab_online = self._make_tab("在线与探测")
        self.tab_advanced = self._make_tab("高级")

        self._build_basic(self.tab_basic)
        self._build_workflow(self.tab_workflow)
        self._build_simple(self.tab_simple)
        self._build_online(self.tab_online)
        self._build_advanced(self.tab_advanced)

    def _make_tab(self, title: str) -> ttk.Frame:
        outer = ttk.Frame(self.notebook, style="Page.TFrame")
        self.notebook.add(outer, text=title)
        card = ttk.Frame(outer, style="Card.TFrame", padding=20)
        card.pack(fill="both", expand=True, padx=4, pady=4)
        card.columnconfigure(1, weight=1)
        return card

    def _section(self, parent: ttk.Frame, title: str, subtitle: str, row: int) -> int:
        ttk.Label(parent, text=title, style="Section.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1
        if subtitle:
            ttk.Label(parent, text=subtitle, style="CardMuted.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
            row += 1
        return row

    def _form(self, parent: ttk.Frame, keys: list[str], start_row: int) -> None:
        for i, key in enumerate(keys):
            r = start_row + i
            ttk.Label(parent, text=_FIELD_LABELS.get(key, key), style="Card.TLabel").grid(
                row=r, column=0, sticky="w", padx=(0, 14), pady=4)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="we", pady=4)

    def _make_text(self, parent: ttk.Frame, height: int, mono: bool = False) -> tk.Text:
        font = (F["mono"], 9) if mono else (F["ui"], 10)
        text = tk.Text(parent, height=height, bg=C["input"], fg=C["text"], font=font,
                       relief="solid", bd=1, wrap="none", insertbackground=C["text"],
                       highlightthickness=1, highlightbackground=C["border"],
                       highlightcolor=C["primary"], padx=8, pady=6)
        return text

    def _build_basic(self, parent: ttk.Frame) -> None:
        row = 0
        row = self._section(parent, "认证模式", "workflow=锐捷工作流；simple=通用直接登录", row)
        self.mode_var = tk.StringVar(value="workflow")
        ttk.Label(parent, text="认证模式", style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 14), pady=4)
        mode_box = ttk.Combobox(parent, textvariable=self.mode_var, values=MODES, state="readonly", width=18)
        mode_box.grid(row=row, column=1, sticky="w", pady=4)
        row += 1
        row = self._section(parent, "门户地址", "", row)
        self._form(parent, ["portal.host", "portal.port", "portal.scheme", "portal.entry_path"], row)

    def _build_workflow(self, parent: ttk.Frame) -> None:
        row = self._section(parent, "工作流模式", "锐捷 SAM+ 等：取节点 → 提交账号密码 → 选服务 → 复核在线", 0)
        self._form(parent, [
            "endpoints.get_current_node", "endpoints.update_session",
            "endpoints.service_selection", "endpoints.set_service",
            "endpoints.service_login", "endpoints.operator_login", "endpoints.query_terminal",
        ], row)
        row += 7
        row = self._section(parent, "字段名", "", row)
        self._form(parent, [
            "session.flow_key", "workflow.auth_type", "workflow.result_value",
            "workflow.credential_fields.username", "workflow.credential_fields.password",
            "workflow.credential_fields.auth_type",
            "workflow.service_fields.session_id", "workflow.service_fields.service",
        ], row)

    def _build_simple(self, parent: ttk.Frame) -> None:
        row = self._section(parent, "通用登录模式", "非锐捷门户的兜底：直接 POST 账号密码到登录接口", 0)
        self._form(parent, [
            "simple_login.login_path", "simple_login.method",
            "simple_login.username_field", "simple_login.password_field",
        ], row)
        row += 4
        ttk.Label(parent, text="额外固定字段（JSON，可选）", style="Card.TLabel").grid(
            row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        self.extra_fields_text = self._make_text(parent, 5, mono=True)
        self.extra_fields_text.grid(row=row, column=1, sticky="we", pady=4)

    def _build_online(self, parent: ttk.Frame) -> None:
        row = self._section(parent, "在线判定", "登录后如何判断已联网", 0)
        self._form(parent, [
            "endpoints.online_info", "online_check.path_field", "online_check.success_value",
        ], row)
        row += 3
        row = self._section(parent, "外网探测", "", row)
        self._form(parent, ["connectivity.probe_hosts", "connectivity.probe_port"], row)

    def _build_advanced(self, parent: ttk.Frame) -> None:
        row = self._section(parent, "会话", "sessionId 的获取方式", 0)
        self._form(parent, ["session.mode", "session.field_name", "session.redirect_probe_url"], row)
        row += 3
        ttk.Label(parent, text="错误文案（每行：类别=标记1,标记2）", style="Card.TLabel").grid(
            row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        self.error_markers_text = self._make_text(parent, 7, mono=True)
        self.error_markers_text.grid(row=row, column=1, sticky="we", pady=4)

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.root, style="Page.TFrame")
        # 固定到底部：无论上方内容多高，底部按钮区始终可见
        footer.pack(side="bottom", fill="x", padx=18, pady=(0, 14))
        self.footer_widget = footer

        preview_card = ttk.Frame(footer, style="Card.TFrame", padding=14)
        preview_card.pack(fill="x", pady=(0, 10))
        preview_card.columnconfigure(0, weight=1)

        head = ttk.Frame(preview_card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="we")
        ttk.Label(head, text="portal.json 预览", style="Section.TLabel").pack(side="left")
        ttk.Label(head, text="（实时生成）", style="CardMuted.TLabel").pack(side="left", padx=(8, 0))

        self.preview_text = self._make_text(preview_card, 9, mono=True)
        self.preview_text.grid(row=1, column=0, sticky="we", pady=(8, 0))
        scroll = ttk.Scrollbar(preview_card, orient="vertical", command=self.preview_text.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))
        self.preview_text.configure(yscrollcommand=scroll.set)

        buttons = tk.Frame(footer, bg=C["page"])
        buttons.pack(fill="x")
        RoundedButton(buttons, "加载 JSON", self.load_file, padx=16).pack(side="left", padx=(0, 6))
        RoundedButton(buttons, "刷新预览", self.refresh_preview, padx=16).pack(side="left", padx=6)
        RoundedButton(buttons, "恢复默认", self.reset, padx=16).pack(side="left", padx=6)
        RoundedButton(buttons, "保存 JSON", self.save_file, padx=16).pack(side="right", padx=(0, 6))
        RoundedButton(buttons, "开始自动登录", self._start_autologin,
                      fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"],
                      bold=True, padx=18).pack(side="right")

    # ---- 开始自动登录 ----

    def _start_autologin(self) -> None:
        """保存配置 → 确认账号密码 → 后台启动守护循环。"""
        # 1) 保存配置到工具目录
        data = self._collect()
        portal_file = _tool_root() / "portal.json"
        try:
            portal_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法写入 portal.json：{exc}")
            return

        # 2) 确认账号密码
        from .client import Credentials
        from .config import ConfigError, load_credentials, save_credentials
        try:
            credentials = load_credentials()
        except ConfigError:
            credentials = self._prompt_credentials()
            if credentials is None:
                return
            try:
                save_credentials(credentials)
            except OSError as exc:
                messagebox.showerror("保存失败", f"无法保存账号密码：{exc}")
                return

        # 3) 后台启动守护循环
        import threading
        threading.Thread(target=self._watch_worker, args=(portal_file, credentials), daemon=True).start()
        messagebox.showinfo("已开始", f"自动登录已在后台运行。\n\n配置已保存到：{portal_file}\n账号密码保存在：{_credentials_file_hint()}\n\n关闭本窗口不影响后台运行。")

    def _prompt_credentials(self):
        """弹窗输入账号密码与运营商，返回 Credentials 或 None。"""
        from .client import Credentials
        top = tk.Toplevel(self.root)
        top.title("输入校园网账号")
        top.geometry("380x310")
        top.configure(bg=C["card"])
        top.transient(self.root)
        top.grab_set()

        tk.Label(top, text="校园网账号", bg=C["card"], fg=C["text"], font=(F["ui"], 10)).pack(anchor="w", padx=22, pady=(18, 4))
        user = tk.Entry(top, width=34)
        user.pack(padx=22, pady=(0, 10))

        tk.Label(top, text="校园网密码", bg=C["card"], fg=C["text"], font=(F["ui"], 10)).pack(anchor="w", padx=22, pady=(0, 4))
        pwd = tk.Entry(top, width=34, show="*")
        pwd.pack(padx=22, pady=(0, 10))

        tk.Label(top, text="运营商（可输入或选择）", bg=C["card"], fg=C["text"], font=(F["ui"], 10)).pack(anchor="w", padx=22, pady=(0, 4))
        operators = ("中国移动", "中国联通", "中国电信", "校园网")
        service_var = tk.StringVar(value=operators[0])
        service = ttk.Combobox(top, textvariable=service_var, values=operators, width=32)
        service.pack(padx=22, pady=(0, 14))

        result: dict = {}

        def ok() -> None:
            result["username"] = user.get().strip()
            result["password"] = pwd.get()
            result["service"] = service_var.get().strip()
            top.destroy()

        def cancel() -> None:
            result.clear()
            top.destroy()

        row = tk.Frame(top, bg=C["card"])
        row.pack(fill="x", padx=22)
        RoundedButton(row, "取消", cancel).pack(side="left")
        RoundedButton(row, "确定", ok, fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"], bold=True).pack(side="right")

        self.root.wait_window(top)
        if not result or not result.get("username") or not result.get("password"):
            return None
        return Credentials(result["username"], result["password"], result.get("service", ""))

    def _watch_worker(self, portal_file, credentials) -> None:
        """后台守护线程：周期检测 + 登录 + 退避重试。"""
        import time
        from .client import Client
        from .network import enumerate_interfaces, pick_adapter
        from .portal import load_profile
        from .state import AuthState, RetryPolicy
        try:
            profile = load_profile(portal_file)
        except Exception:
            return
        adapter = pick_adapter(enumerate_interfaces())
        client = Client(profile, adapter=adapter)
        policy = RetryPolicy()
        while True:
            if not policy.should_try():
                time.sleep(1)
                continue
            try:
                result = client.authenticate(credentials)
            except Exception:
                result = None
            if result is not None:
                if result.state == AuthState.ONLINE:
                    policy.on_success()
                elif result.state == AuthState.ERROR:
                    break
                elif result.state == AuthState.PENDING:
                    policy.on_pending()
                else:
                    policy.on_failure()
            time.sleep(15)

    # ---- 数据装配 ----

    def _collect(self) -> dict:
        """从表单组装 portal.json 结构。"""
        data = json.loads(json.dumps(DEFAULT_PROFILE, ensure_ascii=False))
        for key, var in self.vars.items():
            value = var.get().strip()
            if key in ("portal.port", "connectivity.probe_port"):
                _set(data, key, int(value) if value.isdigit() else 0)
            else:
                _set(data, key, value)
        data["auth_mode"] = self.mode_var.get()
        hosts = [h.strip() for h in data["connectivity"]["probe_hosts"].split(",") if h.strip()] \
            if isinstance(data["connectivity"].get("probe_hosts"), str) else data["connectivity"]["probe_hosts"]
        data["connectivity"]["probe_hosts"] = hosts or ["www.baidu.com", "www.qq.com"]
        if self.extra_fields_text is not None:
            raw = self.extra_fields_text.get("1.0", "end").strip()
            data["simple_login"]["extra_fields"] = json.loads(raw) if raw else {}
        if self.error_markers_text is not None:
            markers = {}
            for line in self.error_markers_text.get("1.0", "end").splitlines():
                line = line.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    markers[key.strip()] = [v.strip() for v in value.split(",") if v.strip()]
            if markers:
                data["error_markers"] = markers
        return data

    def _load(self, data: dict) -> None:
        """把 dict 填进表单。"""
        self.mode_var.set(data.get("auth_mode", "workflow"))
        for key in self.vars:
            value = _get(data, key, "")
            if key == "connectivity.probe_hosts" and isinstance(value, list):
                value = ",".join(value)
            self.vars[key].set(str(value))
        if self.extra_fields_text is not None:
            self.extra_fields_text.delete("1.0", "end")
            self.extra_fields_text.insert("1.0", json.dumps(
                data.get("simple_login", {}).get("extra_fields", {}), ensure_ascii=False, indent=2))
        if self.error_markers_text is not None:
            self.error_markers_text.delete("1.0", "end")
            lines = [f"{k}={','.join(v)}" for k, v in data.get("error_markers", {}).items()]
            self.error_markers_text.insert("1.0", "\n".join(lines))

    # ---- 动作 ----

    def refresh_preview(self) -> None:
        data = self._collect()
        if self.preview_text is not None:
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))

    def save_file(self) -> None:
        target = self.profile_path or filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="portal.json")
        if not target:
            return
        data = self._collect()
        Path(target).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("已保存", f"已保存到 {target}")

    def load_file(self) -> None:
        source = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not source:
            return
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            messagebox.showerror("加载失败", str(exc))
            return
        self._load(deep_merge(DEFAULT_PROFILE, data))
        self.refresh_preview()

    def reset(self) -> None:
        self._load(DEFAULT_PROFILE)
        self.refresh_preview()


def _enable_dpi_awareness() -> None:
    """启用 DPI 感知，避免高分屏（系统缩放）下界面与字体模糊。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDpiAware()
        except Exception:
            pass


# 单实例互斥体句柄（保持持有，进程退出前不释放）
_MUTEX_HANDLE = None
_MUTEX_NAME = "CampusAuthConfigWindow"


def _acquire_single_instance() -> bool:
    """用命名互斥体实现单实例；返回 True 表示本次是首个实例。"""
    global _MUTEX_HANDLE
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return True  # 创建失败，假定可运行
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


def _activate_existing() -> None:
    """激活已打开的配置窗口（按标题查找并置前）。"""
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "校园网认证 · 门户配置")
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


def run_gui(profile_path: str | None = None) -> int:
    """打开配置窗口（单实例：已有窗口则激活它，不重复打开）。"""
    _enable_dpi_awareness()
    if not _acquire_single_instance():
        _activate_existing()
        return 0
    root = tk.Tk()
    ConfigWindow(root, profile_path)
    root.mainloop()
    return 0
