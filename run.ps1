# Launches Slot Car Duel from the project venv.
# Usage:  .\run.ps1            (real hardware)
#         .\run.ps1 -Simulate  (built-in track simulator)
param([switch]$Simulate)
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Error "No .venv found - run .\setup_venv.ps1 first"; exit 1 }
$args_ = @("run_app.py")
if ($Simulate) { $args_ += "--simulate" }
& $py @args_
