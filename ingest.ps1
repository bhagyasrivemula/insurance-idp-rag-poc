# ---------------------------------------------------------------------------
# Run the IDP pipeline over data\brochures -> data\processed + data\chroma.
# Usage:  .\ingest.ps1            process new / changed PDFs only
#         .\ingest.ps1 -Force     rebuild everything
#         .\ingest.ps1 -SkipLlm   fast run without LLM key-fact extraction
# ---------------------------------------------------------------------------
param([switch]$Force, [switch]$SkipLlm)
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"

$argsList = @("-m", "app.idp.pipeline")
if ($Force)   { $argsList += "--force" }
if ($SkipLlm) { $argsList += "--skip-llm" }
.\.venv\Scripts\python.exe @argsList
