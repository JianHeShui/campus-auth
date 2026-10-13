# -*- mode: python ; coding: utf-8 -*-
"""打包成目录模式（onedir），避免单文件解压临时目录被杀软拦截。

打包命令（在正常终端，非沙箱）：
    pip install pyinstaller
    pyinstaller --noconfirm --clean campus_config.spec
产物：dist/campus-auth/ 目录（campus-auth.exe + _internal/）
"""
from PyInstaller.utils.hooks import collect_all

# 显式收集 pycryptodome（Crypto）的模块 + C 扩展（.pyd），否则 .pyd 不会被打包
_crypto_datas, _crypto_binaries, _crypto_hidden = collect_all("Crypto")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=_crypto_binaries,
    datas=[("tray.ico", ".")] + _crypto_datas,  # 打进 _internal，托盘运行时从 _MEIPASS 加载
    hiddenimports=[
        "campus_auth.config_gui",
        "campus_auth.tray",
        "campus_auth.startup",
        "campus_auth.detect",
        "campus_auth.shortcut",
        "campus_auth.cas",
        "campus_auth.crypto",
    ] + _crypto_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# onedir：exe 只含引导与脚本，依赖放到 _internal 目录（不打包进 exe，无需解压临时目录）
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="campus-auth",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed：无控制台窗口
    icon="tray.ico",        # exe 文件图标（白底黑「水」字）
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="campus-auth",
)
