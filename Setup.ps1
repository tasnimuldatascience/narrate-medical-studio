$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed with exit code $LASTEXITCODE" }
}
Write-Host 'Setup downloads Python and frontend packages into this project.'
if ((Read-Host 'Install project dependencies? Type yes') -ne 'yes') { return }
Invoke-Checked 'python' @('-m','venv','.venv')
$studioPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Invoke-Checked $studioPython @('-m','pip','install','-r','requirements.txt')
Invoke-Checked 'npm.cmd' @('--prefix','frontend','ci')
Invoke-Checked 'npm.cmd' @('--prefix','frontend','run','build')
Write-Host 'Voice assets are downloaded only during this explicit setup step.'
Write-Host 'Recommended: Kokoro for paragraph narration and four narrator choices. Piper is an optional compact alternative.'
do {
    $studioVoiceChoice = (Read-Host 'Voice setup: kokoro / piper / both / skip [default: kokoro]').Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($studioVoiceChoice)) { $studioVoiceChoice = 'kokoro' }
    if ($studioVoiceChoice -notin @('kokoro', 'piper', 'both', 'skip')) {
        Write-Host 'Enter kokoro, piper, both, or skip.' -ForegroundColor Yellow
    }
} while ($studioVoiceChoice -notin @('kokoro', 'piper', 'both', 'skip'))
if ($studioVoiceChoice -in @('kokoro', 'both')) {
    Invoke-Checked $studioPython @('scripts\download_kokoro.py')
}
if ($studioVoiceChoice -in @('piper', 'both')) {
    Invoke-Checked $studioPython @('-m','piper.download_voices','en_US-lessac-medium','--download-dir','models')
}
Write-Host 'Install PowerPoint, FFmpeg/ffprobe, and a local Ollama model separately if missing.'
Write-Host 'Use Preview voice in Setup or Export to audition a fixed sample. Project audio still requires slide approval.'
Write-Host 'Start the studio with .\Start.ps1. Check runtime readiness in Setup & preferences.' -ForegroundColor Green
