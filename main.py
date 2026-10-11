"""程序主入口（供 PyInstaller 打包成单个 exe）。

打包后用法：campus-auth.exe <子命令>
  config      打开配置界面
  tray        系统托盘常驻
  watch       静默守护循环
  check/login/configure/autostart  其他命令
"""
from campus_auth.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
