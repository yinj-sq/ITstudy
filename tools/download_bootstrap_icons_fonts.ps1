$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out_dir = 'C:\Users\Administrator\Desktop\ITstudy V4.0\static\bootstrap-icons\fonts'
if (-not (Test-Path $out_dir)) { New-Item -ItemType Directory -Path $out_dir -Force | Out-Null }

$base = 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts'
$files = @('bootstrap-icons.woff', 'bootstrap-icons.woff2')

foreach ($f in $files) {
    $url = "$base/$f"
    $dest = Join-Path $out_dir $f
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        Write-Output "OK $f  size=$((Get-Item $dest).Length)"
    } catch {
        Write-Output "ERR $f : $($_.Exception.Message)"
    }
}
