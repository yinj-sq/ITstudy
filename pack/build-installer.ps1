$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")

$makensisCommand = Get-Command "makensis.exe" -ErrorAction SilentlyContinue
$candidates = @()
if ($makensisCommand) {
    $candidates += $makensisCommand.Source
}
$candidates += Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"
$candidates += Join-Path $env:ProgramFiles "NSIS\makensis.exe"

$makensis = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $makensis) {
    throw "makensis.exe was not found. Install NSIS 3.x or add the NSIS directory to PATH."
}

Write-Host "Repo root: $RepoRoot"
Write-Host "NSIS: $makensis"

# ── 版本单源化：从 installer.nsi 的 PRODUCT_VERSION 提取（此前两处硬编码
#    v6.1.0，升版只改 nsi 会与本脚本回显/输出检测漂移）──
$nsiPath = Join-Path $ScriptDir "installer.nsi"
$versionMatch = Select-String -Path $nsiPath -Pattern '!define PRODUCT_VERSION "(.+?)"' |
    Select-Object -First 1
if (-not $versionMatch) { throw "PRODUCT_VERSION not found in installer.nsi" }
$Version = $versionMatch.Matches[0].Groups[1].Value
Write-Host "Version: $Version (from installer.nsi)"

# ── 离线 wheel 包（断网机房安装）：与 requirements.txt 同步下载到 pack\wheels ──
# 安装器检测到同目录 wheels\ 时走 --no-index 离线安装；缺失则回退在线镜像。
# 必须带 -c constraints.txt：与容器镜像使用同一组钉死版本，避免构建机在线解析
# 到比已验证版本更新的依赖（2026-09-13 flask-caching 2.5 装机即崩即此类漂移）。
# --only-binary=:all: 保证下载的是 wheel（离线安装机不需要编译器）。
Write-Host "Downloading offline wheels to pack\wheels ..." -ForegroundColor Cyan
Write-Host "注意：二进制 wheel（psycopg2/cryptography/pywin32 等）与构建机 Python 小版本绑定，" -ForegroundColor Yellow
Write-Host "目标机须使用相同小版本的 Python（当前构建机：$(python -V)）。" -ForegroundColor Yellow
python -m pip download -r (Join-Path $RepoRoot "requirements.txt") -c (Join-Path $RepoRoot "constraints.txt") --only-binary=:all: -d (Join-Path $ScriptDir "wheels")
if ($LASTEXITCODE -ne 0) {
    Write-Warning "wheel 下载失败。联网安装不受影响（安装器回退在线镜像）；断网环境部署前必须补齐 pack\wheels。"
}

# 清理与 constraints 版本不一致的旧 wheel：pip download 不会删除旧版本，
# 升级依赖后会同时留下新旧两份，离线目录无法保证可复现，且
# tests/test_review_fixes_0925.py 的 wheels/constraints 一致性检查会失败。
$pins = @{}
Get-Content (Join-Path $RepoRoot "constraints.txt") -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z0-9_.-]+)==([^\s;]+)') {
        $pins[$matches[1].ToLower().Replace('_', '-')] = $matches[2]
    }
}
Get-ChildItem (Join-Path $ScriptDir "wheels") -Filter *.whl | ForEach-Object {
    $parts = $_.Name.Split('-')
    if ($parts.Count -lt 2) { return }
    $name = $parts[0].ToLower().Replace('_', '-')
    if ($pins.ContainsKey($name) -and $pins[$name] -ne $parts[1]) {
        Write-Host "Removing stale wheel: $($_.Name)"
        Remove-Item $_.FullName -Force
    }
}

Write-Host "Building ITstudy v$Version installer..."

# ── 打包前校准预压缩副本：nginx gzip_static 只要 .gz 存在就直接下发，
#    源文件改过而 .gz 未重建时浏览器拿到的是旧脚本（2026-09-25 实测 5 个陈旧）──
Write-Host "Refreshing precompressed .gz copies ..." -ForegroundColor Cyan
python -X utf8 (Join-Path $RepoRoot "tools\precompress_static.py") --refresh-only
if ($LASTEXITCODE -ne 0) {
    throw "precompress_static.py failed with exit code $LASTEXITCODE"
}

Push-Location $ScriptDir
try {
    & $makensis "/INPUTCHARSET" "UTF8" "installer.nsi"
    if ($LASTEXITCODE -ne 0) {
        throw "makensis failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$output = Join-Path $ScriptDir "ITstudy-v$Version-Setup.exe"
if (Test-Path $output) {
    Write-Host "Installer created: $output"
}
else {
    Write-Host "NSIS finished. Expected output: $output"
}
