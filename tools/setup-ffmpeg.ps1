# Installs a static ffmpeg build as tools\ffmpeg.exe.
#
# Required for the CNMS video download feature, which remuxes the DVR's H.265
# FLV into MP4 on the fly (ffmpeg -c copy). The binary itself is NOT committed
# (145 MB); run this once per server/deploy to fetch it.
#
# Idempotent: does nothing if tools\ffmpeg.exe already exists.
#
#   powershell -ExecutionPolicy Bypass -File tools\setup-ffmpeg.ps1

$ErrorActionPreference = 'Stop'

$dest = Join-Path $PSScriptRoot 'ffmpeg.exe'
if (Test-Path $dest) {
    Write-Host "ffmpeg already present: $dest"
    exit 0
}

$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
$zip = Join-Path $env:TEMP 'ffmpeg-dhfleetview.zip'
$tmp = Join-Path $env:TEMP 'ffmpeg-dhfleetview'

Write-Host "Downloading ffmpeg (static win64 build)..."
Invoke-WebRequest -Uri $url -OutFile $zip

Write-Host "Extracting..."
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path $zip -DestinationPath $tmp -Force

$exe = Get-ChildItem -Path $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if (-not $exe) { throw "ffmpeg.exe not found in the downloaded archive" }
Copy-Item $exe.FullName $dest -Force

Remove-Item -Force $zip
Remove-Item -Recurse -Force $tmp

Write-Host "ffmpeg installed: $dest"
& $dest -version | Select-Object -First 1
