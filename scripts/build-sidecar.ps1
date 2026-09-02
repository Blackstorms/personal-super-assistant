#!/usr/bin/env -S powershell.exe -NoProfile -ExecutionPolicy Bypass -File
# Windows: build FastAPI sidecar with PyInstaller (vendored Hermes).
# Prefer scripts\build-sidecar.cmd from cmd.exe / Git Bash (bypasses ExecutionPolicy).
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
  $PSNativeCommandUseErrorActionPreference = $false
}

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
  $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$Root = Split-Path -Parent $ScriptDir
$Server = Join-Path $Root "server"
$Hermes = Join-Path $Root "third_party\hermes-agent"
$Dest = Join-Path $Root "resources\sidecars\win32-x64"
$Name = "server-win-x64.exe"
$Entry = Join-Path $Server "sidecar_entry.py"

if (-not (Test-Path -LiteralPath (Join-Path $Hermes "model_tools.py"))) {
  throw "missing vendored Hermes at $Hermes"
}
if (-not (Test-Path -LiteralPath $Entry)) {
  throw "missing $Entry"
}

function Find-Python {
  foreach ($rel in @(".venv\Scripts\python.exe", ".venv312\Scripts\python.exe")) {
    $candidate = Join-Path $Server $rel
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  foreach ($cmd in @("python", "python3", "py")) {
    $resolved = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $resolved) { continue }
    if ($resolved.Source -match "WindowsApps") { continue }
    return $resolved.Source
  }
  throw "Python not found. Run scripts\install.ps1 first to create server\.venv."
}

$py = Find-Python
Write-Host "[PSA] python: $py"
Write-Host "[PSA] building sidecar -> $Dest\$Name (vendored Hermes)"

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Push-Location $Server
try {
  & $py -m pip install -q pyinstaller
  if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed (exit $LASTEXITCODE)" }

  $tiktokenArgs = @()
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $py -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('tiktoken') else 1)" | Out-Null
  $tiktokenOk = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prevEap
  if ($tiktokenOk) {
    $tiktokenArgs += "--collect-data=tiktoken"
  } else {
    Write-Host "[PSA] tiktoken not installed; skip collect-data (compress fallback OK)"
  }

  $piArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "server-win-x64",
    "--paths", $Server,
    "--paths", $Hermes,
    "--add-data", ($Hermes + ";third_party/hermes-agent")
  )
  $DbDir = Join-Path $Root "resources\db"
  if (Test-Path -LiteralPath $DbDir) {
    $piArgs += @("--add-data", ($DbDir + ";resources/db"))
  }
  $Skills = Join-Path $Root "skills"
  if (Test-Path -LiteralPath $Skills) {
    $piArgs += @("--add-data", ($Skills + ";skills"))
  }
  $piArgs += @(
    "--hidden-import=uvicorn.logging",
    "--hidden-import=uvicorn.loops",
    "--hidden-import=uvicorn.loops.auto",
    "--hidden-import=uvicorn.protocols",
    "--hidden-import=uvicorn.protocols.http",
    "--hidden-import=uvicorn.protocols.http.auto",
    "--hidden-import=uvicorn.protocols.websockets.auto",
    "--hidden-import=uvicorn.lifespan",
    "--hidden-import=uvicorn.lifespan.on",
    "--collect-submodules=app",
    "--collect-data=certifi"
  )
  if ($tiktokenArgs.Count -gt 0) { $piArgs += $tiktokenArgs }
  $piArgs += @("--console", "sidecar_entry.py")

  & $py @piArgs
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

  $built = Join-Path $Server "dist\server-win-x64.exe"
  if (-not (Test-Path -LiteralPath $built)) { throw "expected $built" }
  Copy-Item -LiteralPath $built -Destination (Join-Path $Dest $Name) -Force
} finally {
  Pop-Location
}

$Tpl = Join-Path $Root "resources\hermes_home_template"
New-Item -ItemType Directory -Force -Path $Tpl | Out-Null
@(
  "# HERMES_HOME template",
  "",
  "Created at runtime under {PSA_DATA_DIR}/hermes_home.",
  "Hermes is vendored at third_party/hermes-agent and bundled into the sidecar.",
  "",
  "See docs/Hermes集成说明.md."
) | Set-Content -LiteralPath (Join-Path $Tpl "README.md") -Encoding UTF8

Write-Host "[PSA] wrote $Dest\$Name (vendored Hermes included)"
Write-Host "[PSA] sidecar build done."
