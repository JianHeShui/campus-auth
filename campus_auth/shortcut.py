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
    """快捷方式的目标程序与参数。"""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ""
    # 源码：pythonw 运行 tray_app.pyw
    from .config_gui import _tool_root
    root = _tool_root()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return str(pythonw), str(root / "tray_app.pyw")


def create_desktop_shortcut() -> bool:
    """在桌面创建快捷方式，返回是否成功。"""
    target, args = _launch_target()
    lnk = _shortcut_path()
    workdir = str(Path(target).parent)
    # 用 PowerShell 的 WScript.Shell 创建 .lnk（用 EncodedCommand 避免引号转义问题）
    script = (
        f"$W = New-Object -ComObject WScript.Shell; "
        f"$S = $W.CreateShortcut('{lnk}'); "
        f"$S.TargetPath = '{target}'; "
        f"$S.Arguments = '{args}'; "
        f"$S.WorkingDirectory = '{workdir}'; "
        f"$S.IconLocation = '{target},0'; "
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
