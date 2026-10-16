"""配置界面：用可视化表单填写门户画像，生成 portal.json。

纯标准库 tkinter 实现，可打包成独立 exe（不要求目标用户安装 Python）。
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .portal import DEFAULT_PROFILE, deep_merge
from .theme import C as _TC, MOTION as _MOTION, R as _TR, S as _TS

# 认证引擎模式
MODES = ("workflow", "cas", "simple")

# --------------------------------------------------------------------------
# 配色与字体（高级中性灰 × 明亮简约，Token 见 theme.py）
# 浅灰底 + 白卡片 + 1px 发丝描边 + 单一强调蓝 + 大留白；无阴影、无渐变。
# --------------------------------------------------------------------------
C = {
    "page": _TC["n25"],          # 窗口底色（比纯白略暗，让白卡片浮起来）
    "card": _TC["n0"],           # 卡片 / 输入框表面
    "primary": _TC["accent"],    # 唯一强调色
    "primary_hover": _TC["accent_hover"],
    "primary_active": _TC["accent_active"],
    "accent_subtle": _TC["accent_subtle"],
    "text": _TC["n700"],         # 正文默认色
    "title": _TC["n800"],        # 标题
    "muted": _TC["n500"],        # 辅助文字
    "faint": _TC["n400"],        # 占位符 / 禁用
    "border": _TC["n200"],       # 默认 1px 描边
    "border_strong": _TC["n300"],  # hover 描边
    "hairline": _TC["n150"],     # 分隔线
    "input": _TC["n0"],
    "tab": _TC["n25"],
    "subtle": _TC["n50"],        # 次级面板 / hover 底
    "pressed": _TC["n100"],      # 按下底 / 禁用底
    "danger": _TC["danger"],
    "success": _TC["success"],
    "warning": _TC["warning"],
    "white": _TC["white"],
}
F = {
    "ui": "Microsoft YaHei UI",
    "mono": "Cascadia Mono",
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


def _blend(c1: str, c2: str, t: float) -> str:
    """两个十六进制颜色之间插值（t: 0→c1, 1→c2）。"""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


class RoundedButton(tk.Canvas):
    """圆角按钮：Canvas 自绘，支持 hover 与点击（纯色 + 1px 描边，无渐变）。"""

    def __init__(self, parent, text, command=None, *, fill=C["card"], fg=C["text"],
                 border=C["border"], hover_fill=None, hover_border=C["primary"],
                 radius=8, bold=False, font_size=10, padx=24, height=32, gradient_to=None,
                 width=None):
        self._text = text
        self._command = command
        self._fill = fill
        self._fg = fg
        self._border = border
        self._hover_fill = hover_fill if hover_fill else (C["subtle"] if fill == C["card"] else fill)
        self._hover_border = hover_border
        self._radius = radius
        self._gradient_to = gradient_to  # 保留参数兼容旧调用，本方案不使用渐变
        self._font = (F["ui"], font_size, "bold" if bold else "normal")
        self._hovered = False

        import tkinter.font as tkfont
        font_obj = tkfont.Font(family=F["ui"], size=font_size, weight="bold" if bold else "normal")
        self._btn_w = width if width else (font_obj.measure(text) + padx * 2)
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
        # 纯色填充 + 1px 描边（本方案不使用渐变/阴影）
        _round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, self._radius,
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


class SlimScrollbar(tk.Canvas):
    """微信式细窄滚动条：圆角胶囊滑块，贴右边缘，无原生轨道/箭头。"""

    def __init__(self, parent, text_widget: tk.Text, *, width: int = 6,
                 color: str = None, bg: str = None):
        color = color or C["border_strong"]
        bg = bg or C["card"]
        super().__init__(parent, width=width, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._text = text_widget
        self._color = color
        self._width = width
        self._drag_anchor = None

        text_widget.bind("<MouseWheel>", self._on_wheel)
        text_widget.bind("<Button-4>", self._on_wheel)
        text_widget.bind("<Button-5>", self._on_wheel)
        text_widget.bind("<Configure>", lambda e: self._update())
        text_widget.bind("<KeyRelease>", lambda e: self._update())
        self.bind("<Configure>", lambda e: self._update())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_anchor", None))
        self._update()

    def set(self, *args) -> None:
        """兼容 Text 的 yscrollcommand 回调。"""
        self._update()

    def _update(self) -> None:
        self.delete("all")
        h = self.winfo_height()
        if h <= 1:
            return
        # 文本总高度（近似，含滚动内容）
        total = self._text.winfo_reqheight() or 1
        visible = self._text.winfo_height() or 1
        if total <= visible:
            return  # 内容不足一屏，不显示滑块
        thumb_h = max(24, int(h * visible / total))
        first = float(self._text.yview()[0])
        thumb_y = int(first * (h - thumb_h))
        w = self._width - 2
        r = w / 2  # 胶囊圆角
        _round_rect(self, 1, thumb_y, 1 + w, thumb_y + thumb_h, r,
                    fill=self._color, outline="")

    def _on_wheel(self, event) -> None:
        if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0:
            self._text.yview_scroll(-1, "units")
        elif getattr(event, "num", 0) == 5 or getattr(event, "delta", 0) < 0:
            self._text.yview_scroll(1, "units")
        self._update()

    def _on_press(self, event) -> None:
        self._drag_anchor = event.y

    def _on_drag(self, event) -> None:
        if self._drag_anchor is None:
            return
        delta = event.y - self._drag_anchor
        self._drag_anchor = event.y
        h = self.winfo_height() or 1
        total = self._text.winfo_reqheight() or 1
        visible = self._text.winfo_height() or 1
        if total > visible:
            # 按比例滚动
            units = int(delta * total / (h * 20)) + (1 if delta > 0 else -1 if delta < 0 else 0)
            if units:
                self._text.yview_scroll(units, "units")
                self._update()


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
    "华三 CAS SSO（加密）": {
        "auth_mode": "cas",
    },
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
TUTORIAL_TEXT = """这个工具帮你自动登录校园网：配置一次，即可后台守护、断线自动重连。

