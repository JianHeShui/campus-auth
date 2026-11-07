"""配置界面：用可视化表单填写门户画像，生成 portal.json。

纯标准库 tkinter 实现，可打包成独立 exe（不要求目标用户安装 Python）。
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import CONFIG_WINDOW_TITLE, __version__
from .portal import DEFAULT_PROFILE, deep_merge
from .theme import C as _TC

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
    "rail": "#17263A",
    "rail_muted": "#B7C8DE",
    "rail_line": "#415573",
    "rail_active": "#A9CBFF",
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


class RoundedButton(tk.Canvas):
    """圆角按钮：Canvas 自绘，支持 hover 与点击（纯色 + 1px 描边，无渐变）。"""

    def __init__(self, parent, text, command=None, *, fill=C["card"], fg=C["text"],
                 border=C["border_strong"], hover_fill=None, hover_border=C["border_strong"],
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
        self._pressed = False

        import tkinter.font as tkfont
        font_obj = tkfont.Font(family=F["ui"], size=font_size, weight="bold" if bold else "normal")
        self._btn_w = max(width or 0, font_obj.measure(text) + padx * 2)
        self._btn_h = max(height, font_obj.metrics("linespace") + 10)
        surface = (ttk.Style().lookup(parent.cget("style") or "TFrame", "background")
                   if isinstance(parent, ttk.Widget) else parent.cget("background"))
        super().__init__(parent, width=self._btn_w, height=self._btn_h, bg=surface or C["page"],
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=True)

        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda e: self._invoke())
        self.bind("<space>", lambda e: self._invoke())
        self.bind("<FocusIn>", self._on_configure)
        self.bind("<FocusOut>", self._on_configure)
        self._repaint()

    def _fill_now(self):
        if self._pressed and self._hovered:
            return C["primary_active"] if self._fill == C["primary"] else C["pressed"]
        return self._hover_fill if self._hovered else self._fill

    def _border_now(self):
        if self.focus_get() == self:
            return C["rail_active"] if self._fill == C["primary"] else C["primary"]
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
        _round_rect(self, 1.5, 1.5, w - 1.5, h - 1.5, self._radius,
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

    def _on_press(self, event) -> None:
        self._pressed = True
        self.focus_set()
        self._on_enter()

    def _on_release(self, event=None) -> None:
        self._pressed = False
        self._hovered = False
        self._repaint()
        if event is None or (0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()):
            self._invoke()

    def _invoke(self) -> None:
        if self._command:
            self._command()


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
    "watch.recheck_interval": "在线复核间隔（秒，5-3600）",
    "watch.max_interval": "失败重试上限（秒，5-3600）",
}

# 以「秒」为单位的自动保护间隔字段：走 _parse_seconds（去空格 + 整数 + 5-3600 校验）
_SECONDS_FIELDS = ("watch.recheck_interval", "watch.max_interval")


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


def _format_address(data: dict) -> str:
    """把画像里的 portal.host/port/scheme 还原成地址框文本（_apply_address 的逆运算）。

    非默认端口才显示 :port，保证「打开 → 保存」往返不丢协议与端口。
    """
    portal = data.get("portal") if isinstance(data, dict) else None
    if not isinstance(portal, dict):
        return ""
    host = str(portal.get("host", "") or "").strip()
    if not host:
        return ""
    scheme = str(portal.get("scheme", "http") or "http").strip().lower()
    if scheme not in ("http", "https"):
        scheme = "http"
    try:
        port = int(portal.get("port", 0))
    except (TypeError, ValueError):
        port = 0
    default_port = 443 if scheme == "https" else 80
    if port in (0, default_port):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _apply_address(data: dict, address: str) -> None:
    """把地址框文本解析并写入 portal.host/port/scheme（地址框是唯一数据源）。

    地址为空或无法解析时抛 ValueError（中文提示），避免把旧值静默写回。
    """
    addr = (address or "").strip()
    if not addr:
        raise ValueError("门户地址不能为空，请填写形如 10.0.0.1 或 http://host:8080 的地址")
    try:
        host, port, scheme = _parse_address(addr)
    except ValueError as exc:
        raise ValueError(f"门户地址无法解析：{exc}") from exc
    if not host:
        raise ValueError("门户地址无法解析，请填写形如 10.0.0.1 或 http://host:8080 的地址")
    portal = data.setdefault("portal", {})
    portal["host"] = host
    portal["port"] = port
    portal["scheme"] = scheme


def _parse_seconds(value: str, label: str) -> int:
    """秒数输入校验：必须是 5-3600 的整数秒（自动保护间隔类配置）。

    与 cli.py 的 _INTERVAL_MIN/_INTERVAL_MAX 保持一致，避免 GUI 允许的值
    被命令行侧再次钳制、导致用户看到的配置与实际运行行为不一致。
    """
    text = (value or "").strip()
    try:
        seconds = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是整数秒（当前：{value!r}）") from exc
    if not 5 <= seconds <= 3600:
        raise ValueError(f"{label} 超出 5-3600 秒范围（当前：{seconds}）")
    return seconds


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

先分清三种运行方式：
· 自动保护（本界面按钮）：后台持续运行、断线自动重连，
  直到你在托盘菜单点「停止自动保护」——不是只登录一次。
· 单次登录：只认证一次、不常驻（命令行 campus-auth login 提供）。
· 开机自启：勾选后开机自动以托盘运行并开启自动保护，一直常驻。

① 填写门户地址
   输入学校认证页地址（形如 10.0.0.1），
   或断网时点「自动获取」一键提取

② 选择门户类型
   点「自动探测类型」自动识别；
   也可手动选 锐捷 / 华三 CAS / 通用

③ 应用模板
   点「应用模板」填好所选类型的接口参数

④ 开启后台守护
   点底部「开启后台守护」，按提示填写账号、密码、运营商。
   程序会在后台持续守护、断线自动重连（关闭窗口不影响），
   不是单次登录；再次点击会自动重启保护。

⑤ 开机自启（可选）
   勾选后，开机登录 Windows 会自动以托盘运行并开启自动保护，
   之后一直常驻；取消勾选则仅本次运行有效。

──────
免责声明：本工具仅供学习交流，用于自动完成本人账号在所在校园网的认证，请遵守所在学校网络使用规定；使用产生的一切后果由使用者自行承担。"""

