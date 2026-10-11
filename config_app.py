"""门户配置界面独立入口（供 PyInstaller 打包成 exe）。

用法：python config_app.py [portal.json 路径]
"""
import sys

from campus_auth.config_gui import run_gui


def main() -> int:
    profile_path = sys.argv[1] if len(sys.argv) > 1 else None
    return run_gui(profile_path)


if __name__ == "__main__":
    raise SystemExit(main())
