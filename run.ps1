# ---------------------------------------------------------------------------
# Start InsureAssist and open it in the browser.
# Usage:  .\run.ps1      then visit http://127.0.0.1:8000
# ---------------------------------------------------------------------------
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"

Start-Process "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m app.server
