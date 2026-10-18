# 打包成目录模式 exe（windowed，无需 Python 环境，支持全部子命令），并生成发布 zip。
# 用法：在正常终端（非沙箱）执行：
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# 版本号以 campus_auth/__init__.py 为唯一事实来源
$initFile = Join-Path $PSScriptRoot 'campus_auth\__init__.py'
$version = (Select-String -Path $initFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $version) { Write-Error "无法从 $initFile 读取版本号"; exit 1 }
Write-Host "开始打包 campus-auth v$version"

python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m PyInstaller --noconfirm --clean campus_config.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $PSScriptRoot 'dist\campus-auth\campus-auth.exe'
if (-not (Test-Path $exe)) { Write-Error "打包产物缺失：$exe"; exit 1 }

# 生成发布 zip：散开结构（解压后直接得到 _internal + campus-auth.exe，与历史发布包一致）
$zip = Join-Path $PSScriptRoot "dist\campus-auth-v$version.zip"
if (Test-Path $zip) { Remove-Item -LiteralPath $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    (Join-Path $PSScriptRoot 'dist\campus-auth'),
    $zip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false)
if (-not (Test-Path $zip)) { Write-Error "发布 zip 生成失败：$zip"; exit 1 }

Write-Host ''
Write-Host '打包完成：dist\campus-auth\campus-auth.exe'
Write-Host "发布包：dist\campus-auth-v$version.zip"
Write-Host ''
Write-Host '用法（双击或命令行）：'
Write-Host '  campus-auth.exe tray      系统托盘常驻'
Write-Host '  campus-auth.exe config    打开配置界面'
Write-Host '  campus-auth.exe watch     静默守护循环'
Write-Host '  campus-auth.exe autostart on/off   开关开机自启'
