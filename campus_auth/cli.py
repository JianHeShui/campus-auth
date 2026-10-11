"""命令行入口：单次登录 / 状态检查 / 配置 / 静默守护。"""
from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .client import AuthError, Client, Credentials
from .config import ConfigError, load_credentials, save_credentials
from .network import NetworkAdapter, enumerate_interfaces, pick_adapter
from .portal import ProfileError, load_profile
from .state import AuthState, RetryPolicy


def _build_client(args: argparse.Namespace) -> Client:
    profile = load_profile(getattr(args, "portal", None))
    adapters = enumerate_interfaces()
    adapter: NetworkAdapter | None = pick_adapter(adapters, prefer_ethernet=True)
    if getattr(args, "adapter", None):
        adapter = next((a for a in adapters if a.ipv4 == args.adapter or a.mac == args.adapter), None)
    return Client(profile, adapter=adapter, timeout=getattr(args, "timeout", 10))


def _describe_adapter(adapter: NetworkAdapter | None) -> str:
    if adapter is None:
        return "未找到可用物理网卡"
    kind = "以太网" if adapter.is_ethernet else "Wi-Fi"
    return f"{kind} {adapter.ipv4} ({adapter.mac})"


def _print_result(result, adapter: NetworkAdapter | None, quiet: bool) -> int:
    state_icons = {
        AuthState.ONLINE: "✓ 在线",
        AuthState.PENDING: "? 待确认",
        AuthState.OFFLINE: "✗ 离线",
        AuthState.ERROR: "✗ 失败",
    }
    if quiet:
        print(result.state.value)
    else:
        print(f"{state_icons[result.state]}  [{_describe_adapter(adapter)}]  {result.message}")
    return 0 if result.state == AuthState.ONLINE else 1


def cmd_check(args: argparse.Namespace) -> int:
    client = _build_client(args)
    try:
        session_id = client.acquire_session()
    except AuthError as exc:
        print(f"探测失败: {exc}", file=sys.stderr)
        return 2
    if session_id and client.check_online(session_id):
        return _print_result(_online_result(), client.adapter, args.quiet)
    if client._internet_ok():
        return _print_result(_online_result(), client.adapter, args.quiet)
    return _print_result(_pending_result(), client.adapter, args.quiet)


def _online_result():
    from .client import AuthResult
    return AuthResult(AuthState.ONLINE, "已联网")


def _pending_result():
    from .client import AuthResult
    return AuthResult(AuthState.PENDING, "未联网或待确认")


def cmd_login(args: argparse.Namespace) -> int:
    client = _build_client(args)
    try:
        credentials = load_credentials()
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    try:
        result = client.authenticate(credentials)
    except AuthError as exc:
        print(f"认证失败: {credentials.redact(str(exc))}", file=sys.stderr)
        return 1
    return _print_result(result, client.adapter, args.quiet)