① 填写门户地址
   输入学校认证页地址（形如 10.0.0.1），
   或断网时点「自动获取」一键提取

② 选择门户类型
   点「自动探测类型」自动识别；
   也可手动选 锐捷 / 华三 CAS / 通用

③ 一键生成配置
   点「一键生成配置」，接口细节自动填好

④ 开始自动登录
   点底部「开始自动登录」，填写账号、密码、运营商，
   程序即在后台守护，断线自动重连

⑤ 开机自启（可选）
   勾选后，重启电脑自动以托盘运行

──────
免责声明：本工具仅供学习交流，用于自动完成本人账号在所在校园网的认证，请遵守所在学校网络使用规定；使用产生的一切后果由使用者自行承担。"""

# 首次使用标记：放在用户配置目录，看到教程后不再自动弹出
TUTORIAL_MARKER = Path.home() / ".campus-auth" / ".tutorial_shown"

# GitHub 主页地址
GITHUB_URL = "https://github.com/JianHeShui/campus-auth"
# GitHub 下的一行宣传语
STAR_HINT = "本软件完全免费，如果对你有所帮助，请为我点一个 star"


def _open_url(url: str) -> None:
    """用默认浏览器打开链接（一键跳转）。"""
    import webbrowser
    webbrowser.open(url)


def _bind_context_menu(widget) -> None:
    """给输入控件（Entry/Text）绑定右键复制/粘贴菜单。"""
    def _select_all():
        try:
            widget.tag_add("sel", "1.0", "end")  # Text
        except Exception:
            widget.select_range(0, "end")  # Entry
            widget.icursor("end")
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="剪切", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="复制", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="粘贴", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="全选", command=_select_all)
    widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))


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
        root.geometry("1120x720")
        root.minsize(1080, 700)
        root.configure(bg=C["page"])

        self._apply_theme()
        self._build_header()
        self._build_quick_start()
        self._build_advanced_toggle()
        self._build_notebook()
        self._build_footer()
        # 记忆上次输入：优先加载已保存的 portal.json，否则用默认画像
        saved = self._read_saved_profile()
        self._load(saved if saved else DEFAULT_PROFILE)
        self.refresh_preview()
        # 首次使用自动弹出教程
        if not TUTORIAL_MARKER.exists():
            self.root.after(400, self._show_tutorial)
        # 关闭窗口时自动保存配置，重启后记忆不变回默认
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        """关闭窗口前自动保存当前配置（记忆门户地址等）。"""
        try:
            data = self._collect()
            portal_file = _tool_root() / "portal.json"
            portal_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # 保存失败不阻塞关闭
        self.root.destroy()

    def _read_saved_profile(self) -> dict | None:
        """读取已保存的 portal.json（记忆上次填写的门户地址等），失败返回 None。"""
        import json as _json
        saved = _tool_root() / "portal.json"
        if not saved.exists():
            return None
        try:
            user = _json.loads(saved.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(user, dict):
            return None
        return deep_merge(DEFAULT_PROFILE, user)

    # ---- 主题 ----

    def _apply_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=(F["ui"], 10), background=C["page"], foreground=C["text"],
                        borderwidth=0, focuscolor=C["page"])  # focuscolor=底色即隐藏系统虚线环

        # 卡片式面板
        style.configure("Card.TFrame", background=C["card"])
        style.configure("Page.TFrame", background=C["page"])

        # 标签（靠字重与色阶分主次，不堆字号）
        style.configure("TLabel", background=C["page"], foreground=C["text"])
        style.configure("Card.TLabel", background=C["card"], foreground=C["text"])
        style.configure("Muted.TLabel", background=C["page"], foreground=C["muted"], font=(F["ui"], 9))
        style.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"], font=(F["ui"], 9))
        style.configure("Section.TLabel", background=C["card"], foreground=C["title"],
                        font=(F["ui"], 12, "bold"))

        # 输入框（高 32 = 行高 17 + padding 6×2 + border 1×2）
        style.configure("TEntry", fieldbackground=C["input"], foreground=C["text"],
                        bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                        padding=(10, 6), relief="flat", borderwidth=1)
        style.map("TEntry",
                  bordercolor=[("focus", C["primary"]), ("active", C["border_strong"])],
                  lightcolor=[("focus", C["primary"]), ("active", C["border_strong"])],
                  darkcolor=[("focus", C["primary"]), ("active", C["border_strong"])],
                  fieldbackground=[("disabled", C["subtle"])],
                  foreground=[("disabled", C["faint"])])

        # 下拉框（readonly 态必须单独 map，否则会出现灰色系统底）
        style.configure("TCombobox", fieldbackground=C["input"], foreground=C["text"],
                        background=C["white"], bordercolor=C["border"], lightcolor=C["border"],
                        darkcolor=C["border"], padding=(10, 6), relief="flat", borderwidth=1,
                        arrowcolor=C["muted"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", C["input"]), ("disabled", C["subtle"])],
                  foreground=[("disabled", C["faint"])],
                  bordercolor=[("focus", C["primary"]), ("active", C["border_strong"])],
                  lightcolor=[("focus", C["primary"]), ("active", C["border_strong"])],
                  darkcolor=[("focus", C["primary"]), ("active", C["border_strong"])],
                  arrowcolor=[("disabled", C["faint"])])

        # 次级按钮（lightcolor/darkcolor 必须与底同色，否则留 3D 斜角）
        style.configure("TButton", background=C["card"], foreground=C["text"],
                        bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                        padding=(12, 6), font=(F["ui"], 10), relief="flat", borderwidth=1)
        style.map("TButton",
                  background=[("active", C["subtle"]), ("pressed", C["pressed"])],
                  bordercolor=[("active", C["border_strong"]), ("pressed", C["border_strong"])],
                  lightcolor=[("active", C["subtle"]), ("pressed", C["pressed"])],
                  darkcolor=[("active", C["subtle"]), ("pressed", C["pressed"])],
                  foreground=[("disabled", C["faint"])])

        # 主按钮（唯一强调色）
        style.configure("Primary.TButton", background=C["primary"], foreground=C["white"],
                        bordercolor=C["primary"], lightcolor=C["primary"], darkcolor=C["primary"],
                        padding=(16, 7), font=(F["ui"], 10, "bold"), relief="flat", borderwidth=1)
        style.map("Primary.TButton",
                  background=[("active", C["primary_hover"]), ("pressed", C["primary_active"])],
                  bordercolor=[("active", C["primary_hover"]), ("pressed", C["primary_active"])],
                  lightcolor=[("active", C["primary_hover"]), ("pressed", C["primary_active"])],
                  darkcolor=[("active", C["primary_hover"]), ("pressed", C["primary_active"])])

        # 标签页（选中：浅强调底 + 主色文字）
        style.configure("TNotebook", background=C["page"], borderwidth=0, tabmargins=(0, 8, 0, 0))
        style.configure("TNotebook.Tab", background=C["tab"], foreground=C["muted"],
                        padding=(16, 8), font=(F["ui"], 10), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", C["accent_subtle"])],
                  foreground=[("selected", C["primary"])])

        # 复选框（白底）
        style.configure("Card.TCheckbutton", background=C["card"], foreground=C["text"])

        # 滚动条（去掉两端箭头 + 细窄浅灰滑块）
        style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Vertical.TScrollbar", background=C["border_strong"], troughcolor=C["page"],
                        bordercolor=C["page"], lightcolor=C["border_strong"],
                        darkcolor=C["border_strong"], relief="flat", borderwidth=0,
                        arrowsize=0, gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", C["faint"])])

    # ---- 结构 ----

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=C["card"])
        header.pack(fill="x")
        title_row = tk.Frame(header, bg=C["card"])
        title_row.pack(fill="x", padx=_TS["6"], pady=(_TS["5"], _TS["1"]))
        title_left = tk.Frame(title_row, bg=C["card"])
        title_left.pack(side="left")
        tk.Label(title_left, text="门户配置", bg=C["card"], fg=C["title"],
                 font=(F["ui"], 18, "bold")).pack(side="left")
        from . import __version__
        tk.Label(title_left, text=f"v{__version__}", bg=C["card"], fg=C["faint"],
                 font=(F["ui"], 9)).pack(side="left", padx=(_TS["2"], 0), pady=(_TS["3"], 0))
        RoundedButton(title_row, "使用教程", self._show_tutorial, font_size=9, padx=_TS["4"],
                      height=28).pack(side="right")
        tk.Label(header, text="填写你所在学校的门户信息，自动生成 portal.json",
                 bg=C["card"], fg=C["muted"], font=(F["ui"], 10)).pack(anchor="w", padx=_TS["6"], pady=(0, _TS["1"]))
        gh = tk.Label(header, text=f"GitHub: {GITHUB_URL}", bg=C["card"], fg=C["primary"],
                      font=(F["ui"], 9, "underline"), cursor="hand2")
        gh.pack(anchor="w", padx=_TS["6"], pady=(0, _TS["1"]))
        gh.bind("<Button-1>", lambda e: _open_url(GITHUB_URL))
        # star 文案（金色星标为装饰性品牌元素，不属于 UI 强调色）
        star_row = tk.Frame(header, bg=C["card"])
        star_row.pack(anchor="w", padx=_TS["6"], pady=(0, _TS["3"]))
        tk.Label(star_row, text="本软件完全免费，如果对你有所帮助，请为我点一个 ", bg=C["card"],
                 fg=C["muted"], font=(F["ui"], 9)).pack(side="left")
        tk.Label(star_row, text="star", bg=C["card"], fg="#F5A623",
                 font=(F["ui"], 9, "bold")).pack(side="left")
        # 底部分隔线
        tk.Frame(header, bg=C["hairline"], height=1).pack(fill="x")

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
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"], gradient_to=C["primary_hover"],
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
        _bind_context_menu(content)

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
        wrap.pack(fill="x", padx=_TS["6"], pady=(_TS["4"], 0))
        # 1px 发丝描边：外层描边色 Frame + 内层白底卡片留 1px
        border = tk.Frame(wrap, bg=C["border"])
        border.pack(fill="x")
        card = ttk.Frame(border, style="Card.TFrame", padding=_TS["6"])
        card.pack(fill="both", expand=True, padx=1, pady=1)

        ttk.Label(card, text="快速开始", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(card, text="只需两步：选择门户类型，填写门户网页地址",
                  style="CardMuted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 10))

        # 门户类型（独占一行）
        ttk.Label(card, text="门户类型", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
        self.template_var = tk.StringVar(value=list(PORTAL_TEMPLATES.keys())[0])
        ttk.Combobox(card, textvariable=self.template_var, values=list(PORTAL_TEMPLATES.keys()),
                     state="readonly", width=26).grid(row=2, column=1, sticky="w", pady=4)

        # 门户地址（独占一行）
        ttk.Label(card, text="门户地址", style="Card.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=4)
        self.address_var = tk.StringVar(value=DEFAULT_PROFILE["portal"]["host"])
        address_entry = ttk.Entry(card, textvariable=self.address_var, width=34)
        address_entry.grid(row=3, column=1, columnspan=2, sticky="we", pady=4)
        _bind_context_menu(address_entry)
        card.columnconfigure(1, weight=1)
        RoundedButton(card, "自动获取", self._auto_fill_address, font_size=9, width=88).grid(
            row=3, column=3, padx=(8, 0), pady=4)

        # 按钮行（独占一行）
        btn_row = tk.Frame(card, bg=C["card"])
        btn_row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 2))
        RoundedButton(btn_row, "自动探测类型", self._auto_detect, font_size=9, width=120).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, "一键生成配置", self._quick_generate,
                      fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"], gradient_to=C["primary_hover"],
                      bold=True, width=150).pack(side="left")

        # 开机自启
        from .startup import startup_enabled
        self.autostart_var = tk.BooleanVar(value=startup_enabled())
        tk.Checkbutton(card, text="开机自启（登录 Windows 后自动连接）",
                       variable=self.autostart_var, command=self._toggle_autostart,
                       bg=C["card"], fg=C["text"], activebackground=C["card"],
                       activeforeground=C["text"], selectcolor=C["card"],
                       font=(F["ui"], 10), highlightthickness=0).grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))

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

    def _auto_fill_address(self) -> None:
        """断网时自动从网关劫持重定向中提取门户地址并填入。"""
        from .network import detect_portal_host
        host = detect_portal_host()
        if host:
            self.address_var.set(host)
            messagebox.showinfo("已获取", f"已自动获取门户地址：{host}")
        else:
            messagebox.showinfo(
                "未获取到",
                "未能自动获取门户地址。\n\n"
                "请确保当前处于「未联网」状态（断网）后再点一次：\n"
                "断网时访问外网会被网关重定向到认证页，据此提取地址。\n"
                "若已联网，请先断网，或手动填写地址。")

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
        border = tk.Frame(outer, bg=C["border"])
        border.pack(fill="both", expand=True, padx=_TS["1"], pady=_TS["1"])
        card = ttk.Frame(border, style="Card.TFrame", padding=_TS["6"])
        card.pack(fill="both", expand=True, padx=1, pady=1)
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
            entry = ttk.Entry(parent, textvariable=var)
            entry.grid(row=r, column=1, sticky="we", pady=4)
            _bind_context_menu(entry)

    def _make_text(self, parent: ttk.Frame, height: int, mono: bool = False) -> tk.Text:
        font = (F["mono"], 9) if mono else (F["ui"], 10)
        text = tk.Text(parent, height=height, bg=C["input"], fg=C["text"], font=font,
                       relief="solid", bd=1, wrap="none", insertbackground=C["text"],
                       highlightthickness=1, highlightbackground=C["border"],
                       highlightcolor=C["primary"], padx=8, pady=6)
        _bind_context_menu(text)
        return text

    def _build_basic(self, parent: ttk.Frame) -> None:
        row = 0
        row = self._section(parent, "认证模式", "workflow=锐捷工作流；cas=华三CAS加密；simple=通用直接登录", row)
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
        # 底部按钮区：只含提示 + 按钮，固定底部，按钮固定大小
        footer = ttk.Frame(self.root, style="Page.TFrame")
        footer.pack(side="bottom", fill="x", padx=18, pady=(0, 14))
        self.footer_widget = footer

        tk.Label(footer, text="提示：「开始自动登录」会自动保存配置，无需手动点「保存 JSON」。",
                 bg=C["page"], fg=C["muted"], font=(F["ui"], 9)).pack(anchor="w", pady=(0, 10))

        buttons = tk.Frame(footer, bg=C["page"])
        buttons.pack(fill="x")

        # 第一行：次要操作（固定宽度按钮）
        row1 = tk.Frame(buttons, bg=C["page"])
        row1.pack(fill="x", pady=(0, 8))
        b1 = RoundedButton(row1, "加载 JSON", self.load_file, width=130)
        b2 = RoundedButton(row1, "恢复默认", self.reset, width=130)
        b3 = RoundedButton(row1, "保存 JSON", self.save_file, width=130)
        for i, b in enumerate([b1, b2, b3]):
            b.grid(row=0, column=i, padx=(0, 8), sticky="w")
            row1.grid_columnconfigure(i, minsize=b._btn_w)

        # 第二行：主要操作（固定宽度，靠右）
        row2 = tk.Frame(buttons, bg=C["page"])
        row2.pack(fill="x")
        row2.grid_columnconfigure(0, weight=1)  # 左侧留白伸缩
        b4 = RoundedButton(row2, "重新输入账号密码", self._reenter_credentials, width=170)
        b5 = RoundedButton(row2, "开始自动登录", self._start_autologin,
                           fill=C["primary"], fg=C["white"], border=C["primary"],
                           hover_fill=C["primary_hover"], hover_border=C["primary_hover"], gradient_to=C["primary_hover"],
                           bold=True, width=170)
        b4.grid(row=0, column=1, padx=(0, 8), sticky="e")
        b5.grid(row=0, column=2, sticky="e")
        row2.grid_columnconfigure(1, minsize=b4._btn_w)
        row2.grid_columnconfigure(2, minsize=b5._btn_w)

    # ---- 开始自动登录 ----

    def _reenter_credentials(self) -> None:
        """重新输入账号密码并保存（用于密码错误后更正）。"""
        from .config import save_credentials
        credentials = self._prompt_credentials()
        if credentials is None:
            return
        try:
            save_credentials(credentials)
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法保存账号密码：{exc}")
            return
        messagebox.showinfo("已更新", "账号密码已更新，下次自动登录将使用新密码。")

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
        _bind_context_menu(user)

        tk.Label(top, text="校园网密码", bg=C["card"], fg=C["text"], font=(F["ui"], 10)).pack(anchor="w", padx=22, pady=(0, 4))
        pwd = tk.Entry(top, width=34, show="*")
        pwd.pack(padx=22, pady=(0, 10))
        _bind_context_menu(pwd)

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
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"], gradient_to=C["primary_hover"], bold=True).pack(side="right")

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
        except Exception as exc:
            self._report_error(f"配置文件加载失败：{exc}")
            return
        adapter = pick_adapter(enumerate_interfaces())
        client = Client(profile, adapter=adapter)
        policy = RetryPolicy()
        error_shown = False  # 避免同一错误重复弹窗
        while True:
            if not policy.should_try():
                time.sleep(1)
                continue
            # 每次认证前重新枚举网卡（IP 可能因断网重连变化，避免源地址绑定失败）
            fresh_adapter = pick_adapter(enumerate_interfaces())
            if fresh_adapter is not None:
                client.adapter = fresh_adapter
            try:
                result = client.authenticate(credentials)
            except Exception as exc:
                result = None
                if not error_shown:
                    error_shown = True
                    self._report_error(f"认证过程发生错误：{exc}")
            if result is not None:
                if result.state == AuthState.ONLINE:
                    policy.on_success()
                    error_shown = False  # 成功后重置，允许下次再报告
                elif result.state == AuthState.ERROR:
                    msg = result.message or ""
                    if "密码" in msg or "账号" in msg or "用户不存在" in msg:
                        # 账号密码错误：提示用户用「重新输入账号密码」更正
                        self._report_error(f"账号或密码错误。\n\n{msg}\n\n请点【重新输入账号密码】更正后，再点【开始自动登录】。")
                    else:
                        self._report_error(f"认证失败：{msg}")
                    break
                elif result.state == AuthState.PENDING:
                    policy.on_pending()
                else:
                    policy.on_failure()
            time.sleep(15)

    def _report_error(self, msg: str) -> None:
        """在主线程弹出错误报告对话框。"""
        def _show():
            messagebox.showerror(
                "认证错误报告",
                f"{msg}\n\n详细信息请查看：\nC:\\Users\\{Path.home().name}\\.campus-auth\\auth-debug.log")
        try:
            self.root.after(0, _show)
        except Exception:
            pass

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
        # 门户地址以快速开始区的输入框为准（保证输入框与预览一致）
        if self.address_var is not None:
            addr = self.address_var.get().strip()
            if addr:
                host, port, scheme = _parse_address(addr)
                if host:
                    data["portal"]["host"] = host
                    data["portal"]["port"] = port
                    data["portal"]["scheme"] = scheme
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
        auth = data.get("auth_mode", "workflow")
        self.mode_var.set(auth)
        # 同步门户地址输入框（快速开始区独立于 vars，否则会与预览不一致）
        if self.address_var is not None:
            self.address_var.set(str(data.get("portal", {}).get("host", "")))
        # 根据 auth_mode 同步模板下拉框，避免后续「一键生成」把模式覆盖回默认
        if self.template_var is not None:
            if auth == "cas":
                self.template_var.set("华三 CAS SSO（加密）")
            elif auth == "simple":
                self.template_var.set("通用（简单登录）")
            else:
                self.template_var.set("锐捷 SAM+（工作流）")
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


def _window_icon_path() -> Path:
    """配置窗口图标（tray.ico）：frozen 时在 _MEIPASS，源码时在项目根。"""
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "tray.ico"
    return Path(__file__).resolve().parent.parent / "tray.ico"


def run_gui(profile_path: str | None = None) -> int:
    """打开配置窗口（单实例：已有窗口则激活它，不重复打开）。"""
    _enable_dpi_awareness()
    if not _acquire_single_instance():
        _activate_existing()
        return 0
    root = tk.Tk()
    icon = _window_icon_path()
    if icon.exists():
        try:
            root.iconbitmap(str(icon))
        except Exception:
            pass  # 图标设置失败不影响主流程
    ConfigWindow(root, profile_path)
    root.mainloop()
    return 0
