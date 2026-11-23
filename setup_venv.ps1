# Creates .venv in the project folder and installs all dependencies.
# Usage:  powershell -ExecutionPolicy Bypass -File .\setup_venv.ps1 [-Dev]
param([switch]$Dev)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment in .venv ..." -ForegroundColor Cyan
    py -3 -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
if ($Dev) { & $py -m pip install -r requirements-dev.txt } else { & $py -m pip install -r requirements.txt }
& $py tools\generate_assets.py
Write-Host "Done. Start the app with .\run.ps1  (or .\run.ps1 -Simulate)" -ForegroundColor Green
