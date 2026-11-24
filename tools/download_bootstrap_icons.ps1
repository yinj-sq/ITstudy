$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out_dir = 'C:\Users\Administrator\Desktop\ITstudy V4.0\static\bootstrap-icons'
if (-not (Test-Path $out_dir)) { New-Item -ItemType Directory -Path $out_dir -Force | Out-Null }

$css_url = 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css'
$css_file = Join-Path $out_dir 'bootstrap-icons.min.css'

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $css_url -OutFile $css_file -UseBasicParsing
    Write-Output "OK CSS  size=$((Get-Item $css_file).Length)"
} catch {
    Write-Output "CSS ERR: $($_.Exception.Message)"
    exit 1
}
