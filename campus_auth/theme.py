"""theme.py —— 现代中性灰 UI 主题与自绘组件（纯标准库 tkinter/ttk）。

设计语言：高级中性灰 × 明亮简约。
浅灰底 + 白卡片 + 1px 发丝描边 + 单一强调蓝 + 大留白。
禁止阴影、渐变、半透明、毛玻璃。

本文件是配色 / 间距 / 圆角 / 字号的唯一事实来源，业务代码只引用 Token，
禁止裸写颜色值或魔法数字。
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ================================================================ 色彩 Token
C = {
    # 中性灰阶（冷调、低饱和）
    "n0": "#FFFFFF",    # 卡片、输入框表面
    "n25": "#FBFBFC",   # 应用窗口底色
    "n50": "#F5F6F8",   # 次级面板、hover 底
    "n100": "#EDEFF2",  # 分区底、按钮按下底、禁用底
    "n150": "#E4E7EB",  # 分隔线
    "n200": "#DCE0E5",  # 默认 1px 描边
    "n300": "#C6CCD3",  # 强描边 / 输入框 hover 边
    "n400": "#8A929C",  # 占位符、禁用文字
    "n500": "#6B7480",  # 辅助文字
    "n600": "#4E565F",  # 次级正文
    "n700": "#3A414A",  # 正文默认色
    "n800": "#262C34",  # 标题
    "n900": "#14181D",  # 最高对比 / Toast 深底
    # 强调色（唯一）
    "accent": "#2F6BE4",
    "accent_hover": "#2559C7",
    "accent_active": "#1E4AA8",
    "accent_subtle": "#EEF3FE",
    "accent_border": "#BFD3F8",
    # 语义色
    "success": "#1F7A4D", "success_bg": "#E9F5EF", "success_border": "#BCE0CD",
    "warning": "#8A5A00", "warning_bg": "#FFF5E5", "warning_border": "#F0D8A8",
    "danger": "#C22B3A", "danger_bg": "#FDEDEF", "danger_border": "#F4C4CA",
    "danger_hover": "#AE2735", "danger_active": "#98212E",
    "white": "#FFFFFF",
}

# 旧 key 兼容映射（campus-auth 内部既有代码用的 key → 新 Token）
C_COMPAT = {
    "page": C["n25"],
    "card": C["n0"],
    "primary": C["accent"],
    "primary_hover": C["accent_hover"],
    "text": C["n700"],
    "muted": C["n500"],
    "border": C["n200"],
    "input": C["n0"],
    "tab": C["n25"],
    "white": C["white"],
}

# ================================================================ 间距 Token（4px 基准）
S = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32, "10": 40, "12": 48}

# ================================================================ 圆角 Token
R = {"none": 0, "sm": 4, "md": 8, "lg": 10, "xl": 14, "full": 999}

# ================================================================ 控件尺寸
SZ = {"xs": 24, "sm": 28, "md": 32, "lg": 40}

# ================================================================ 动效
MOTION = {"fast": 120, "base": 180, "slow": 240, "fps": 60}
REDUCE_MOTION = False

# ================================================================ 字体
_FAMILY = {
    "win32": ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"],
    "darwin": ["PingFang SC", "Helvetica Neue", "Lucida Grande"],
    "linux": ["Noto Sans CJK SC", "Noto Sans", "DejaVu Sans"],
}
_MONO = {
    "win32": ["Cascadia Mono", "Consolas"],
    "darwin": ["SF Mono", "Menlo"],
    "linux": ["Noto Sans Mono", "DejaVu Sans Mono"],
}

UI_FAMILY = ""
MONO_FAMILY = ""
FONT: dict[str, tkfont.Font] = {}


def init_fonts(root: tk.Misc) -> None:
    """必须在创建 Tk 根窗口之后、创建任何控件之前调用。"""
    global UI_FAMILY, MONO_FAMILY
    available = set(tkfont.families(root))
    ui_prefs = _FAMILY.get(sys.platform, _FAMILY["linux"])
    mono_prefs = _MONO.get(sys.platform, _MONO["linux"])
    UI_FAMILY = next((n for n in ui_prefs if n in available), "TkDefaultFont")
    MONO_FAMILY = next((n for n in mono_prefs if n in available), UI_FAMILY)

    _scale = {
        "display": (18, "bold"), "title": (15, "bold"), "heading": (12, "bold"),
        "subheading": (10, "bold"), "body": (10, "normal"),
        "caption": (9, "normal"), "micro": (8, "normal"),
    }
    for name, (size, weight) in _scale.items():
        FONT[name] = tkfont.Font(root=root, family=UI_FAMILY, size=size, weight=weight)
    FONT["mono"] = tkfont.Font(root=root, family=MONO_FAMILY, size=10)


def tfont(token: str, weight: str | None = None, size: int | None = None):
    """取字体，返回 (family, size, weight) 元组，供 tk 控件 font= 使用。"""
    f = FONT.get(token) or FONT.get("body")
    return (f.cget("family"), size or f.cget("size"), weight or f.cget("weight"))


# ================================================================ 辅助绘制
def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形，返回 item id。r 自动裁剪到合法范围。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def hairline(parent, bg=None, border=None, **kw):
    """发丝描边容器：tkinter 里最可靠的 1px 边框方案。"""
    return tk.Frame(parent, bg=bg or C["n0"], highlightthickness=1,
                    highlightbackground=border or C["n200"],
                    highlightcolor=border or C["n200"], **kw)


def divider(parent, orient="horizontal", color=None):
    """1px 分隔线。"""
    c = color or C["n150"]
    if orient == "horizontal":
        return tk.Frame(parent, height=1, bg=c)
    return tk.Frame(parent, width=1, bg=c)


def mix(hex_a: str, hex_b: str, t: float) -> str:
    """两个十六进制颜色之间线性插值，t ∈ [0,1]。"""
    a = tuple(int(hex_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def animate(widget, duration_ms, on_frame, on_done=None):
    """属性插值动画（ease-out cubic）。on_frame(t) 被调用若干次，t 从 0 → 1。"""
    if REDUCE_MOTION:
        on_frame(1.0)
        if on_done:
            on_done()
        return
    fps = MOTION["fps"]
    steps = max(1, int(duration_ms / (1000 / fps)))

    def tick(i):
        t = i / steps
        on_frame(1 - (1 - t) ** 3)
        if i < steps:
            widget.after(int(1000 / fps), tick, i + 1)
        elif on_done:
            on_done()

    tick(0)


# ================================================================ 自绘按钮
class FlatButton(tk.Canvas):
    """圆角按钮（纯色，无渐变）。tkinter 原生按钮无圆角，故自绘。

    注意：必须传 parent_bg（父容器底色），否则四角露方底。
    """

    VARIANTS = {
        # (默认底, hover底, 按下底, 文字色, 描边色)
        "primary": (C["accent"], C["accent_hover"], C["accent_active"], C["white"], C["accent"]),
        "secondary": (C["n0"], C["n50"], C["n100"], C["n700"], C["n200"]),
        "ghost": (None, C["n100"], C["n150"], C["n600"], None),
        "danger": (C["danger"], C["danger_hover"], C["danger_active"], C["white"], C["danger"]),
    }

    def __init__(self, master, text="", command=None, variant="primary",
                 width=88, height=SZ["md"], radius=R["md"], font_token="body",
                 parent_bg=None, bold=False):
        self._pbg = parent_bg or master.cget("bg")
        super().__init__(master, width=width, height=height, bg=self._pbg,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        n, h, a, fg, bd = self.VARIANTS[variant]
        self._n = n or self._pbg
        self._h, self._a, self._fg, self._bd = h, a, fg, bd or self._n
        self._command = command
        self._enabled = True

        self._shape = round_rect(self, 0.5, 0.5, width - 0.5, height - 0.5, radius,
                                 fill=self._n, outline=self._bd, width=1)
        self._text = self.create_text(width / 2, height / 2, text=text, fill=fg,
                                      font=tfont(font_token, weight="bold" if bold else None))

        self.bind("<Enter>", lambda e: self._paint(self._h))
        self.bind("<Leave>", lambda e: self._paint(self._n, self._bd))
        self.bind("<ButtonPress-1>", lambda e: self._paint(self._a))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda e: self.itemconfigure(self._shape, outline=C["accent"], width=2))
        self.bind("<FocusOut>", lambda e: self.itemconfigure(self._shape, outline=self._bd, width=1))
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())

    def _paint(self, fill, outline=None):
        if not self._enabled:
            return
        self.itemconfigure(self._shape, fill=fill, outline=outline or fill)

    def _release(self, event):
        if not self._enabled:
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._paint(self._h)
        if inside:
            self.invoke()

    def invoke(self):
        if self._enabled and self._command:
            self._command()

    def set_text(self, text):
        self.itemconfigure(self._text, text=text)

    def set_enabled(self, flag):
        self._enabled = flag
        self.configure(cursor="hand2" if flag else "arrow")
        self.itemconfigure(self._shape,
                           fill=self._n if flag else C["n100"],
                           outline=self._bd if flag else C["n200"])
        self.itemconfigure(self._text, fill=self._fg if flag else C["n400"])


# ================================================================ 高 DPI
def enable_dpi_awareness():
    """必须在创建 Tk() 之前调用，否则高 DPI 下字会糊。"""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def sync_scaling(root: tk.Misc):
    """让 Tk 的 pt 字号匹配真实 DPI。创建根窗口后调用一次。"""
    try:
        dpi = root.winfo_fpixels("1i")
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
