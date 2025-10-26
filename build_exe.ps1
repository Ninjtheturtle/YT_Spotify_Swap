param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($Clean) {
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }
    if (Test-Path build) { Remove-Item -Recurse -Force build }
}

if (!(Test-Path .venv)) {
    py -3 -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

# Build one-file console executable
pyinstaller --onefile --name yt-spotify-switch --console yt_spotify_auto_switch.py

Write-Host "\nBuild complete. EXE is at: dist\\yt-spotify-switch.exe" -ForegroundColor Green
