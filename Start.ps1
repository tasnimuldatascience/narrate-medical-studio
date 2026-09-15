$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$studioPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { throw 'Run Setup.ps1 first to create the local environment.' }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Build the interface with npm.cmd --prefix frontend run build.' }
Write-Host 'Narrate Studio: http://127.0.0.1:8765' -ForegroundColor Green
Write-Host 'Keep this terminal open. Press Ctrl+C to stop.'
& $studioPython -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
