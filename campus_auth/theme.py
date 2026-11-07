"""theme.py —— 现代中性灰 UI 配色与间距 Token（纯标准库）。

设计语言：高级中性灰 × 明亮简约。
浅灰底 + 白卡片 + 1px 发丝描边 + 单一强调蓝 + 大留白。
禁止阴影、渐变、半透明、毛玻璃。

说明：自绘控件（圆角按钮等）与字体选择在 config_gui 内实现；
本模块只保留被实际引用的配色/间距 Token，不再维护未使用的组件与字号体系。
"""
from __future__ import annotations

# ================================================================ 色彩 Token
C = {
    # 中性灰阶（冷调、低饱和）
    "n0": "#FFFFFF",    # 卡片、输入框表面
    "n25": "#F5F7FA",   # 应用窗口底色
    "n50": "#F0F3F7",   # 次级面板、hover 底
    "n100": "#EDEFF2",  # 分区底、按钮按下底、禁用底
    "n150": "#E4E7EB",  # 分隔线
    "n200": "#DCE3EC",  # 默认 1px 描边
    "n300": "#C6CCD3",  # 强描边 / 输入框 hover 边
    "n400": "#8A929C",  # 占位符、禁用文字
    "n500": "#6B7480",  # 辅助文字
    "n600": "#4E565F",  # 次级正文
    "n700": "#3A414A",  # 正文默认色
    "n800": "#18283D",  # 标题
    "n900": "#14181D",  # 最高对比 / Toast 深底
    # 强调色（唯一）
    "accent": "#245FD6",
    "accent_hover": "#204FC8",
    "accent_active": "#1942AD",
    "accent_subtle": "#EAF0FF",
    "accent_border": "#BFD3F8",
    # 语义色
    "success": "#1F7A4D", "success_bg": "#E9F5EF", "success_border": "#BCE0CD",
    "warning": "#8A5A00", "warning_bg": "#FFF5E5", "warning_border": "#F0D8A8",
    "danger": "#C22B3A", "danger_bg": "#FDEDEF", "danger_border": "#F4C4CA",
    "danger_hover": "#AE2735", "danger_active": "#98212E",
    "white": "#FFFFFF",
}

# ================================================================ 间距 Token（4px 基准）
S = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32, "10": 40, "12": 48}
