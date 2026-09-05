# Служба Windows через NSSM (https://nssm.cc). Запускати з теки service/ від адміністратора:
#   powershell -ExecutionPolicy Bypass -File deploy\nssm-install.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Немає $py — спочатку: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) { throw "nssm не знайдено в PATH (winget install nssm)" }
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
nssm install batman $py "-m batman_service"
nssm set batman AppDirectory $root
nssm set batman AppEnvironmentExtra "BATMAN_CONFIG=$root\config.toml"
nssm set batman AppStdout (Join-Path $root "logs\batman.log")
nssm set batman AppStderr (Join-Path $root "logs\batman.err.log")
nssm set batman AppRotateFiles 1
nssm set batman AppRotateBytes 10485760
nssm set batman Start SERVICE_AUTO_START
nssm start batman
Write-Host "Служба batman встановлена й запущена. Логи: $root\logs"
