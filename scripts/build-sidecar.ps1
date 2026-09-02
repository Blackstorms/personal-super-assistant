#!/usr/bin/env -S powershell.exe -NoProfile -ExecutionPolicy Bypass -File
# Windows: build FastAPI sidecar with PyInstaller (vendored Hermes).
# Prefer scripts\build-sidecar.cmd
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
$Req = Join-Path $Server "requirements.txt"
$OutExe = Join-Path $Dest $Name

if (-not (Test-Path -LiteralPath (Join-Path $Hermes "model_tools.py"))) {
  throw "missing vendored Hermes at $Hermes"
}
if (-not (Test-Path -LiteralPath $Entry)) { throw "missing $Entry" }
if (-not (Test-Path -LiteralPath $Req)) { throw "missing $Req" }

function Invoke-Py {
  param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string[]]$PyArgs,
    [string]$WorkDir = ""
  )
  $startArgs = @{
    FilePath         = $Python
    ArgumentList     = $PyArgs
    Wait             = $true
    PassThru         = $true
    NoNewWindow      = $true
  }
  if ($WorkDir) { $startArgs["WorkingDirectory"] = $WorkDir }
  $p = Start-Process @startArgs
  if ($null -eq $p.ExitCode) { return 1 }
  return [int]$p.ExitCode
}

function Find-BasePython {
  foreach ($cmd in @("python", "python3", "py")) {
    $resolved = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $resolved) { continue }
    if ($resolved.Source -match "WindowsApps") { continue }
    return $resolved.Source
  }
  throw "Python not found. Install Python 3.11+ x64 from https://www.python.org/"
}

function Ensure-ServerVenv {
  foreach ($rel in @(".venv\Scripts\python.exe", ".venv312\Scripts\python.exe")) {
    $candidate = Join-Path $Server $rel
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  $base = Find-BasePython
  $venvDir = Join-Path $Server ".venv"
  Write-Host "[PSA] creating venv: $venvDir"
  if ((Invoke-Py -Python $base -PyArgs @("-m", "venv", $venvDir) -WorkDir $Server) -ne 0) { throw "venv create failed" }
  $py = Join-Path $venvDir "Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $py)) { throw "venv python missing: $py" }
  return $py
}

function Assert-PyImport {
  param([string]$Python)
  $code = @'
import importlib
import sys
from pathlib import Path

# Ensure server/ is on sys.path even if cwd differs.
server = Path(__file__).resolve().parent
if str(server) not in sys.path:
    sys.path.insert(0, str(server))

mods = ["uvicorn", "fastapi", "starlette", "anyio"]
for m in mods:
    mod = importlib.import_module(m)
    print(m, "OK", getattr(mod, "__file__", "?"))
from app.main import app
print("app.main OK", type(app))
'@
  # Keep check script under server/ so "app" package resolves.
  $tmp = Join-Path $Server "psa-check-imports.py"
  Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8
  try {
    $ec = Invoke-Py -Python $Python -PyArgs @($tmp) -WorkDir $Server
    if ($ec -ne 0) {
      throw "build-env import check failed (exit $ec). Need uvicorn + importable app.main from $Server"
    }
  } finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Test-SidecarSmoke {
  param([string]$Exe)
  $port = 18775
  $err = Join-Path $env:TEMP "psa-sidecar-smoke.err.txt"
  $out = Join-Path $env:TEMP "psa-sidecar-smoke.out.txt"
  Remove-Item $err, $out -Force -ErrorAction SilentlyContinue

  Write-Host "[PSA] smoke-testing $Exe on port $port ..."
  $prevHost = $env:PSA_HOST
  $prevPort = $env:PSA_PORT
  $env:PSA_HOST = "127.0.0.1"
  $env:PSA_PORT = "$port"
  $proc = $null
  try {
    $proc = Start-Process -FilePath $Exe `
      -PassThru -WindowStyle Hidden `
      -RedirectStandardError $err `
      -RedirectStandardOutput $out

    $ok = $false
    for ($i = 0; $i -lt 45; $i++) {
      Start-Sleep -Seconds 1
      if ($proc.HasExited) {
        $msg = ""
        if (Test-Path -LiteralPath $err) { $msg = Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $out) { $msg += "`n" + (Get-Content -LiteralPath $out -Raw -ErrorAction SilentlyContinue) }
        throw "sidecar exited early (code $($proc.ExitCode)). Log:`n$msg"
      }
      try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/v1/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
      } catch { }
    }
    if (-not $ok) {
      $msg = ""
      if (Test-Path -LiteralPath $err) { $msg = Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue }
      if (Test-Path -LiteralPath $out) { $msg += "`n" + (Get-Content -LiteralPath $out -Raw -ErrorAction SilentlyContinue) }
      throw "sidecar health check timed out. Log:`n$msg"
    }
    Write-Host "[PSA] smoke OK"
  } finally {
    if ($null -ne $proc -and -not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -eq $prevHost) { Remove-Item Env:PSA_HOST -ErrorAction SilentlyContinue } else { $env:PSA_HOST = $prevHost }
    if ($null -eq $prevPort) { Remove-Item Env:PSA_PORT -ErrorAction SilentlyContinue } else { $env:PSA_PORT = $prevPort }
  }
}

