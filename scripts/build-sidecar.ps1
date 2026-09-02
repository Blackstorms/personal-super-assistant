# Windows: build FastAPI sidecar with PyInstaller（含 vendored Hermes）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Server = Join-Path $Root "server"
$Hermes = Join-Path $Root "third_party\hermes-agent"
$Dest = Join-Path $Root "resources\sidecars\win32-x64"
$Name = "server-win-x64.exe"

if (-not (Test-Path (Join-Path $Hermes "model_tools.py"))) {
  throw "missing vendored Hermes at $Hermes"
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host "[PSA] building sidecar → $Dest\$Name (vendored Hermes)"
Push-Location $Server
$py = Join-Path $Server ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m pip install -q pyinstaller

$tiktokenArgs = @()
& $py -c "import tiktoken" 2>$null
if ($LASTEXITCODE -eq 0) {
  $tiktokenArgs += "--collect-data=tiktoken"
} else {
  Write-Host "[PSA] tiktoken not installed; skip collect-data (compress fallback OK)"
}

$addData = @(
  "--add-data=$Hermes;third_party/hermes-agent"
)
$DbDir = Join-Path $Root "resources\db"
if (Test-Path $DbDir) {
  $addData += "--add-data=$DbDir;resources/db"
}
$Skills = Join-Path $Root "skills"
if (Test-Path $Skills) {
  $addData += "--add-data=$Skills;skills"
}

& $py -m PyInstaller --noconfirm --clean --onefile --name "server-win-x64" `
  --paths $Server `
  --paths $Hermes `
  @addData `
  --hidden-import=uvicorn.logging `
  --collect-submodules=app `
  --collect-data=certifi `
  @tiktokenArgs `
  --console `
  sidecar_entry.py
Copy-Item "dist\server-win-x64.exe" (Join-Path $Dest $Name) -Force
Pop-Location
Write-Host "[PSA] wrote $Dest\$Name (vendored Hermes included)"
