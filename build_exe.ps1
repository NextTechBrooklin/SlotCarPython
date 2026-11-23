# Builds a single-file Windows executable into .\dist using PyInstaller.
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements-dev.txt
& $py tools\generate_assets.py
& $py -m PyInstaller --noconfirm SlotCarDuel.spec
Write-Host "Built dist\SlotCarDuel.exe" -ForegroundColor Green
