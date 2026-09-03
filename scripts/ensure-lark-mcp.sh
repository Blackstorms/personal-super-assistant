#!/usr/bin/env bash
# 预装飞书官方 MCP CLI，避免每次 npx -y 拉包
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"

if ! command -v npm >/dev/null 2>&1; then
  echo "[PSA] skip lark-mcp: npm not found"
  exit 0
fi

echo "[PSA] npm registry → ${REGISTRY}"
npm config set registry "$REGISTRY" >/dev/null

echo "[PSA] install @larksuiteoapi/lark-mcp (local tools/mcp)"
mkdir -p "$ROOT/tools/mcp"
cd "$ROOT/tools/mcp"
if [[ ! -f package.json ]]; then
  cat > package.json <<'EOF'
{
  "name": "psa-mcp-tools",
  "private": true,
  "dependencies": {
    "@larksuiteoapi/lark-mcp": "^0.5.0"
  }
}
EOF
fi
npm install --registry "$REGISTRY"

echo "[PSA] install @larksuiteoapi/lark-mcp (global, optional)"
npm install -g @larksuiteoapi/lark-mcp --registry "$REGISTRY" || {
  echo "[PSA] WARN: global lark-mcp install failed; local tools/mcp still OK"
}

LOCAL_BIN="$ROOT/tools/mcp/node_modules/.bin/lark-mcp"
if [[ -x "$LOCAL_BIN" ]]; then
  echo "[PSA] local lark-mcp OK: $LOCAL_BIN"
elif command -v lark-mcp >/dev/null 2>&1; then
  echo "[PSA] global lark-mcp OK: $(command -v lark-mcp)"
else
  echo "[PSA] WARN: lark-mcp binary not found after install"
  exit 1
fi
