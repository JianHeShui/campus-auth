"""系统托盘：用 Shell_NotifyIcon（ctypes，纯标准库）实现常驻托盘图标。

托盘右键菜单：状态（保护中/未保护）/ 配置 / 开始保护 / 停止保护 / 退出；左键双击打开配置。
悬浮提示（tooltip）实时显示当前保护状态，每 5 秒同步一次；
「开始保护」在已保护时会先停止再启动（重启守护进程，让新配置生效）；
退出托盘会一并停止守护进程。
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
WM_TIMER = 0x0113
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IDI_APPLICATION = 32512

TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

MF_STRING = 0x0000
MF_GRAYED = 0x0001
MF_SEPARATOR = 0x0800

ID_STATUS = 1000
ID_OPEN = 1001
ID_START = 1002
ID_EXIT = 1003
ID_STOP = 1004

TIMER_ID = 1
STATUS_POLL_MS = 5000

MB_OK = 0x0000
MB_ICONWARNING = 0x0030
MB_ICONINFORMATION = 0x0040

PROTECTED_TEXT = "保护中"
UNPROTECTED_TEXT = "未保护"


def _status_text(protected: bool) -> str:
    """保护状态文案（托盘菜单与悬浮提示共用）。"""
    return PROTECTED_TEXT if protected else UNPROTECTED_TEXT


def _tray_tip(protected: bool) -> str:
    """托盘悬浮提示：显示当前是否处于保护状态。"""
    return f"校园网自动保护：{_status_text(protected)}"

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
_user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
_user32.MessageBoxW.restype = ctypes.c_int
_user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
_user32.SetTimer.restype = ctypes.c_size_t
_user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
_user32.KillTimer.restype = wintypes.BOOL


def _safe_print(msg: str) -> None:
    """windowed（pythonw / frozen）下 sys.stderr 可能为 None，打印失败静默。"""
    try:
        print(msg, file=sys.stderr)
    except Exception:
        pass


def _notify(title: str, text: str, icon: int = MB_ICONINFORMATION) -> None:
    """弹系统消息框（托盘菜单操作的反馈），失败静默。"""
    try:
        _user32.MessageBoxW(None, text, title, MB_OK | icon)
    except Exception:
        pass


def _tool_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_root() -> Path:
    """打包资源目录：frozen 时为 PyInstaller 解压目录(_MEIPASS)，源码为项目根。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _icon_candidates() -> list[Path]:
    """图标候选：打包 _MEIPASS / 项目根（源码） / 包内（pip 安装）。"""
    return [
        _resource_root() / "tray.ico",
        Path(__file__).resolve().parent / "tray.ico",
    ]


def _load_tray_icon():
    """加载托盘图标：优先用 tray.ico（白底黑「水」字），回退系统图标。"""
    _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.LoadImageW.restype = wintypes.HANDLE
    for icon_path in _icon_candidates():
        if not icon_path.exists():
            continue
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


class TrayIcon:
    def __init__(self, tip: str | None = None):
        self._proc = WNDPROC(self._wnd_proc)  # 保持引用，防 GC
        self._tip = tip or _tray_tip(False)
        self._nid: NOTIFYICONDATAW | None = None
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
        self._nid = nid
        ok = _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        if not ok:
            err = _kernel32.GetLastError()
            _safe_print(f"[警告] 托盘图标添加失败 (错误 {err}: {ctypes.FormatError(err)})")
            _safe_print("      若在 Windows 11，请点击任务栏 ^ 箭头查看隐藏图标区。")

    def _delete(self) -> None:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    # ---- 保护状态 ----

    def _is_protected(self) -> bool:
        """当前是否处于保护状态（守护进程是否在运行）。"""
        try:
            from .daemon import is_running
            return is_running()
        except Exception:
            return False

    def _update_status(self) -> None:
        """把保护状态同步到托盘悬浮提示（仅在状态变化时刷新）。"""
        tip = _tray_tip(self._is_protected())
        if tip == self._tip:
            return
        self._tip = tip
        if self._nid is None:
            return
        self._nid.szTip = tip
        self._nid.uFlags = NIF_TIP
        try:
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass

    # ---- 菜单 ----

    def _show_menu(self) -> None:
        self._update_status()
        protected = self._is_protected()
        menu = _user32.CreatePopupMenu()
        # 首行显示当前状态（灰色不可点），让用户一眼看到是否处于保护中
        _user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, ID_STATUS,
                            f"状态：{_status_text(protected)}")
        _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, MF_STRING, ID_OPEN, "配置")
        _user32.AppendMenuW(menu, MF_STRING, ID_START,
                            "重新开始保护" if protected else "开始保护")
        _user32.AppendMenuW(menu, MF_STRING, ID_STOP, "停止保护")
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
        if msg == WM_TIMER and wparam == TIMER_ID:
            self._update_status()
            return 0
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
                from .daemon import is_running, start, stop
                was_running = is_running()
                if was_running:
                    stop()  # 已在保护中：先停止再启动，等同"重启保护"
                if start():
                    self._update_status()
                    if was_running:
                        _notify("自动保护", "保护已重新启动（新配置已生效）。")
                    else:
                        _notify("自动保护", "已开始保护（后台守护进程运行中）。")
                else:
                    _notify("自动保护",
                            "启动失败。\n请先点「配置」填写门户信息并保存账号密码。", MB_ICONWARNING)
            elif cmd_id == ID_STOP:
                from .daemon import is_running, stop
                if not is_running():
                    _notify("自动保护", "当前未处于保护状态。")
                elif stop():
                    self._update_status()
                    _notify("自动保护", "已停止保护。")
                else:
                    _notify("自动保护", "停止失败，请稍后重试。", MB_ICONWARNING)
            elif cmd_id == ID_EXIT:
                from .daemon import stop as daemon_stop
                daemon_stop()  # 退出托盘时一并结束守护，避免残留后台进程
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
        self._update_status()
        # 每 5 秒同步一次保护状态到 tooltip（守护进程可能由配置界面/命令行启动或停止）
        _user32.SetTimer(self._hwnd, TIMER_ID, STATUS_POLL_MS, None)
        msg = MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _user32.KillTimer(self._hwnd, TIMER_ID)


_TRAY_MUTEX_NAME = "CampusAuthTray"
_TRAY_MUTEX_HANDLE = None


def _acquire_tray_single_instance() -> bool:
    """托盘单实例：返回 True 表示本次是首个托盘实例。"""
    global _TRAY_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, _TRAY_MUTEX_NAME)
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _TRAY_MUTEX_HANDLE = handle
    return True


def run_tray() -> int:
    # 单实例：已有托盘在运行则直接退出，避免多次双击产生重复进程
    if not _acquire_tray_single_instance():
        return 0
    # 已配置账号密码时自动开始守护循环（独立进程；已在运行则不会重复启动）
    try:
        from .config import load_credentials
        from .daemon import start
        load_credentials()
        start()
    except Exception:
        pass  # 未配置凭据或启动失败则静默跳过，等用户手动开始
    tray = TrayIcon()
    tray.run()
    return 0
