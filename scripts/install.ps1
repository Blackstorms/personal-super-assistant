# Windows PowerShell 一键安装脚本
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "[PSA] root: $Root"

function Need($cmd) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "missing: $cmd" }
}
Need python
Need npm

Write-Host "[PSA] python venv"
if (Get-Command uv -ErrorAction SilentlyContinue) {
  Write-Host "[PSA] using uv"
  Push-Location "$Root\server"
  uv venv .venv --python 3.12
  & "$Root\server\.venv\Scripts\uv.exe" pip install -r "$Root\server\requirements.txt"
  if (-not $?) { & "$Root\server\.venv\Scripts\pip.exe" install -r "$Root\server\requirements.txt" }
  Pop-Location
} else {
  python -m venv "$Root\server\.venv"
  & "$Root\server\.venv\Scripts\pip.exe" install -U pip
  & "$Root\server\.venv\Scripts\pip.exe" install -r "$Root\server\requirements.txt"
}

$Hermes = Join-Path $Root "third_party\hermes-agent"
if (Test-Path (Join-Path $Hermes "model_tools.py")) {
  Write-Host "[PSA] vendored Hermes OK: $Hermes"
} else {
  Write-Host "[PSA] WARN: missing $Hermes; Hermes bridge will degrade"
}

Write-Host "[PSA] desktop deps"
$env:ELECTRON_MIRROR = if ($env:ELECTRON_MIRROR) { $env:ELECTRON_MIRROR } else { "https://npmmirror.com/mirrors/electron/" }
Push-Location "$Root\apps\desktop"
npm install
Pop-Location

Write-Host "[PSA] start backend"
$env:PYTHONPATH = "$Root\server"
Start-Process -FilePath "$Root\server\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","18765" -WorkingDirectory "$Root\server" -WindowStyle Hidden
Start-Sleep -Seconds 2
Invoke-WebRequest -Uri "http://127.0.0.1:18765/api/v1/health" -UseBasicParsing | Out-Null
Write-Host "[PSA] backend healthy"
Write-Host "Start UI: cd apps\desktop; npm run electron:dev"
