# Windows PowerShell 一键部署：环境检测 → 依赖安装 → 配置校验 → 启动后端与桌面端
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "[PSA] root: $Root"

function Need($cmd) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "missing: $cmd" }
}
Need python
. (Join-Path $PSScriptRoot "lib\ensure-node.ps1")
Ensure-PsaNpm

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

$Py = "$Root\server\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  $Py = "$Root\server\.venv312\Scripts\python.exe"
}
if (-not (Test-Path $Py)) { throw "venv python missing under server\.venv" }

$Hermes = Join-Path $Root "third_party\hermes-agent"
if (Test-Path (Join-Path $Hermes "model_tools.py")) {
  Write-Host "[PSA] vendored Hermes OK: $Hermes"
} else {
  Write-Host "[PSA] WARN: missing $Hermes; Hermes bridge will degrade"
}

Write-Host "[PSA] schema check"
$schema = Join-Path $Root "resources\db\schema.sql"
if (-not (Test-Path $schema)) { throw "missing schema.sql: $schema" }
Write-Host "[PSA] schema ok $schema"

Write-Host "[PSA] desktop deps"
$env:ELECTRON_MIRROR = if ($env:ELECTRON_MIRROR) { $env:ELECTRON_MIRROR } else { "https://npmmirror.com/mirrors/electron/" }
$env:NPM_CONFIG_REGISTRY = if ($env:NPM_CONFIG_REGISTRY) { $env:NPM_CONFIG_REGISTRY } else { "https://registry.npmmirror.com" }
npm config set registry $env:NPM_CONFIG_REGISTRY | Out-Null
Push-Location "$Root\apps\desktop"
npm install
Pop-Location

Write-Host "[PSA] ensure lark-mcp"
& (Join-Path $PSScriptRoot "ensure-lark-mcp.ps1")
if (-not $?) { Write-Host "[PSA] WARN: ensure-lark-mcp failed" }

function Test-PsaBackend {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:18765/api/v1/health" -UseBasicParsing -TimeoutSec 2
    return $r.StatusCode -eq 200
  } catch {
    return $false
  }
}

function Wait-PsaBackend {
  for ($i = 0; $i -lt 45; $i++) {
    if (Test-PsaBackend) {
      Write-Host "[PSA] backend healthy (http://127.0.0.1:18765)"
      return
    }
    Start-Sleep -Seconds 1
  }
  throw "backend health check failed"
}

if (Test-PsaBackend) {
  Write-Host "[PSA] backend already running, reuse"
} else {
  Write-Host "[PSA] start backend"
  $env:PYTHONPATH = "$Root\server"
  $proc = Start-Process -FilePath $Py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","18765" -WorkingDirectory "$Root\server" -WindowStyle Hidden -PassThru
  Set-Content -Path "$Root\server\uvicorn.pid" -Value $proc.Id
  Wait-PsaBackend
}

Write-Host "[PSA] start desktop UI (Vite + Electron)"
Write-Host "[PSA] backend http://127.0.0.1:18765"
Write-Host "[PSA] login page will open; sign in manually (default admin / admin)"
Write-Host "[PSA] close the window or Ctrl+C to stop UI (backend keeps running)"
if (Test-Path Env:ELECTRON_RUN_AS_NODE) { Remove-Item Env:ELECTRON_RUN_AS_NODE }
$env:PSA_SHOW_LOGIN = "1"
$env:VITE_PSA_SHOW_LOGIN = "1"
Push-Location "$Root\apps\desktop"
npm start
Pop-Location
