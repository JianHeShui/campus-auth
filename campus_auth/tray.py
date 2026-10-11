"""系统托盘：用 Shell_NotifyIcon（ctypes，纯标准库）实现常驻托盘图标。

托盘右键菜单：打开配置 / 开始自动登录 / 退出；左键双击打开配置。
「打开配置」「开始自动登录」用独立进程启动，关闭托盘不影响它们。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

# ---- Win32 常量 ----
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IDI_APPLICATION = 32512

TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

ID_OPEN = 1001
ID_START = 1002
ID_EXIT = 1003

# ---- Win32 结构体 ----
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", POINT),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD), ("guidItem", wintypes.BYTE * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


# ---- Win32 函数 ----
_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_kernel32 = ctypes.windll.kernel32

# 显式声明函数签名：防止句柄/指针被默认 c_int 截断、字符串被错误转换
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
_user32.LoadIconW.restype = wintypes.HICON
# 标准图标 ID 是整数，需经 MAKEINTRESOURCE 转成资源指针
_IDI_APPLICATION = ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR)
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
_user32.AppendMenuW.restype = wintypes.BOOL
_user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, ctypes.c_void_p,
]
_user32.TrackPopupMenu.restype = wintypes.BOOL
_user32.DestroyMenu.argtypes = [wintypes.HMENU]
_user32.DestroyMenu.restype = wintypes.BOOL
_user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = wintypes.BOOL
_user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
_user32.DispatchMessageW.restype = ctypes.c_ssize_t
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def _tool_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_root() -> Path:
    """打包资源目录：frozen 时为 PyInstaller 解压目录(_MEIPASS)，源码为项目根。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _load_tray_icon():
    """加载托盘图标：优先用 tray.ico（白底黑「水」字），回退系统图标。"""
    icon_path = _resource_root() / "tray.ico"
    if icon_path.exists():
        _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT]
        _user32.LoadImageW.restype = wintypes.HANDLE
        # IMAGE_ICON=1, LR_LOADFROMFILE=0x0010
        hicon = _user32.LoadImageW(None, str(icon_path), 1, 0, 0, 0x0010)
        if hicon:
            return hicon
    return _user32.LoadIconW(None, _IDI_APPLICATION)


def _python_command(*args: str) -> list[str]:
    """生成启动子进程的命令（frozen 用 exe，源码用 python -m）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "campus_auth", *args]


def _no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def open_config() -> None:
    subprocess.Popen(_python_command("config"), cwd=str(_tool_root()),
                     creationflags=_no_window_flag())


def start_watch() -> None:
    subprocess.Popen(_python_command("watch", "--startup"), cwd=str(_tool_root()),
                     creationflags=_no_window_flag())


class TrayIcon:
    def __init__(self, tip: str = "校园网认证"):
        self._proc = WNDPROC(self._wnd_proc)  # 保持引用，防 GC
        self._tip = tip
        self._hwnd = self._create_window()

    # ---- 窗口 ----

    def _create_window(self) -> int:
        class_name = "CampusAuthTrayWindow"
        hinst = _kernel32.GetModuleHandleW(None)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        wc.hIcon = _load_tray_icon()
        wc.hIconSm = wc.hIcon
        _user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = _user32.CreateWindowExW(0, class_name, class_name, 0, 0, 0, 0, 0,
                                       None, None, hinst, None)
        if not hwnd:
            raise RuntimeError("无法创建托盘窗口")
        return hwnd

    def _add(self) -> None:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = _load_tray_icon()
        nid.szTip = self._tip
        ok = _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        if not ok:
            err = _kernel32.GetLastError()
            print(f"[警告] 托盘图标添加失败 (错误 {err}: {ctypes.FormatError(err)})", file=sys.stderr)
            print("      若在 Windows 11，请点击任务栏 ^ 箭头查看隐藏图标区。", file=sys.stderr)

    def _delete(self) -> None:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    # ---- 菜单 ----

    def _show_menu(self) -> None:
        menu = _user32.CreatePopupMenu()
        _user32.AppendMenuW(menu, MF_STRING, ID_OPEN, "配置")
        _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "退出")

        pt = POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(self._hwnd)  # 否则菜单点击后不消失
        _user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY, pt.x, pt.y, 0, self._hwnd, None)
        _user32.PostMessageW(self._hwnd, 0, 0, 0)
        _user32.DestroyMenu(menu)

    # ---- 消息回调 ----

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam in (WM_RBUTTONUP,):
                self._show_menu()
            elif lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                open_config()
            return 0
        if msg == WM_COMMAND:
            cmd_id = wparam & 0xFFFF
            if cmd_id == ID_OPEN:
                open_config()
            elif cmd_id == ID_START:
                start_watch()
            elif cmd_id == ID_EXIT:
                self._delete()
                _user32.DestroyWindow(hwnd)
                _user32.PostQuitMessage(0)
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---- 主循环 ----

    def run(self) -> None:
        self._add()
        msg = MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))


def run_tray() -> int:
    tray = TrayIcon()
    tray.run()
    return 0
