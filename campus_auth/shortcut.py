"""桌面快捷方式：首次启动时在桌面创建「校园网自动登录」快捷方式。

用标记文件避免每次启动都重复创建；创建失败静默（不阻塞程序）。
"""
from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "校园网自动登录.lnk"
MARKER = Path.home() / ".campus-auth" / ".shortcut_created"


def _desktop_dir() -> Path:
    """获取真实桌面目录（CSIDL_DESKTOP=0，兼容桌面重定向到 OneDrive 的情况）。"""
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)
    return Path(buf.value) if buf.value else (Path.home() / "Desktop")


def _shortcut_path() -> Path:
    return _desktop_dir() / SHORTCUT_NAME


def _launch_target() -> tuple[str, str]:
    """快捷方式的目标程序与参数（参数已按命令行规则转义，含空格路径也安全）。"""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ""
    # 源码：pythonw 运行 tray_app.pyw
    from .config_gui import _tool_root
    root = _tool_root()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    entry = str(root / "tray_app.pyw")
    return str(pythonw), subprocess.list2cmdline([entry])


def _icon_location(target: str) -> str:
    """快捷方式图标：源码模式用项目根 tray.ico；打包版 exe 已内嵌图标。"""
    if not getattr(sys, "frozen", False):
        icon = Path(__file__).resolve().parent.parent / "tray.ico"
        if icon.exists():
            return f"{icon},0"
    return f"{target},0"


def create_desktop_shortcut() -> bool:
    """在桌面创建快捷方式，返回是否成功。"""
    target, args = _launch_target()
    lnk = _shortcut_path()
    workdir = str(Path(target).parent)
    icon = _icon_location(target)

    def _ps(value) -> str:
        """PowerShell 单引号字符串转义。"""
        return str(value).replace("'", "''")

    # 用 PowerShell 的 WScript.Shell 创建 .lnk（用 EncodedCommand 避免引号转义问题）
    script = (
        f"$W = New-Object -ComObject WScript.Shell; "
        f"$S = $W.CreateShortcut('{_ps(lnk)}'); "
        f"$S.TargetPath = '{_ps(target)}'; "
        f"$S.Arguments = '{_ps(args)}'; "
        f"$S.WorkingDirectory = '{_ps(workdir)}'; "
        f"$S.IconLocation = '{_ps(icon)}'; "
        f"$S.Description = '校园网自动登录'; "
        f"$S.Save()"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
            check=False,
        )
        return r.returncode == 0 and _shortcut_path().exists()
    except Exception:
        return False


def ensure_desktop_shortcut() -> None:
    """首次启动时创建桌面快捷方式（用标记文件避免重复）。"""
    if MARKER.exists():
        return
    try:
        if create_desktop_shortcut():
            MARKER.parent.mkdir(parents=True, exist_ok=True)
            MARKER.touch()
    except OSError:
        pass  # 创建失败不阻塞程序
