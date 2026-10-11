# 打包成单个 exe（windowed，无需 Python 环境，支持全部子命令）。
# 用法：在正常终端（非沙箱）执行：
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m PyInstaller --noconfirm --clean campus_config.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ''
Write-Host '打包完成：dist\campus-auth.exe'
Write-Host ''
Write-Host '用法（双击或命令行）：'
Write-Host '  campus-auth.exe tray      系统托盘常驻'
Write-Host '  campus-auth.exe config    打开配置界面'
Write-Host '  campus-auth.exe watch     静默守护循环'
Write-Host '  campus-auth.exe autostart on/off   开关开机自启'
