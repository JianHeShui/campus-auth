"""Windows 开机自启：读写当前用户注册表 Run 项（无需管理员权限）。

启动命令会根据运行方式生成：
- 打包成 exe 时：`"exe路径" tray`
- 源码运行时：用 pythonw 直接运行 tray_app.pyw（无控制台，避免开机弹 cmd）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CampusAuth"


def _project_root() -> Path:
    """campus-auth 项目根目录（campus_auth 包的上一级）。"""
    return Path(__file__).resolve().parent.parent


def launch_command() -> str:
    """生成开机自启要执行的完整命令行字符串（启动托盘入口，无控制台）。"""
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable, "tray"])
    # 源码：用 pythonw 直接运行 tray_app.pyw，避免开机弹 cmd 窗口
    root = _project_root()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)  # 回退 python
    entry = root / "tray_app.pyw"
    return subprocess.list2cmdline([str(pythonw), str(entry)])


def startup_enabled() -> bool:
    """当前是否已写入开机自启项。"""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(value)
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    """写入或删除开机自启项。"""
    if sys.platform != "win32":
        raise OSError("开机自启仅支持 Windows")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