def cmd_configure(args: argparse.Namespace) -> int:
    username = args.username or input("校园网账号: ").strip()
    import getpass
    password = args.password if args.password is not None else getpass.getpass("校园网密码: ")
    service = args.service or input("服务/运营商（可空）: ").strip()
    if not username or not password:
        print("账号和密码不能为空", file=sys.stderr)
        return 2
    path = save_credentials(Credentials(username, password, service))
    print(f"凭据已保存到 {path}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """静默守护：按退避策略周期重试。"""
    # 开机自启模式：先延时，等网卡与网络就绪
    if getattr(args, "startup", False) and getattr(args, "delay", 0) > 0:
        time.sleep(args.delay)

    client = _build_client(args)
    try:
        credentials = load_credentials()
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    policy = RetryPolicy(cap=args.max_interval)
    interval = args.interval
    while True:
        if not policy.should_try():
            time.sleep(1)
            continue
        try:
            result = client.authenticate(credentials)
        except AuthError as exc:
            result = None
            if not args.quiet:
                print(f"[{time.strftime('%H:%M:%S')}] 错误: {credentials.redact(str(exc))}", flush=True)
        if result is not None:
            if result.state == AuthState.ONLINE:
                policy.on_success()
                if not args.quiet:
                    print(f"[{time.strftime('%H:%M:%S')}] 已联网", flush=True)
            elif result.state == AuthState.ERROR:
                if not args.quiet:
                    print(f"[{time.strftime('%H:%M:%S')}] {result.message}", flush=True)
                # 明确失败（账号密码错等）不无限重试，等待人工介入
                break
            elif result.state == AuthState.PENDING:
                policy.on_pending()
            else:
                policy.on_failure()
        time.sleep(interval)
    return 1


def cmd_autostart(args: argparse.Namespace) -> int:
    """查询或设置开机自启。"""
    from .startup import set_startup, startup_enabled
    state = getattr(args, "state", None)
    if state == "on":
        try:
            set_startup(True)
        except OSError as exc:
            print(f"启用失败: {exc}", file=sys.stderr)
            return 1
        print("已启用开机自启（登录 Windows 后自动连接）")
    elif state == "off":
        try:
            set_startup(False)
        except OSError as exc:
            print(f"禁用失败: {exc}", file=sys.stderr)
            return 1
        print("已禁用开机自启")
    else:
        print("开机自启：已启用" if startup_enabled() else "开机自启：未启用")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="campus-auth", description="锐捷 SAM+ 校园网自动认证（接口直连）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--portal", help="portal.json 路径（默认用内置画像）")
    parser.add_argument("--adapter", help="指定网卡（IPv4 或 MAC）")
    parser.add_argument("--timeout", type=float, default=10, help="单次请求超时秒数")
    parser.add_argument("-q", "--quiet", action="store_true", help="仅输出状态值")

    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("check", help="只检查是否已联网").set_defaults(func=cmd_check)

    p_login = sub.add_parser("login", help="执行一次认证")
    p_login.set_defaults(func=cmd_login)

    p_conf = sub.add_parser("configure", help="保存账号密码")
    p_conf.add_argument("--username")
    p_conf.add_argument("--password")
    p_conf.add_argument("--service", help="服务/运营商（可空）")
    p_conf.set_defaults(func=cmd_configure)

    p_watch = sub.add_parser("watch", help="静默守护循环")
    p_watch.add_argument("--interval", type=float, default=15, help="轮询间隔秒数")
    p_watch.add_argument("--max-interval", type=int, default=300, help="退避上限秒数")
    p_watch.add_argument("--startup", action="store_true", help="开机自启模式（配合 --delay 延时启动）")
    p_watch.add_argument("--delay", type=float, default=10, help="开机自启延时秒数（等网络就绪）")
    p_watch.set_defaults(func=cmd_watch)

    p_auto = sub.add_parser("autostart", help="查询或设置开机自启")
    p_auto.add_argument("state", nargs="?", choices=("on", "off"), help="on 启用 / off 禁用 / 不填则查询")
    p_auto.set_defaults(func=cmd_autostart)

    p_tray = sub.add_parser("tray", help="以系统托盘图标常驻运行")
    p_tray.set_defaults(func=cmd_tray)

    p_conf = sub.add_parser("config", help="打开门户配置界面（图形界面）")
    p_conf.add_argument("--profile", help="portal.json 路径（保存目标）")
    p_conf.set_defaults(func=cmd_config)

    return parser


def cmd_tray(args: argparse.Namespace) -> int:
    """以系统托盘图标常驻运行。"""
    from .tray import run_tray
    return run_tray()


def cmd_config(args: argparse.Namespace) -> int:
    """打开 tkinter 配置界面。"""
    from .config_gui import run_gui
    return run_gui(getattr(args, "profile", None))


def main(argv: list[str] | None = None) -> int:
    _ensure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        # 双击 exe：首次启动时创建桌面快捷方式 + 弹出配置界面 + 启动托盘
        from .shortcut import ensure_desktop_shortcut
        ensure_desktop_shortcut()
        import subprocess
        from .tray import _python_command, _tool_root, run_tray
        cmd = _python_command("config")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, cwd=str(_tool_root()), creationflags=creationflags)
        return run_tray()
    try:
        return args.func(args)
    except ProfileError as exc:
        print(f"画像错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _ensure_stdio() -> None:
    """windowed 打包（console=False）下 stdout/stderr 为 None，print 会抛异常；
    这里重定向到 devnull，让打印静默丢弃而非崩溃。"""
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
