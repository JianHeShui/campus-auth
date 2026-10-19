# campus-auth 发布构建：目录版 + 单文件版 + 发布 zip + SHA256SUMS
# 用法：在正常终端（非沙箱）执行：
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
# 可选开关：
#   -SkipDeps     跳过 pip install（已自备 PyInstaller/pycryptodome 时用，例如 PYTHONPATH 指向 .pylibs）
#   -SkipOneFile  只构建目录版，跳过单文件版
# 产物（dist\ 下）：
#   campus-auth\campus-auth.exe                目录版（发布 zip 的内容）
#   campus-auth-v<版本>.zip                    发布包：_internal\ + campus-auth.exe + LICENSE/README.md/portal.example.json
#   campus-auth-v<版本>-单文件版.exe           单文件便携版
#   SHA256SUMS.txt                             zip / 单文件版 / 目录版 exe 的 SHA256（UTF-8 BOM，Windows PowerShell 可直接校验）
[CmdletBinding()]
param(
    [switch]$SkipDeps,    # 跳过依赖安装（本机已备好构建依赖时使用）
    [switch]$SkipOneFile  # 跳过单文件版构建
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Fail {
    param([string]$Message, [int]$Code = 1)
    Write-Host "错误：$Message" -ForegroundColor Red
    exit $Code
}

function Get-Sha256 {
    param([string]$FilePath)
    return (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
}

$root = $PSScriptRoot

# ---------- 0. 版本号以 campus_auth/__init__.py 为唯一事实来源 ----------
$initFile = Join-Path $root 'campus_auth\__init__.py'
$versionMatch = Select-String -LiteralPath $initFile -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $versionMatch) { Fail "无法从 $initFile 读取版本号" }
$version = $versionMatch.Matches[0].Groups[1].Value
Write-Host "开始打包 campus-auth v$version"

# ---------- 1. 构建依赖：按 requirements-build.txt 钉死的版本安装 ----------
$reqFile = Join-Path $root 'requirements-build.txt'
if (-not (Test-Path -LiteralPath $reqFile -PathType Leaf)) { Fail "缺少构建依赖清单：$reqFile" }
if ($SkipDeps) {
    Write-Host '已跳过依赖安装（-SkipDeps）：请确认当前 Python 环境已有 PyInstaller 6.22.3 / pycryptodome 3.24.1'
} else {
    Write-Host '安装构建依赖：python -m pip install -r requirements-build.txt'
    python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { Fail "构建依赖安装失败（pip exit=$LASTEXITCODE）" }
}

# ---------- 2. 目录版（onedir） ----------
Write-Host '构建目录版（onedir）...'
python -m PyInstaller --noconfirm --clean campus_config.spec
if ($LASTEXITCODE -ne 0) { Fail "目录版构建失败（PyInstaller exit=$LASTEXITCODE）" }

$distDir = Join-Path $root 'dist\campus-auth'
$exe = Join-Path $distDir 'campus-auth.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Fail "打包产物缺失：$exe" }

# ---------- 3. 发布合规文件：LICENSE / README.md / portal.example.json ----------
$releaseFiles = @('LICENSE', 'README.md', 'portal.example.json')
foreach ($name in $releaseFiles) {
    $source = Join-Path $root $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Fail "发布必需文件缺失：$source" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $distDir $name) -Force
    Write-Host "已加入发布文件：$name"
}

# ---------- 4. 发布 zip（散开结构：解压后顶层为 _internal\ + campus-auth.exe + 三个合规文件） ----------
$zip = Join-Path $root "dist\campus-auth-v$version.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $distDir,
    $zip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false)
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { Fail "发布 zip 生成失败：$zip" }

