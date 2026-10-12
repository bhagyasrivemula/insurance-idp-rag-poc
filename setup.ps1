# ---------------------------------------------------------------------------
# One-time setup: Python environment + .env file for the OpenAI key.
# Usage (from C:\Demo):   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# ---------------------------------------------------------------------------
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Creating Python virtual environment (.venv)..." -ForegroundColor Cyan
if (-not (Test-Path .\.venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
# RAGAS without its optional scikit-network dependency (no Python 3.14 build; see requirements.txt)
.\.venv\Scripts\python.exe -m pip install --quiet --no-deps "ragas==0.4.3"

if (-not (Test-Path .\.env)) {
    Copy-Item .\.env.example .\.env
    Write-Host "Created .env - open it and paste your OpenAI API key." -ForegroundColor Yellow
}

Write-Host "Setup complete. Next: add your key to .env, then .\ingest.ps1 and .\run.ps1" -ForegroundColor Green
