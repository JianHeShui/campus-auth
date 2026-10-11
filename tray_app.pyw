"""托盘无控制台入口（由 pythonw.exe 运行，开机自启时不弹 cmd 窗口）。"""
import sys
from pathlib import Path

# 把项目根加入 sys.path，确保能找到 campus_auth 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from campus_auth.tray import run_tray  # noqa: E402


if __name__ == "__main__":
    run_tray()
