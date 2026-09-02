# Shared helper: make sure node + npm exist.
# Dot-sourced by build-desktop.ps1 / install.ps1.

function Add-PsaNodePath {
  $dirs = @(
    (Join-Path $env:ProgramFiles "nodejs"),
    (Join-Path ${env:ProgramFiles(x86)} "nodejs"),
    (Join-Path $env:LOCALAPPDATA "Programs\nodejs"),
    (Join-Path $env:APPDATA "npm"),
    (Join-Path $env:USERPROFILE ".local\bin"),
    (Join-Path $env:USERPROFILE "scoop\apps\nodejs\current"),
    (Join-Path $env:USERPROFILE "scoop\apps\nodejs-lts\current")
  )
  foreach ($d in $dirs) {
    if ($d -and (Test-Path -LiteralPath $d)) {
      if ($env:PATH -notlike "*$d*") { $env:PATH = "$d;$env:PATH" }
    }
  }
}

function Find-PsaNodeExe {
  $candidates = @(
    (Join-Path $env:ProgramFiles "nodejs\node.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "nodejs\node.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\nodejs\node.exe")
  )
  foreach ($p in $candidates) {
    if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  }
  return $null
}

function Refresh-PsaProcessPath {
  $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
  if ($machine -or $user) {
    $env:PATH = @($machine, $user, $env:PATH) -join ";"
  }
  Add-PsaNodePath
  $found = Find-PsaNodeExe
  if ($found) {
    $bin = Split-Path -Parent $found
    if ($env:PATH -notlike "*$bin*") { $env:PATH = "$bin;$env:PATH" }
  }
}

function Test-PsaNpmReady {
  Refresh-PsaProcessPath
  return [bool]((Get-Command npm -ErrorAction SilentlyContinue) -and (Get-Command node -ErrorAction SilentlyContinue))
}

function Save-PsaUrlToFile {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile
  )
  Write-Host "[PSA] download: $Url"
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    & curl.exe -fsSL --connect-timeout 20 --retry 3 -o $OutFile $Url
    if (($LASTEXITCODE -eq 0) -and (Test-Path -LiteralPath $OutFile) -and ((Get-Item -LiteralPath $OutFile).Length -gt 1MB)) {
      return $true
    }
    Write-Host "[PSA] curl failed (exit $LASTEXITCODE)"
  }

  $prevProgress = $ProgressPreference
  $ProgressPreference = "SilentlyContinue"
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 120
    if ((Test-Path -LiteralPath $OutFile) -and ((Get-Item -LiteralPath $OutFile).Length -gt 1MB)) {
      return $true
    }
  } catch {
    Write-Host "[PSA] Invoke-WebRequest failed: $($_.Exception.Message)"
  } finally {
    $ProgressPreference = $prevProgress
  }
  return $false
}

function Install-PsaNodeViaMsi {
  Write-Host "[PSA] trying Node.js MSI (npmmirror first)..."
  # Keep a recent LTS; override with PSA_NODE_VERSION=v22.14.0 if needed.
  $ver = if ($env:PSA_NODE_VERSION) { $env:PSA_NODE_VERSION } else { "v22.14.0" }
  if ($ver -notmatch '^v') { $ver = "v$ver" }
  $file = "node-$ver-x64.msi"
  $urls = @(
    "https://npmmirror.com/mirrors/node/$ver/$file",
    "https://cdn.npmmirror.com/binaries/node/$ver/$file",
    "https://nodejs.org/dist/$ver/$file"
  )
  $tmp = Join-Path $env:TEMP $file
  if (Test-Path -LiteralPath $tmp) {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }

  $downloaded = $false
  foreach ($url in $urls) {
    if (Save-PsaUrlToFile -Url $url -OutFile $tmp) {
      $downloaded = $true
      break
    }
  }
  if (-not $downloaded) {
    Write-Host "[PSA] MSI download failed from all mirrors"
    return $false
  }

  $sizeMb = [math]::Round((Get-Item -LiteralPath $tmp).Length / 1MB, 1)
  Write-Host "[PSA] installing MSI ($sizeMb MB, silent)..."
  $p = Start-Process -FilePath "msiexec.exe" `
    -ArgumentList "/i `"$tmp`" /qn /norestart ALLUSERS=1 ADDLOCAL=ALL" `
    -Wait -PassThru
  Write-Host "[PSA] msiexec exit $($p.ExitCode)"
  # 0 = success, 3010 = success reboot required
  if (($p.ExitCode -ne 0) -and ($p.ExitCode -ne 3010)) {
    Write-Host "[PSA] silent install failed; retrying with UI..."
    $p2 = Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$tmp`"" -Wait -PassThru
    Write-Host "[PSA] msiexec (UI) exit $($p2.ExitCode)"
  }

  Start-Sleep -Seconds 2
  Refresh-PsaProcessPath
  return (Test-PsaNpmReady)
}

function Install-PsaNodeViaWinget {
  if ($env:PSA_SKIP_WINGET -eq "1") { return $false }
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
  Write-Host "[PSA] trying winget --source winget ..."
  # 0x80072efd / 12029: winget CDN often blocked in CN; do not treat as fatal.
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & winget install -e --id OpenJS.NodeJS.LTS `
      --source winget `
      --accept-package-agreements `
      --accept-source-agreements `
      --disable-interactivity 2>&1 | ForEach-Object { Write-Host $_ }
  } catch {
    Write-Host "[PSA] winget threw: $($_.Exception.Message)"
  } finally {
    $ErrorActionPreference = $prevEap
  }
  Write-Host "[PSA] winget exit $LASTEXITCODE"
  Refresh-PsaProcessPath
  return (Test-PsaNpmReady)
}

function Install-PsaNodeViaChoco {
  if (-not (Get-Command choco -ErrorAction SilentlyContinue)) { return $false }
  Write-Host "[PSA] trying chocolatey..."
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & choco install nodejs-lts -y
  } finally {
    $ErrorActionPreference = $prevEap
  }
  Refresh-PsaProcessPath
  return (Test-PsaNpmReady)
}

function Ensure-PsaNpm {
  if (Test-PsaNpmReady) {
    Write-Host "[PSA] node $(node -v)  npm $(npm -v)"
    return
  }

  $existing = Find-PsaNodeExe
  if ($existing) {
    Write-Host "[PSA] found $existing but npm not on PATH; fixing PATH for this session"
    Refresh-PsaProcessPath
    if (Test-PsaNpmReady) {
      Write-Host "[PSA] node $(node -v)  npm $(npm -v)"
      return
    }
  }

  Write-Host "[PSA] npm/node not on PATH; installing Node.js LTS..."
  # Prefer MSI/npmmirror in CN networks; winget CDN often fails (0x80072efd).
  $ok = $false
  if (-not $ok) { $ok = Install-PsaNodeViaMsi }
  if (-not $ok) { $ok = Install-PsaNodeViaChoco }
  if (-not $ok) { $ok = Install-PsaNodeViaWinget }

  if (-not (Test-PsaNpmReady)) {
    $mirror = "https://npmmirror.com/mirrors/node/v22.14.0/node-v22.14.0-x64.msi"
    throw @"
npm still missing after auto-install.

Your network appears to block winget CDN (0x80072efd / 12029).

Manual fix (recommended):
  1. Download: $mirror
  2. Run the MSI installer
  3. Close this terminal, open a new one
  4. Retry scripts\build-desktop.cmd

Or install from https://nodejs.org/ (LTS x64).
"@
  }
  Write-Host "[PSA] node $(node -v)  npm $(npm -v)"
}
