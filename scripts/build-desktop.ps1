#!/usr/bin/env -S powershell.exe -NoProfile -ExecutionPolicy Bypass -File
# One-click Windows NSIS installer. Prefer scripts\build-desktop.cmd
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
$Desktop = Join-Path $Root "apps\desktop"
$Sidecar = Join-Path $Root "resources\sidecars\win32-x64\server-win-x64.exe"

if (-not $env:ELECTRON_MIRROR) {
  $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
}
if (-not $env:ELECTRON_BUILDER_BINARIES_MIRROR) {
  $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
}
# Skip code-signing discovery (contest builds are unsigned).
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"

. (Join-Path $ScriptDir "lib\ensure-node.ps1")
Ensure-PsaNpm

function Test-PsaDeveloperMode {
  try {
    $v = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" `
      -Name "AllowDevelopmentWithoutDevLicense" -ErrorAction SilentlyContinue
    return ($v.AllowDevelopmentWithoutDevLicense -eq 1)
  } catch {
    return $false
  }
}

function Repair-PsaWinCodeSignCache {
  # electron-builder extracts winCodeSign.7z with -snld (create symlinks).
  # On Windows without Developer Mode / admin, darwin/*.dylib symlinks fail and
  # the whole extract is treated as failure even though Windows tools are fine.
  $cache = Join-Path $env:LOCALAPPDATA "electron-builder\Cache\winCodeSign"
  if (-not (Test-Path -LiteralPath $cache)) { return }

  $sevenZa = Join-Path $Desktop "node_modules\7zip-bin\win\x64\7za.exe"
  if (-not (Test-Path -LiteralPath $sevenZa)) {
    $sevenZa = Join-Path $Desktop "node_modules\7zip-bin\win\ia32\7za.exe"
  }

  Get-ChildItem -LiteralPath $cache -Filter "*.7z" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $archive = $_.FullName
    $outDir = Join-Path $cache $_.BaseName
    $rcedit = Join-Path $outDir "rcedit-x64.exe"
    $winToolsOk = (Test-Path -LiteralPath $rcedit) -or `
      (Test-Path -LiteralPath (Join-Path $outDir "windows-10\signtool.exe")) -or `
      (Test-Path -LiteralPath (Join-Path $outDir "windows-11\signtool.exe"))

    if ($winToolsOk) {
      Write-Host "[PSA] winCodeSign cache OK: $outDir"
      return
    }

    Write-Host "[PSA] repairing winCodeSign cache (extract without symlinks): $($_.Name)"
    if (Test-Path -LiteralPath $outDir) {
      Remove-Item -LiteralPath $outDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null

    if (Test-Path -LiteralPath $sevenZa) {
      # No -snld => do not create symlinks; darwin dylibs are unused on Windows builds.
      & $sevenZa x -bd "-o$outDir" $archive | Out-Null
    } else {
      Write-Host "[PSA] 7za not found yet; will rely on electron-builder / Developer Mode"
      return
    }

    # Touch placeholder files so partial darwin paths don't confuse tools.
    $darwinLib = Join-Path $outDir "darwin\10.12\lib"
    if (-not (Test-Path -LiteralPath $darwinLib)) {
      New-Item -ItemType Directory -Force -Path $darwinLib | Out-Null
    }
    foreach ($name in @("libcrypto.dylib", "libssl.dylib")) {
      $p = Join-Path $darwinLib $name
      if (-not (Test-Path -LiteralPath $p)) {
        New-Item -ItemType File -Force -Path $p | Out-Null
      }
    }
    Write-Host "[PSA] winCodeSign cache repaired: $outDir"
  }
}

Write-Host "[PSA] desktop build for win32-x64"
if (-not (Test-Path -LiteralPath $Sidecar)) {
  throw "missing sidecar: $Sidecar`nRun scripts\build-sidecar.cmd first, then retry."
}

if (-not (Test-PsaDeveloperMode)) {
  Write-Host "[PSA] tip: Windows Developer Mode is OFF."
  Write-Host "      Settings → Privacy & security → For developers → Developer Mode = On"
  Write-Host "      (avoids winCodeSign symlink errors; script will also try cache repair)"
}

Push-Location $Desktop
try {
  npm install
  if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }

  Repair-PsaWinCodeSignCache

  $pkg = Get-Content -LiteralPath (Join-Path $Desktop "package.json") -Raw
  if ($pkg -match '"electron:build:win"') {
    npm run electron:build:win
  } else {
    Write-Host "[PSA] package.json has no electron:build:win; using electron-builder --win --x64"
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    npx electron-builder --win --x64
  }

  if ($LASTEXITCODE -ne 0) {
    Write-Host "[PSA] build failed; retrying after cleaning broken winCodeSign cache..."
    $cache = Join-Path $env:LOCALAPPDATA "electron-builder\Cache\winCodeSign"
    if (Test-Path -LiteralPath $cache) {
      # Keep .7z archives, remove extract folders so we can re-extract without -snld.
      Get-ChildItem -LiteralPath $cache -Directory -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    Repair-PsaWinCodeSignCache
    if ($pkg -match '"electron:build:win"') {
      npm run electron:build:win
    } else {
      npx electron-builder --win --x64
    }
  }

  if ($LASTEXITCODE -ne 0) {
    throw @"
Windows electron-builder failed (exit $LASTEXITCODE).

winCodeSign symlink error fix:
  1. Settings → Privacy & security → For developers → turn on Developer Mode
  2. Or run this terminal As Administrator once
  3. Delete cache then retry:
     rmdir /s /q "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign"
     scripts\build-desktop.cmd
"@
  }
} finally {
  Pop-Location
}

$Release = Join-Path $Desktop "release"
Write-Host "[PSA] done. Installers are under $Release"
Get-ChildItem -LiteralPath $Release -File | Select-Object Name, Length | Format-Table -AutoSize