# 校验 zip 布局：顶层 campus-auth.exe + _internal\ + 三个合规文件
$zipArchive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $entryNames = @($zipArchive.Entries | ForEach-Object { $_.FullName -replace '\\', '/' })
} finally {
    $zipArchive.Dispose()
}
foreach ($required in @('campus-auth.exe', 'LICENSE', 'README.md', 'portal.example.json')) {
    if ($entryNames -notcontains $required) { Fail "发布 zip 缺少文件 $required：$zip" }
}
if (-not ($entryNames | Where-Object { $_ -like '_internal/*' })) { Fail "发布 zip 缺少 _internal\ 目录：$zip" }
Write-Host "发布包：dist\campus-auth-v$version.zip"

# ---------- 5. 单文件版（onefile） ----------
$onefileExe = $null
if ($SkipOneFile) {
    Write-Host '已跳过单文件版构建（-SkipOneFile）'
} else {
    Write-Host '构建单文件版（onefile）...'
    $onefileWork = Join-Path $root 'build\onefile'
    $onefileDist = Join-Path $root 'dist\onefile'
    python -m PyInstaller --noconfirm --clean --workpath $onefileWork --distpath $onefileDist campus_config_onefile.spec
    if ($LASTEXITCODE -ne 0) { Fail "单文件版构建失败（PyInstaller exit=$LASTEXITCODE）；可加 -SkipOneFile 只出目录版" }
    $onefileBuilt = Join-Path $onefileDist 'campus-auth.exe'
    if (-not (Test-Path -LiteralPath $onefileBuilt -PathType Leaf)) { Fail "单文件版产物缺失：$onefileBuilt" }
    $onefileExe = Join-Path $root "dist\campus-auth-v$version-单文件版.exe"
    Copy-Item -LiteralPath $onefileBuilt -Destination $onefileExe -Force
    if (-not (Test-Path -LiteralPath $onefileExe -PathType Leaf)) { Fail "单文件版复制失败：$onefileExe" }
    Write-Host "单文件版：dist\campus-auth-v$version-单文件版.exe"
}

# ---------- 6. SHA256SUMS.txt（小写哈希 + 两个空格 + 相对 dist 的路径） ----------
# 必须写 UTF-8 BOM：Windows PowerShell 5.1 的 Get-Content 对无 BOM 文件按 ANSI 解码，
# 会把「单文件版」等中文文件名读成乱码导致校验失败；带 BOM 后可直接用 Get-Content 校验。
$sumsFile = Join-Path $root 'dist\SHA256SUMS.txt'
$sumLines = @()
$sumLines += "$(Get-Sha256 $zip)  campus-auth-v$version.zip"
if ($onefileExe) {
    $sumLines += "$(Get-Sha256 $onefileExe)  campus-auth-v$version-单文件版.exe"
}
$sumLines += "$(Get-Sha256 $exe)  campus-auth/campus-auth.exe"
$utf8Bom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $true
[System.IO.File]::WriteAllText($sumsFile, (($sumLines -join "`r`n") + "`r`n"), $utf8Bom)
Write-Host '校验和：dist\SHA256SUMS.txt（UTF-8 BOM）'

# ---------- 7. 汇总 ----------
Write-Host ''
Write-Host '打包完成：'
Write-Host '  目录版    dist\campus-auth\campus-auth.exe'
Write-Host "  发布包    dist\campus-auth-v$version.zip"
if ($onefileExe) { Write-Host "  单文件版  dist\campus-auth-v$version-单文件版.exe" }
Write-Host '  校验和    dist\SHA256SUMS.txt'
Write-Host ''
Write-Host '用法（双击或命令行）：'
Write-Host '  campus-auth.exe tray      系统托盘常驻（自动保护）'
Write-Host '  campus-auth.exe config    打开配置界面'
Write-Host '  campus-auth.exe watch     自动保护守护循环（持续运行，需手动停止）'
Write-Host '  campus-auth.exe login     单次登录（只认证一次，不常驻）'
Write-Host '  campus-auth.exe autostart on/off   开关开机自启（开机后一直运行并自动保护）'
