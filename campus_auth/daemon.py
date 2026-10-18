"""后台守护进程管理：启动 / 停止 / 状态查询。

守护循环（watch）统一由独立进程运行，避免 GUI 线程版"关窗即死"的假后台：
- 命名互斥体 ``CampusAuthWatch`` 保证全局单实例（CLI / 托盘 / 配置界面共用）；
- ``~/.campus-auth/watch.pid`` 记录进程号，供托盘与配置界面停止它；
- 仅 Windows（项目本身仅支持 Windows）。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

MUTEX_NAME = "CampusAuthWatch"
PID_FILE = Path.home() / ".campus-auth" / "watch.pid"

_SYNCHRONIZE = 0x00100000
_CREATE_NO_WINDOW = 0x08000000


def _is_windows() -> bool:
    return sys.platform == "win32"


def _kernel32():
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def is_running() -> bool:
    """守护进程是否在运行：通过命名互斥体判断（跨进程可靠，不依赖 PID 文件）。"""
    if not _is_windows():
        return False
    try:
        kernel32 = _kernel32()
        handle = kernel32.OpenMutexW(_SYNCHRONIZE, False, MUTEX_NAME)
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def write_pid_file() -> None:
    """记录当前守护进程号（写失败静默）。"""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def read_pid_file() -> int | None:
    """读取守护进程号；文件缺失或非法返回 None。"""
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def clear_pid_file() -> None:
    """删除 PID 文件（失败静默）。"""
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _tool_root() -> Path:
    """工具目录：打包后为 exe 所在目录，源码运行为项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _python_command(*args: str) -> list[str]:
    """生成启动子进程的命令（frozen 用 exe，源码用 python -m）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "campus_auth", *args]


# start_status() 的返回值：区分"已在运行 / 本次新启动 / 失败"，
# 供 GUI 与托盘正确提示，避免把"旧进程没停掉"误报成"新配置已生效"。
ALREADY_RUNNING = "already_running"
STARTED = "started"
FAILED = "failed"


def start_status(*extra_args: str, wait: float = 3.0) -> str:
    """启动独立守护进程并返回三态状态（ALREADY_RUNNING / STARTED / FAILED）。

    返回 STARTED 表示互斥体已由新拉起的进程持有；FAILED 表示启动失败
    （非 Windows、Popen 异常或等待超时仍未拿到互斥体）。
    """
    if is_running():
        return ALREADY_RUNNING
    if not _is_windows():
        return FAILED
    try:
        subprocess.Popen(
            _python_command("watch", *extra_args),
            cwd=str(_tool_root()),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW),
        )
    except OSError:
        return FAILED
    # 等待子进程拿到单实例互斥体（启动失败时也不会无限等）
    deadline = time.monotonic() + max(0.2, wait)
    while time.monotonic() < deadline:
        if is_running():
            return STARTED
        time.sleep(0.1)
    return STARTED if is_running() else FAILED


def start(*extra_args: str, wait: float = 3.0) -> bool:
    """启动独立守护进程；已在运行则直接返回 True（兼容旧调用）。

    新代码请用 start_status() 区分三种结果，以便给出准确提示。
    """
    return start_status(*extra_args, wait=wait) != FAILED


def stop(wait: float = 3.0) -> bool:
    """停止守护进程：按 PID 文件结束进程，并确认互斥体已释放。

    返回 True 表示本次确实停止了一个运行中的守护进程。
    """
    if not is_running():
        clear_pid_file()
        return False
    pid = read_pid_file()
    if pid is None:
        return False  # 互斥体在但拿不到 PID（旧版本进程），无法安全结束
    try:
        os.kill(pid, 15)  # Windows 上等价于 TerminateProcess
    except OSError:
        clear_pid_file()
        return False
    deadline = time.monotonic() + max(0.2, wait)
    while time.monotonic() < deadline:
        if not is_running():
            clear_pid_file()
            return True
        time.sleep(0.1)
    if not is_running():
        clear_pid_file()
        return True
    return False