# 首次使用标记：放在用户配置目录，看到教程后不再自动弹出
TUTORIAL_MARKER = Path.home() / ".campus-auth" / ".tutorial_shown"

# GitHub 主页地址
GITHUB_URL = "https://github.com/JianHeShui/campus-auth"


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


def _autostart_hint(enabled: bool) -> str:
    """开机自启状态的中文说明（配置界面启动成功弹窗使用）。

    明确区分「开机后一直运行」与「仅本次运行」，避免用户误以为已常驻。
    """
    if enabled:
        return "已开启（开机后自动运行并持续保护）"
    return "未开启（仅本次运行，电脑重启后需重新打开）"


class ConfigWindow:
    """门户画像配置窗口。"""

    def __init__(self, root: tk.Tk, profile_path: str | None = None):
        self.root = root
        self.profile_path = Path(profile_path) if profile_path else None
        self.vars: dict[str, tk.StringVar] = {}
        self.field_entries: dict[str, ttk.Entry] = {}
        self.extra_fields_text: tk.Text | None = None
        self.error_markers_text: tk.Text | None = None
        self.template_var: tk.StringVar | None = None
        self.address_var: tk.StringVar | None = None
        self.advanced_visible = False
        self.detect_btn = None
        self.fetch_btn = None
        self._account_ready = False
        self._status_job = None

        root.title(CONFIG_WINDOW_TITLE)
        # 按屏幕可用区自适应：小屏（1366×768 等）不至于超出屏幕 / 按钮被裁
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(1180, screen_w - 80)
        scale = root.winfo_fpixels("1i") / 96
        height = min(780, max(660, round(520 * scale)), screen_h - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(min(960, width), min(620, height))
        root.configure(bg=C["page"])

        self._apply_theme()
        self.content = tk.Frame(root, bg=C["page"])
        self.content.pack(fill="both", expand=True)
        self._build_header()
        self._build_connection_strip()
        self._build_quick_start()
        self._build_advanced_toggle()
        self._build_notebook()
        self._build_footer()
        self.quick_wrap.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        # 记忆上次输入：优先加载已保存的 portal.json，否则用默认画像
        saved = self._read_saved_profile()
        self._load(saved if saved is not None else DEFAULT_PROFILE)
        self._portal_saved = saved is not None
        self._remember_form()
        self._poll_connection()
        root.bind("<Destroy>", self._cancel_status_poll, add="+")
        root.bind("<Configure>", self._fit_connection_header, add="+")
        self.refresh_preview()
        # 首次使用自动弹出教程
        if not TUTORIAL_MARKER.exists():
            self.root.after(400, self._show_tutorial)
        # 关闭窗口时自动保存配置，重启后记忆不变回默认
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        """关闭窗口前自动保存当前配置；配置非法时提示但不阻塞关闭。"""
        data, error = self._collect_safe()
        if error:
            messagebox.showwarning(
                "配置未保存",
                f"关闭前自动保存失败：\n\n{error}\n\n窗口仍会关闭，但本次修改可能未写入 portal.json。")
            self.root.destroy()
            return
        try:
            portal_file = _tool_root() / "portal.json"
            portal_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showwarning("配置未保存", f"无法写入 portal.json：{exc}")
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
                        padding=(14, 8), font=(F["ui"], 10), borderwidth=0,
                        bordercolor=C["page"], lightcolor=C["page"], darkcolor=C["page"])
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
                        arrowsize=10, gripcount=0)
        style.map("Vertical.TScrollbar",
                  background=[("disabled", C["page"]), ("active", C["faint"])],
                  lightcolor=[("disabled", C["page"])], darkcolor=[("disabled", C["page"])])

    # ---- 结构 ----

    def _build_header(self) -> None:
        header = tk.Frame(self.content, bg=C["card"])
        header.pack(fill="x")
        bar = tk.Frame(header, bg=C["card"])
        bar.pack(fill="x", padx=24, pady=8)
        mark = tk.Canvas(bar, width=30, height=30, bg=C["card"], highlightthickness=0)
        mark.pack(side="left", padx=(0, 9))
        _round_rect(mark, 1, 1, 29, 29, 8, fill=C["primary"], outline="")
        mark.create_line(8, 20, 15, 9, 22, 20, fill=C["white"], width=1.6)
        for x, y in ((8, 20), (15, 9), (22, 20)):
            mark.create_oval(x - 1.8, y - 1.8, x + 1.8, y + 1.8, fill=C["white"], outline="")
        tk.Label(bar, text="Campus Auth", bg=C["card"], fg=C["title"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        tk.Label(bar, text=f"v{__version__}", bg=C["subtle"], fg=C["muted"],
                 font=("Segoe UI", 9), padx=7, pady=2).pack(side="left", padx=10)
        tools = ttk.Menubutton(bar, text="工具", direction="below", takefocus=True, width=4)
        tools.pack(side="right")
        menu = tk.Menu(tools, tearoff=False)
        menu.add_command(label="导入配置…", command=self.load_file)
        menu.add_command(label="导出配置…", command=self.save_file)
        menu.add_command(label="恢复默认", command=self.reset)
        menu.add_separator()
        menu.add_command(label="GitHub", command=lambda: _open_url(GITHUB_URL))
        tools.configure(menu=menu)
        RoundedButton(bar, "使用教程", self._show_tutorial, font_size=9,
                      padx=12, height=30).pack(side="right", padx=(0, 8))
        tk.Frame(header, bg=C["hairline"], height=1).pack(fill="x")

    def _build_connection_strip(self) -> None:
        section = tk.Frame(self.content, bg=C["page"])
        section.pack(fill="x", padx=24, pady=(12, 14))
        self.connection_title = tk.Label(section, text="校园网认证设置", bg=C["page"], fg=C["title"],
                                         font=(F["ui"], 21, "bold"))
        self.connection_title.pack(anchor="w", pady=(0, 9))
        self.connection_strip = strip = tk.Frame(section, bg=C["rail"], padx=16, pady=17)
        strip.pack(fill="x")
        self.portal_status = tk.StringVar()
        self.account_status = tk.StringVar()
        self.guard_status = tk.StringVar()
        for index, (title, status) in enumerate((
            ("门户配置", self.portal_status),
            ("校园网账号", self.account_status),
            ("后台守护", self.guard_status),
        )):
            column = index * 2
            strip.columnconfigure(column, weight=1, uniform="connection")
            node = tk.Frame(strip, bg=C["rail"])
            node.grid(row=0, column=column)
            icon = tk.Canvas(node, width=34, height=34, bg=C["rail"], highlightthickness=0)
            icon.pack(side="left", padx=(0, 9))
            ring = icon.create_oval(2, 2, 32, 32, outline=C["rail_line"], width=1.5)
            ink = C["rail_muted"]
            if index == 0:
                icon.create_arc(8, 12, 26, 29, start=42, extent=96, style="arc", outline=ink, width=1.5)
                icon.create_arc(12, 16, 22, 26, start=40, extent=100, style="arc", outline=ink, width=1.5)
                icon.create_oval(16, 21, 18, 23, fill=ink, outline="")
            elif index == 1:
                icon.create_oval(14, 9, 20, 15, outline=ink, width=1.5)
                icon.create_arc(10, 17, 24, 29, start=5, extent=170, style="arc", outline=ink, width=1.5)
            else:
                icon.create_rectangle(10, 10, 24, 20, outline=ink, width=1.5)
                icon.create_line(17, 20, 17, 24, fill=ink, width=1.5)
                icon.create_line(13, 24, 21, 24, fill=ink, width=1.5)
                self.guard_ring = icon, ring
            copy = tk.Frame(node, bg=C["rail"])
            copy.pack(side="left")
            tk.Label(copy, text=title, bg=C["rail"], fg=C["white"],
                     font=(F["ui"], 10, "bold"), padx=0).pack(anchor="w")
            label = tk.Label(copy, textvariable=status, bg=C["rail"], fg=ink, font=(F["ui"], 9), padx=0)
            label.pack(anchor="w", pady=(2, 0))
            if index == 2:
                self.guard_label = label
            if index < 2:
                tk.Frame(strip, bg=C["rail_line"], width=38, height=1).grid(row=0, column=column + 1)

    def _fit_connection_header(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        scale = self.root.winfo_fpixels("1i") / 96
        compact = self.advanced_visible or self.root.winfo_height() < 440 * scale
        if compact == getattr(self, "_compact_header", None):
            return
        self._compact_header = compact
        self.connection_strip.configure(pady=7 if compact else 17)
        if compact:
            self.connection_title.pack_forget()
            self.quick_intro.pack_forget()
        else:
            self.connection_title.pack(anchor="w", pady=(0, 9), before=self.connection_strip)
            self.quick_intro.pack(anchor="w", pady=(4, 18), before=self.address_label)

    def _remember_form(self) -> None:
        self._clean_form = self._collect_safe()[0], self.template_var.get()

    def _refresh_connection(self) -> None:
        from .daemon import is_running

        running = is_running()
        current, _ = self._collect_safe()
        dirty = (current, self.template_var.get()) != self._clean_form
        self.portal_status.set("有未保存修改" if dirty else ("配置已保存" if self._portal_saved else "待保存配置"))
        self.account_status.set("已配置" if self._account_ready else "按需提示填写")
        self.guard_status.set("进程运行中" if running else "未开启")
        self.footer_hint.set("重启时保存并应用配置。" if running else "保存门户配置，缺少账号时提示填写。")
        highlight = C["rail_active"] if running else C["rail_muted"]
        self.guard_label.configure(fg=highlight)
        icon, ring = self.guard_ring
        icon.itemconfigure(ring, outline=highlight if running else C["rail_line"])
        caption = "重启后台守护" if running else "开启后台守护"
        if self.start_btn._text != caption:
            self.start_btn._text = caption
            self.start_btn._repaint()

    def _poll_connection(self) -> None:
        self._refresh_connection()
        self._status_job = self.root.after(1500, self._poll_connection)

    def _cancel_status_poll(self, event) -> None:
        if event.widget is self.root and self._status_job is not None:
            self.root.after_cancel(self._status_job)

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

        content = tk.Text(top, height=14, bg=C["card"], fg=C["text"], font=(F["ui"], 10),
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
        self.quick_wrap = ttk.Frame(self.content, style="Page.TFrame")
        self.quick_canvas, work = self._scroll_card(self.quick_wrap, padding=24, surface=C["page"])
        self.quick_portal = portal = ttk.Frame(work, style="Card.TFrame")
        self.quick_preferences = preferences = ttk.Frame(work, style="Card.TFrame")
        self.quick_divider = tk.Frame(work, bg=C["hairline"], width=1, height=1)
        work.bind("<Configure>", self._layout_quick_start, add="+")

        ttk.Label(portal, text="门户设置", style="Section.TLabel").pack(anchor="w")
        self.quick_intro = ttk.Label(portal, text="填写学校的登录地址，再选择认证类型",
                                     style="CardMuted.TLabel", wraplength=520)
        self.quick_intro.pack(anchor="w", pady=(4, 18))

        self.address_label = ttk.Label(portal, text="门户地址", style="Card.TLabel")
        self.address_label.pack(anchor="w", pady=(6, 0))
        address_row = ttk.Frame(portal, style="Card.TFrame")
        address_row.pack(fill="x", pady=(6, 16))
        self.address_var = tk.StringVar(value=_format_address(DEFAULT_PROFILE))
        self.address_entry = ttk.Entry(address_row, textvariable=self.address_var, width=12, font=(F["ui"], 10))
        self.address_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        _bind_context_menu(self.address_entry)
        self.fetch_btn = RoundedButton(address_row, "自动获取", self._auto_fill_address,
                                       font_size=9, padx=13, height=36)
        self.fetch_btn.pack(side="right", fill="y")

        ttk.Label(portal, text="认证模板", style="Card.TLabel").pack(anchor="w")
        type_row = ttk.Frame(portal, style="Card.TFrame")
        type_row.pack(fill="x", pady=(6, 18))
        self.template_var = tk.StringVar(value=next(iter(PORTAL_TEMPLATES)))
        ttk.Combobox(type_row, textvariable=self.template_var, values=list(PORTAL_TEMPLATES),
                     state="readonly", width=15, font=(F["ui"], 10)).pack(
                         side="left", fill="x", expand=True, padx=(0, 8))
        self.detect_btn = RoundedButton(type_row, "自动探测类型", self._auto_detect,
                                        font_size=9, padx=13, height=36)
        self.detect_btn.pack(side="left", fill="y", padx=(0, 8))
        self.apply_template_btn = RoundedButton(
            type_row, "应用模板", self._quick_generate, fill=C["accent_subtle"], fg=C["primary"],
            border=_TC["accent_border"], hover_fill=C["subtle"], font_size=9, padx=13, height=36,
        )
        self.apply_template_btn.pack(side="left", fill="y")
        ttk.Label(portal, text="选择新模板后，先应用，再开启后台守护。",
                  style="CardMuted.TLabel", wraplength=520).pack(anchor="w")

        ttk.Label(preferences, text="运行偏好", style="Section.TLabel").pack(anchor="w")
        ttk.Label(preferences, text="管理本机启动方式与校园网账号。",
                  style="CardMuted.TLabel", wraplength=230).pack(anchor="w", pady=(3, 12))

        from .startup import startup_enabled
        self.autostart_var = tk.BooleanVar(value=startup_enabled())
        ttk.Checkbutton(preferences, text="开机自启", variable=self.autostart_var,
                        command=self._toggle_autostart, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(preferences, text="随 Windows 启动并开启后台守护。",
                  style="CardMuted.TLabel", wraplength=230).pack(anchor="w", pady=(4, 12))
        RoundedButton(preferences, "账号设置", self._reenter_credentials, font_size=9,
                      padx=13, height=34).pack(anchor="w")

    def _layout_quick_start(self, event) -> None:
        work = event.widget
        # 按实际 DPI 缩放断点，小窗口使用单列，字段通过同一个滚动区访问。
        wide = event.width >= max(930, round(660 * self.root.winfo_fpixels("1i") / 96))
        if wide == getattr(self, "_quick_wide", None):
            return
        self._quick_wide = wide
        work.columnconfigure(0, weight=2 if wide else 1, uniform="setup" if wide else "")
        work.columnconfigure(2, weight=1 if wide else 0, uniform="setup" if wide else "")
        self.quick_portal.grid(row=0, column=0, sticky="nsew")
        if wide:
            self.quick_divider.grid(row=0, column=1, sticky="ns", padx=22, pady=0)
            self.quick_preferences.grid(row=0, column=2, sticky="nsew")
        else:
            self.quick_divider.grid(row=1, column=0, sticky="ew", padx=0, pady=16)
            self.quick_preferences.grid(row=2, column=0, sticky="nsew")

    def _toggle_autostart(self) -> None:
        """开机自启开关：写入/删除注册表启动项。"""
        from .startup import set_startup, startup_enabled
        try:
            set_startup(self.autostart_var.get())
        except OSError as exc:
            messagebox.showerror("开机自启", f"设置失败：{exc}")
            self.autostart_var.set(startup_enabled())

    def _build_advanced_toggle(self) -> None:
        tk.Frame(self.quick_preferences, bg=C["hairline"], height=1).pack(fill="x", pady=14)
        self.advanced_btn = RoundedButton(self.quick_preferences, "高级设置  ›", self._toggle_advanced,
                                          font_size=9, padx=13, height=34)
        self.advanced_btn.pack(anchor="w")
        ttk.Label(self.quick_preferences, text="接口、会话与重连策略",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(5, 0))

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.quick_wrap.pack_forget()
            self.advanced_wrap.pack(fill="both", expand=True, padx=24, pady=(0, 16))
            self.back_btn.focus_set()
        else:
            self.advanced_wrap.pack_forget()
            self.quick_wrap.pack(fill="both", expand=True, padx=24, pady=(0, 16))
            self.root.after_idle(self.advanced_btn.focus_set)
        self._fit_connection_header()

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
        """按所选模板生成配置，并自动探测门户类型；与所选不一致时提醒。"""
        selected = self.template_var.get() if self.template_var else None
        address = self.address_var.get().strip() if self.address_var else ""
        try:
            self._apply_template_and_address(selected, address)
        except ValueError as exc:
            messagebox.showerror("门户地址有误", str(exc), parent=self.root)
            self.address_entry.focus_set()
            return
        if not address:
            messagebox.showinfo(
                "已生成",
                "配置已按所选模板生成。\n\n如需自动校验门户类型，请先填写门户地址。")
            return
        # 后台探测一次：不阻塞界面；探测结果用于校验「所选类型」是否与实际门户一致
        self._probe_async(address, self._on_generate_probe_done)

    @staticmethod
    def _detect_consistency(selected: str | None, detected: str | None) -> str:
        """比较「用户所选类型」与「自动探测类型」。

        返回：
        - "unknown"：未探测出类型（可能已联网 / 地址不可达）
        - "match"：一致
        - "custom"：用户选了自定义模板，探测结果仅提示、不强制替换
        - "mismatch"：不一致（应提醒是否切换）
        """
        if not detected:
            return "unknown"
        if selected == detected:
            return "match"
        if not selected or selected.startswith("自定义"):
            return "custom"
        return "mismatch"

    def _on_generate_probe_done(self, result: dict) -> None:
        """「应用模板」的探测回调：类型不一致时询问是否改用探测结果。"""
        selected = self.template_var.get() if self.template_var else None
        detected = result.get("template")
        state = self._detect_consistency(selected, detected)
        elapsed = result.get("elapsed")
        meta = f"（耗时 {elapsed:.2f}s）" if isinstance(elapsed, (int, float)) else ""
        if state == "match":
            messagebox.showinfo(
                "已生成",
                f"配置已按「{selected}」生成，自动探测确认门户类型一致。{meta}\n\n"
                "可从「工具」导出配置，也可直接开启后台守护。")
            return
        if state == "mismatch":
            switch = messagebox.askyesno(
                "门户类型不一致",
                f"自动探测到的门户类型是「{detected}」，与您选择的「{selected}」不一致。{meta}\n\n"
                f"是否改用「{detected}」重新生成配置？\n\n"
                "（若不确定，建议选择「是」；也可稍后点「自动探测类型」手动确认）")
            if switch:
                if self.template_var is not None:
                    self.template_var.set(detected)
                self._apply_template_and_address(
                    detected, self.address_var.get() if self.address_var else None)
                messagebox.showinfo("已更新", f"已按探测结果「{detected}」重新生成配置。")
            else:
                messagebox.showinfo(
                    "已保留",
                    f"已保留您选择的「{selected}」。\n\n"
                    "如果认证失败，建议点「自动探测类型」重新确认。")
            return
        if state == "custom":
            messagebox.showinfo(
                "已生成",
                f"配置已生成。自动探测识别为「{detected}」{meta}；\n"
                "您当前选择的是「自定义」，已保留手填内容，如需自动填充可点「自动探测类型」。")
            return
        messagebox.showinfo(
            "已生成",
            "配置已按所选模板生成。\n\n"
            "未能自动识别门户类型（可能已联网或门户地址不可达），请核对配置后保存。")

    def _auto_fill_address(self) -> None:
        """断网时从网关劫持中提取门户地址（后台执行，避免多目标探测时界面卡死）。"""
        import queue
        import threading

        from .network import detect_portal_host
        q: queue.Queue = queue.Queue()
        self._set_fetch_busy(True)

        def worker() -> None:
            try:
                q.put(detect_portal_host())
            except Exception as exc:  # 探测异常不崩界面
                q.put((None, [f"探测异常：{type(exc).__name__}: {exc}"]))
        threading.Thread(target=worker, daemon=True).start()
        self._poll_fetch(q)

    def _set_fetch_busy(self, busy: bool) -> None:
        """「自动获取」按钮的进行中状态。"""
        if getattr(self, "fetch_btn", None) is None:
            return
        self.fetch_btn._text = "获取中…" if busy else "自动获取"
        self.fetch_btn._repaint()

    def _poll_fetch(self, q) -> None:
        try:
            host, evidence = q.get_nowait()
        except Exception:
            self.root.after(200, lambda: self._poll_fetch(q))
            return
        self._set_fetch_busy(False)
        self._apply_fetched_address(host, evidence)

    def _apply_fetched_address(self, host: str | None, evidence: list[str]) -> None:
        """展示自动获取结果：成功则填入地址框，失败则给出排查提示。"""
        if host:
            if self.address_var is not None:
                self.address_var.set(host)
            messagebox.showinfo("已获取", f"已自动获取门户地址：{host}")
            return
        detail = "\n".join(evidence[-8:]) if evidence else "（无探测记录）"
        messagebox.showinfo(
            "未获取到",
            "未能自动获取门户地址。\n\n"
            "请确认：\n"
            "1. 已连接校园网（WiFi 或网线）；\n"
            "2. 当前处于「未认证」状态（浏览器打开任意网站会被跳到认证页）。\n\n"
            f"探测记录：\n{detail}\n\n"
            "也可直接手动填写门户地址（如 10.0.0.1）。")

    def _probe_async(self, address: str, on_done) -> None:
        """后台探测门户类型；完成后回到 Tk 主线程调用 on_done(result)。"""
        import queue
        import threading

        from .detect import probe_portal
        q: queue.Queue = queue.Queue()
        self._set_detect_busy(True)

        def worker() -> None:
            try:
                q.put(probe_portal(address))
            except Exception as exc:  # 探测任何异常都不崩界面
                q.put({"recognized": False, "type": None, "template": None, "mode": "simple",
                       "message": f"探测失败：{exc}", "evidence": [], "elapsed": 0.0})
        threading.Thread(target=worker, daemon=True).start()
        self._poll_probe(q, on_done)

    def _poll_probe(self, q, on_done) -> None:
        try:
            result = q.get_nowait()
        except Exception:
            self.root.after(200, lambda: self._poll_probe(q, on_done))
            return
        self._set_detect_busy(False)
        on_done(result)

    def _set_detect_busy(self, busy: bool) -> None:
        """探测期间给按钮一个进行中状态，避免用户以为界面卡死。"""
        if getattr(self, "detect_btn", None) is None:
            return
        self.detect_btn._text = "探测中…" if busy else "自动探测类型"
        self.detect_btn._repaint()

    def _auto_detect(self) -> None:
        """后台探测门户类型，识别后自动填充模板。"""
        address = self.address_var.get().strip() if self.address_var else ""
        if not address:
            messagebox.showwarning("提示", "请先填写门户地址")
            return
        self._probe_async(address, self._on_detect_result)

    def _on_detect_result(self, result: dict) -> None:
        template = result.get("template")
        if template and self.template_var is not None:
            self.template_var.set(template)
        self._apply_template_and_address(
            template if template else (self.template_var.get() if self.template_var else None),
            self.address_var.get() if self.address_var else None)
        evidence = result.get("evidence") or []
        detail = "\n".join(evidence[:6]) if evidence else ""
        elapsed = result.get("elapsed")
        meta = f"（耗时 {elapsed:.2f}s）" if isinstance(elapsed, (int, float)) else ""
        messagebox.showinfo("探测结果", f"{result.get('message', '')}{meta}\n\n{detail}")

    def _build_notebook(self) -> None:
        self.advanced_wrap = ttk.Frame(self.content, style="Page.TFrame")
        bar = tk.Frame(self.advanced_wrap, bg=C["page"])
        bar.pack(fill="x", pady=(0, 6))
        self.back_btn = RoundedButton(bar, "‹  返回连接设置", self._toggle_advanced,
                                      font_size=9, padx=14, height=32)
        self.back_btn.pack(side="left")
        tk.Label(bar, text="高级设置", bg=C["page"], fg=C["title"],
                 font=(F["ui"], 12, "bold")).pack(side="left", padx=14)

        self.notebook = ttk.Notebook(self.advanced_wrap)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.enable_traversal()

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
        _, card = self._scroll_card(outer, padding=20)
        card.columnconfigure(1, weight=1)
        return card

    def _scroll_card(self, outer: ttk.Frame, padding: int, surface=C["card"]) -> tuple[tk.Canvas, ttk.Frame]:
        canvas = tk.Canvas(outer, bg=surface, highlightthickness=1,
                           highlightbackground=C["border"] if surface == C["card"] else surface, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        card = ttk.Frame(canvas, style="Card.TFrame", padding=padding)
        window = canvas.create_window(0, 0, window=card, anchor="nw")
        def update_scrollbar(first, last):
            scrollbar.set(first, last)
            scrollbar.state(["disabled" if float(first) <= 0 and float(last) >= 1 else "!disabled"])

        canvas.configure(yscrollcommand=update_scrollbar)
        card.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=max(1, e.width - 2)))
        # 仅在鼠标位于此页时滚动；不使用 bind_all，避免干扰其他窗口。
        def wheel(event):
            if card.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        def bind_wheel(widget):
            # Combobox 保留滚轮切换选项。
            if not isinstance(widget, ttk.Combobox):
                widget.bind("<MouseWheel>", wheel, add="+")
            if isinstance(widget, (ttk.Entry, ttk.Checkbutton, tk.Text, RoundedButton)):
                widget.bind("<FocusIn>", reveal, add="+")
            for child in widget.winfo_children():
                bind_wheel(child)

        def reveal(event):
            widget = event.widget
            top = widget.winfo_rooty() - canvas.winfo_rooty()
            bottom = top + widget.winfo_height()
            if top < 0 or bottom > canvas.winfo_height():
                offset = widget.winfo_rooty() - card.winfo_rooty() - 12
                canvas.yview_moveto(max(0, offset) / max(1, card.winfo_height()))

        canvas.bind("<MouseWheel>", wheel)
        card.after_idle(lambda: bind_wheel(card))
        return canvas, card

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
            entry = ttk.Entry(parent, textvariable=var, font=(F["ui"], 10))
            self.field_entries[key] = entry
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
        mode_box = ttk.Combobox(parent, textvariable=self.mode_var, values=MODES,
                                state="readonly", width=18, font=(F["ui"], 10))
        mode_box.grid(row=row, column=1, sticky="w", pady=4)
        row += 1
        row = self._section(parent, "门户地址",
                            "主机、端口与协议以门户配置卡片中的地址为准。", row)
        self._form(parent, ["portal.entry_path"], row)

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
        row += 2
        row = self._section(parent, "自动保护", "复核越频繁越早发现掉线；失败后最多等「失败重试上限」再重试", row)
        self._form(parent, list(_SECONDS_FIELDS), row)

    def _build_advanced(self, parent: ttk.Frame) -> None:
        row = self._section(parent, "会话", "sessionId 的获取方式", 0)
        self._form(parent, ["session.mode", "session.field_name", "session.redirect_probe_url"], row)
        row += 3
        ttk.Label(parent, text="错误文案（每行：类别=标记1,标记2）", style="Card.TLabel").grid(
            row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        self.error_markers_text = self._make_text(parent, 7, mono=True)
        self.error_markers_text.grid(row=row, column=1, sticky="we", pady=4)

    def _build_footer(self) -> None:
        footer = tk.Frame(self.content, bg=C["card"])
        footer.pack(side="bottom", fill="x")
        self.footer_widget = footer
        tk.Frame(footer, bg=C["hairline"], height=1).pack(fill="x")
        row = tk.Frame(footer, bg=C["card"])
        row.pack(fill="x", padx=24, pady=12)
        self.start_btn = RoundedButton(
            row, "开启后台守护", self._start_autologin,
            fill=C["primary"], fg=C["white"], border=C["primary"],
            hover_fill=C["primary_hover"], hover_border=C["primary_hover"],
            bold=True, padx=24, width=188, height=44,
        )
        self.start_btn.pack(side="right", padx=(12, 0))
        tk.Label(row, text="后台守护 · 断线重连", bg=C["card"], fg=C["title"],
                 font=(F["ui"], 10, "bold"), padx=0).pack(anchor="w")
        self.footer_hint = tk.StringVar()
        tk.Label(row, textvariable=self.footer_hint, bg=C["card"], fg=C["muted"],
                 font=(F["ui"], 9), padx=0, justify="left", wraplength=460).pack(anchor="w", pady=(3, 0))

    # ---- 开始自动保护 ----

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
        self._account_ready = True
        self._refresh_connection()
        messagebox.showinfo("已更新", "账号密码已更新，下次自动保护将使用新密码。")

    def _start_autologin(self) -> None:
        """保存配置 → 确认账号密码 → 启动（或重启）独立后台保护进程。"""
        if self.template_var.get() != self._applied_template:
            messagebox.showwarning("模板尚未应用", "请先点击「应用模板」，再开启后台守护。", parent=self.root)
            if self.advanced_visible:
                self._toggle_advanced()
            self.root.after_idle(self.apply_template_btn.focus_set)
            return
        # 1) 保存配置到工具目录（先做输入校验，避免把非法配置写进 portal.json）
        data, error = self._collect_safe()
        if error:
            messagebox.showerror("配置有误", error, parent=self.root)
            self._focus_invalid_field(error)
            return
        portal_file = _tool_root() / "portal.json"
        try:
            portal_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("配置未保存", f"无法写入 portal.json：{exc}", parent=self.root)
            return
        self._portal_saved = True
        self._remember_form()
        self._refresh_connection()

        # 2) 确认账号密码
        from .config import ConfigError, load_credentials, save_credentials
        try:
            load_credentials()
        except ConfigError:
            self._account_ready = False
            credentials = self._prompt_credentials()
            if credentials is None:
                self.start_btn.focus_set()
                return
            try:
                save_credentials(credentials)
            except OSError as exc:
                messagebox.showerror("保存失败", f"无法保存账号密码：{exc}")
                return

        self._account_ready = True
        self._refresh_connection()
        # 3) 启动（或重启）独立保护进程：若已在保护中，先停止再启动，让新配置生效
        from .daemon import ALREADY_RUNNING, STARTED, is_running, start_status, stop
        was_running = is_running()
        if was_running:
            stopped = stop()
            # stop() 返回 False 时可能只是"恰好已经退出"，再确认一次；仍在运行则必须报错，
            # 否则会把"旧进程没停掉"误报成"新配置已生效"（假重启）。
            if not stopped and is_running():
                messagebox.showerror(
                    "无法停止旧保护进程",
                    "检测到后台保护进程仍在运行，但无法停止它（缺少 watch.pid，可能是旧版本残留）。\n\n"
                    "请打开任务管理器，结束所有 campus-auth.exe 后重试。\n"
                    "本次新配置尚未生效。")
                return
        status = start_status()
        self._refresh_connection()
        if status == ALREADY_RUNNING:
            messagebox.showerror(
                "启动失败",
                "配置已保存。检测到另一个守护进程已启动，请稍后重试。")
            return
        if status != STARTED:
            messagebox.showerror(
                "启动失败",
                "配置已保存，但未能启动后台守护。\n\n"
                "请确认程序目录完整，或改用托盘菜单「开启自动保护」重试。")
            return
        from .startup import startup_enabled
        auto_hint = _autostart_hint(startup_enabled())
        if was_running:
            messagebox.showinfo(
                "已重启自动保护",
                f"自动保护已重启，新配置已生效。\n\n"
                f"运行方式：后台持续守护、断线自动重连（关闭本窗口不影响；"
                f"停止请用托盘菜单「停止自动保护」）。\n"
                f"开机自启：{auto_hint}\n\n"
                f"配置已保存到：{portal_file}\n"
                f"账号密码保存在：{_credentials_file_hint()}")
        else:
            messagebox.showinfo(
                "已开启自动保护",
                f"自动保护已在后台持续运行：断线自动重连，关闭本窗口不影响"
                f"（停止请用托盘菜单「停止自动保护」）。\n\n"
                f"开机自启：{auto_hint}\n\n"
                f"配置已保存到：{portal_file}\n"
                f"账号密码保存在：{_credentials_file_hint()}")

    def _focus_invalid_field(self, error: str) -> None:
        if "门户地址" in error:
            if self.advanced_visible:
                self._toggle_advanced()
            self.root.after_idle(self.address_entry.focus_set)
            return
        entry = next((widget for key, widget in self.field_entries.items()
                      if error.startswith(_FIELD_LABELS.get(key, key))), None)
        if entry is None and "额外固定字段" in error:
            entry = self.extra_fields_text
        if entry is not None:
            if not self.advanced_visible:
                self._toggle_advanced()
            self.notebook.select(entry.master.master.master)
            self.root.after_idle(entry.focus_set)

    def _prompt_credentials(self):
        """弹窗输入账号密码与运营商，返回 Credentials 或 None。"""
        from .client import Credentials
        top = tk.Toplevel(self.root)
        top.title("输入校园网账号")
        top.configure(bg=C["card"])
        top.transient(self.root)
        top.grab_set()

        ttk.Label(top, text="校园网账号", style="Section.TLabel").pack(anchor="w", padx=22, pady=(18, 4))
        user = ttk.Entry(top, width=32, font=(F["ui"], 10))
        user.pack(fill="x", padx=22, pady=(0, 10))
        _bind_context_menu(user)

        tk.Label(top, text="校园网密码", bg=C["card"], fg=C["text"], font=(F["ui"], 10)).pack(anchor="w", padx=22, pady=(0, 4))
        pwd = ttk.Entry(top, width=32, show="•", font=(F["ui"], 10))
        pwd.pack(fill="x", padx=22, pady=(0, 10))
        _bind_context_menu(pwd)

        tk.Label(top, text="运营商（可输入或选择）", bg=C["card"], fg=C["text"], font=(F["ui"], 10)).pack(anchor="w", padx=22, pady=(0, 4))
        operators = ("中国移动", "中国联通", "中国电信", "校园网")
        service_var = tk.StringVar(value=operators[0])
        service = ttk.Combobox(top, textvariable=service_var, values=operators, width=32, font=(F["ui"], 10))
        service.pack(fill="x", padx=22, pady=(0, 14))

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
        row.pack(fill="x", padx=22, pady=(0, 18))
        RoundedButton(row, "取消", cancel).pack(side="left")
        RoundedButton(row, "确定", ok, fill=C["primary"], fg=C["white"], border=C["primary"],
                      hover_fill=C["primary_hover"], hover_border=C["primary_hover"], gradient_to=C["primary_hover"], bold=True).pack(side="right")

        top.bind("<Escape>", lambda event: cancel())
        user.focus_set()
        self.root.wait_window(top)
        if not result or not result.get("username") or not result.get("password"):
            return None
        return Credentials(result["username"], result["password"], result.get("service", ""))

    # ---- 数据装配 ----

    @staticmethod
    def _parse_port(value: str, label: str) -> int:
        """端口输入校验：必须是 1-65535 的数字。"""
        if not value.isdigit():
            raise ValueError(f"{label} 必须是数字（当前：{value!r}）")
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError(f"{label} 超出 1-65535 范围（当前：{port}）")
        return port

    def _collect_safe(self) -> tuple[dict | None, str]:
        """组装配置；输入非法时返回 (None, 错误说明)，而不是把异常抛给 Tk 回调。"""
        try:
            return self._collect(), ""
        except ValueError as exc:
            return None, str(exc)
        except Exception as exc:  # 兜底：任何解析异常都转成可读提示
            return None, f"配置解析失败：{exc}"

    def _collect(self) -> dict:
        """从表单组装 portal.json 结构（输入非法时抛 ValueError）。

        以「上次加载的完整画像」为基底，只覆盖表单里出现的字段：这样表单没有
        暴露的字段（watch.network_events、login 段等）不会被保存动作重置为默认值。
        """
        base = getattr(self, "_loaded_data", None)
        if not isinstance(base, dict):
            base = DEFAULT_PROFILE
        data = json.loads(json.dumps(base, ensure_ascii=False))
        for key, var in self.vars.items():
            value = var.get().strip()
            if key in ("portal.port", "connectivity.probe_port"):
                _set(data, key, self._parse_port(value, _FIELD_LABELS.get(key, key)))
            elif key in _SECONDS_FIELDS:
                _set(data, key, _parse_seconds(value, _FIELD_LABELS.get(key, key)))
            else:
                _set(data, key, value)
        data["auth_mode"] = self.mode_var.get()
        # 门户地址以快速开始区的输入框为准（单一数据源，保证输入框与保存结果一致）
        if self.address_var is not None:
            _apply_address(data, self.address_var.get())
        hosts = [h.strip() for h in data["connectivity"]["probe_hosts"].split(",") if h.strip()] \
            if isinstance(data["connectivity"].get("probe_hosts"), str) else data["connectivity"]["probe_hosts"]
        data["connectivity"]["probe_hosts"] = hosts or ["www.baidu.com", "www.qq.com"]
        if self.extra_fields_text is not None:
            raw = self.extra_fields_text.get("1.0", "end").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                except ValueError as exc:
                    raise ValueError(f"「通用登录」的额外固定字段不是合法 JSON：{exc}") from exc
                if not isinstance(parsed, dict):
                    raise ValueError("「通用登录」的额外固定字段必须是 JSON 对象（形如 {\"key\": \"value\"}）")
                data["simple_login"]["extra_fields"] = parsed
            else:
                data["simple_login"]["extra_fields"] = {}
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
        # 记录完整画像作为 _collect 的基底：保留表单未暴露的字段（见 _collect 注释）
        try:
            self._loaded_data = (json.loads(json.dumps(data, ensure_ascii=False))
                                 if isinstance(data, dict) else None)
        except (TypeError, ValueError):
            self._loaded_data = None
        auth = data.get("auth_mode", "workflow")
        self.mode_var.set(auth)
        # 门户地址框是唯一数据源：显示完整地址（含协议与非默认端口），保证往返不丢配置
        if self.address_var is not None:
            self.address_var.set(_format_address(data))
        # 根据 auth_mode 同步模板下拉框，避免后续「一键生成」把模式覆盖回默认
        if self.template_var is not None:
            if auth == "cas":
                self.template_var.set("华三 CAS SSO（加密）")
            elif auth == "simple":
                self.template_var.set("通用（简单登录）")
            else:
                self.template_var.set("锐捷 SAM+（工作流）")
            self._applied_template = self.template_var.get()
        for key in self.vars:
            value = _get(data, key, "")
            if key == "connectivity.probe_hosts" and isinstance(value, list):
                value = ",".join(value)
            # watch.* 等数值字段（int）在这里由 str() 统一转成表单文本，_collect 再解析回 int
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
        """（兼容旧调用）配置预览区已移除，保留空方法避免调用点报错。"""
        return

    def save_file(self) -> None:
        target = self.profile_path or filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="portal.json")
        if not target:
            return
        data, error = self._collect_safe()
        if error:
            messagebox.showerror("保存失败", error)
            return
        try:
            Path(target).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法写入 {target}：{exc}")
            return
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
    hwnd = user32.FindWindowW(None, CONFIG_WINDOW_TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


def _window_icon_path() -> Path:
    """配置窗口图标（tray.ico）：_MEIPASS / 项目根 / 包内（pip 安装）依次回退。"""
    import sys
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "tray.ico")
    candidates.append(Path(__file__).resolve().parent.parent / "tray.ico")
    candidates.append(Path(__file__).resolve().parent / "tray.ico")
    for path in candidates:
        if path.exists():
            return path
    return candidates[-1]


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
