# 预装飞书官方 MCP CLI，避免每次 npx -y 拉包
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Registry = if ($env:NPM_CONFIG_REGISTRY) { $env:NPM_CONFIG_REGISTRY } else { "https://registry.npmmirror.com" }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Host "[PSA] skip lark-mcp: npm not found"
  exit 0
}

Write-Host "[PSA] npm registry → $Registry"
npm config set registry $Registry | Out-Null

$ToolsDir = Join-Path $Root "tools\mcp"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
Push-Location $ToolsDir
if (-not (Test-Path "package.json")) {
  @'
{
  "name": "psa-mcp-tools",
  "private": true,
  "dependencies": {
    "@larksuiteoapi/lark-mcp": "^0.5.0"
  }
}
'@ | Set-Content -Encoding utf8 package.json
}
Write-Host "[PSA] install @larksuiteoapi/lark-mcp (local tools/mcp)"
npm install --registry $Registry
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "local lark-mcp install failed" }
Pop-Location

Write-Host "[PSA] install @larksuiteoapi/lark-mcp (global, optional)"
npm install -g @larksuiteoapi/lark-mcp --registry $Registry
if ($LASTEXITCODE -ne 0) {
  Write-Host "[PSA] WARN: global lark-mcp install failed; local tools/mcp still OK"
}

$LocalBin = Join-Path $ToolsDir "node_modules\.bin\lark-mcp.cmd"
$LocalBinUnix = Join-Path $ToolsDir "node_modules\.bin\lark-mcp"
if (Test-Path $LocalBin) {
  Write-Host "[PSA] local lark-mcp OK: $LocalBin"
} elseif (Test-Path $LocalBinUnix) {
  Write-Host "[PSA] local lark-mcp OK: $LocalBinUnix"
} elseif (Get-Command lark-mcp -ErrorAction SilentlyContinue) {
  Write-Host "[PSA] global lark-mcp OK: $((Get-Command lark-mcp).Source)"
} else {
  throw "[PSA] lark-mcp binary not found after install"
}
