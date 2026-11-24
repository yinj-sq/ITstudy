$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out_dir = 'C:\Users\Administrator\Desktop\ITstudy V4.0\static\xlsx'
if (-not (Test-Path $out_dir)) { New-Item -ItemType Directory -Path $out_dir -Force | Out-Null }

$url = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js'
$dest = Join-Path $out_dir 'xlsx.full.min.js'

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Output "OK xlsx.full.min.js  size=$((Get-Item $dest).Length)"
} catch {
    Write-Output "ERR: $($_.Exception.Message)"
    exit 1
}
