# -*- mode: python ; coding: utf-8 -*-
"""打包成单文件版（onefile），便携分发。

与 campus_config.spec（目录版）的区别：
- EXE 直接包含 a.binaries、a.datas，不再生成 COLLECT 目录；
- 运行时自解压到临时目录，启动比目录版慢，且易被杀软误报，
  因此正式发布以目录版（campus-config.spec）为主，单文件版仅作便携补充。

构建命令（一般由 build.ps1 调用，不建议手工执行）：
    python -m PyInstaller --noconfirm --clean --distpath dist\\onefile campus_config_onefile.spec
产物：dist\\onefile\\campus-auth.exe
发布命名：build.ps1 会把它复制为 dist\\campus-auth-v<版本>-单文件版.exe
（spec 内 name 保持 campus-auth，版本号由 build.ps1 从 campus_auth/__init__.py 读取后拼入发布名，
 避免 spec 与代码两处维护版本号）。
"""
from PyInstaller.utils.hooks import collect_all

# 显式收集 pycryptodome（Crypto）的模块 + C 扩展（.pyd），否则 .pyd 不会被打包
_crypto_datas, _crypto_binaries, _crypto_hidden = collect_all("Crypto")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=_crypto_binaries,
    datas=[("tray.ico", ".")] + _crypto_datas,  # 打进 exe，运行时从 _MEIPASS 加载
    hiddenimports=[
        "campus_auth.config_gui",
        "campus_auth.tray",
        "campus_auth.startup",
        "campus_auth.detect",
        "campus_auth.shortcut",
        "campus_auth.cas",
        "campus_auth.crypto",
        "campus_auth.daemon",
        "campus_auth.logutil",
    ] + _crypto_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# onefile：binaries/datas 全部内嵌进 exe（不加 exclude_binaries，也不建 COLLECT）
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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