$py = Ensure-ServerVenv
Write-Host "[PSA] python: $py"
Write-Host "[PSA] building sidecar -> $OutExe"

# Prefer CN PyPI if unset
if (-not $env:PIP_INDEX_URL) {
  $env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
  $env:PIP_TRUSTED_HOST = "pypi.tuna.tsinghua.edu.cn"
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Push-Location $Server
try {
  Write-Host "[PSA] wipe previous PyInstaller outputs..."
  Remove-Item -LiteralPath (Join-Path $Server "build") -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath (Join-Path $Server "dist") -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath (Join-Path $Server "server-win-x64.spec") -Force -ErrorAction SilentlyContinue

  Write-Host "[PSA] installing requirements + pyinstaller into venv..."
  if ((Invoke-Py -Python $py -PyArgs @("-m", "pip", "install", "-U", "pip") -WorkDir $Server) -ne 0) { throw "pip upgrade failed" }
  if ((Invoke-Py -Python $py -PyArgs @("-m", "pip", "install", "-r", $Req, "pyinstaller>=6.0") -WorkDir $Server) -ne 0) {
    throw "pip install requirements failed"
  }

  Assert-PyImport -Python $py

  $tiktokenArgs = @()
  $ecTik = Invoke-Py -Python $py -PyArgs @("-c", "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('tiktoken') else 1)") -WorkDir $Server
  if ($ecTik -eq 0) {
    $tiktokenArgs += @("--collect-all", "tiktoken")
  } else {
    Write-Host "[PSA] tiktoken not installed; skip"
  }

  # Hermès on --paths can confuse analysis; keep only server on pathex for imports,
  # and pass Hermes solely via --add-data.
  $piArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--noupx",
    "--name", "server-win-x64",
    "--paths", $Server,
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

  # collect-all is stronger than hidden-import for uvicorn on Windows.
  foreach ($pkg in @("uvicorn", "fastapi", "starlette", "anyio", "click", "h11", "httptools", "websockets", "watchfiles")) {
    $piArgs += @("--collect-all", $pkg)
  }
  $piArgs += @(
    "--hidden-import=uvicorn",
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
    "--collect-data=certifi",
    "--copy-metadata=uvicorn",
    "--copy-metadata=fastapi"
  )
  if ($tiktokenArgs.Count -gt 0) { $piArgs += $tiktokenArgs }
  $piArgs += @("--console", "sidecar_entry.py")

  Write-Host "[PSA] PyInstaller ..."
  Write-Host ("[PSA] " + ($piArgs -join " "))
  if ((Invoke-Py -Python $py -PyArgs $piArgs -WorkDir $Server) -ne 0) { throw "PyInstaller failed" }

  $built = Join-Path $Server "dist\server-win-x64.exe"
  if (-not (Test-Path -LiteralPath $built)) { throw "expected $built" }

  # warn-*.txt lists many optional/missing submodules; do NOT fail the build on that.
  # Real gate is size check + smoke health test below.
  $warn = Get-ChildItem -Path (Join-Path $Server "build") -Filter "warn-*.txt" -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($warn) {
    $hits = Select-String -Path $warn.FullName -Pattern "missing module named ['\`"]?uvicorn['\`"]?\b" -AllMatches -ErrorAction SilentlyContinue
    if ($hits) {
      Write-Host "[PSA] note: warn file mentions top-level uvicorn (often a false positive for optional hooks)."
      Write-Host "      Continuing; smoke test will decide success: $($warn.FullName)"
    }
  }

  Copy-Item -LiteralPath $built -Destination $OutExe -Force
  $sizeMb = [math]::Round((Get-Item -LiteralPath $OutExe).Length / 1MB, 1)
  Write-Host "[PSA] wrote $OutExe ($sizeMb MB)"
  if ($sizeMb -lt 15) {
    throw "sidecar suspiciously small ($sizeMb MB); uvicorn/deps likely not bundled. Check build env."
  }

  Test-SidecarSmoke -Exe $OutExe
} finally {
  Pop-Location
}

Write-Host "[PSA] sidecar build done."
Write-Host "[PSA] NEXT: rebuild the installer so the new exe is embedded:"
Write-Host "      scripts\build-desktop.cmd"
Write-Host "      Then uninstall old app / use the new Setup exe (old install still has old sidecar)."
