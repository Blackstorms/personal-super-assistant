#!/usr/bin/env bash
# macOS / Linux 一键部署：环境检测 → 依赖安装 → 配置校验 → 启动后端与桌面端
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[PSA] project root: $ROOT"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1"; exit 1; }; }
need python3
# shellcheck source=lib/ensure-node.sh
. "$ROOT/scripts/lib/ensure-node.sh"
psa_ensure_npm

echo "[PSA] setup Python venv"
if command -v uv >/dev/null 2>&1; then
  echo "[PSA] using uv sync"
  cd "$ROOT/server"
  uv venv .venv --python 3.12 || uv venv .venv
  # shellcheck disable=SC1091
  source "$ROOT/server/.venv/bin/activate"
  uv pip install -e ".[dev,hermes]" || uv pip install -r requirements.txt
  cd "$ROOT"
else
  python3 -m venv "$ROOT/server/.venv"
  # shellcheck disable=SC1091
  source "$ROOT/server/.venv/bin/activate"
  pip install -U pip
  pip install -r "$ROOT/server/requirements.txt"
fi

if [[ -x "$ROOT/server/.venv/bin/python" ]]; then
  PY="$ROOT/server/.venv/bin/python"
elif [[ -x "$ROOT/server/.venv312/bin/python" ]]; then
  PY="$ROOT/server/.venv312/bin/python"
else
  echo "[PSA] ERROR: venv python missing under server/.venv"
  exit 1
fi

HERMES="$ROOT/third_party/hermes-agent"
if [[ -f "$HERMES/model_tools.py" ]]; then
  echo "[PSA] vendored Hermes OK: $HERMES"
else
  echo "[PSA] WARN: missing $HERMES (model_tools.py); Hermes bridge will degrade"
fi

echo "[PSA] init database schema check"
python3 - <<PY
from pathlib import Path
p = Path("$ROOT/resources/db/schema.sql")
assert p.exists(), p
print("schema ok", p)
PY

echo "[PSA] install desktop deps"
cd "$ROOT/apps/desktop"
# Electron 官方源在国内易超时，优先使用 npmmirror
export ELECTRON_MIRROR="${ELECTRON_MIRROR:-https://npmmirror.com/mirrors/electron/}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
npm config set registry "${NPM_CONFIG_REGISTRY}" >/dev/null || true
npm install

# 预装飞书 MCP CLI（少走每次 npx -y）
# shellcheck source=ensure-lark-mcp.sh
bash "$ROOT/scripts/ensure-lark-mcp.sh" || echo "[PSA] WARN: ensure-lark-mcp failed"

backend_healthy() {
  curl -sf --max-time 2 "http://127.0.0.1:18765/api/v1/health" >/dev/null 2>&1
}

wait_backend() {
  local i
  for i in $(seq 1 45); do
    if backend_healthy; then
      echo "[PSA] backend healthy (http://127.0.0.1:18765)"
      return 0
    fi
    sleep 1
  done
  echo "[PSA] ERROR: backend health check failed. log: $ROOT/server/uvicorn.log"
  tail -n 40 "$ROOT/server/uvicorn.log" 2>/dev/null || true
  return 1
}

if backend_healthy; then
  echo "[PSA] backend already running, reuse"
else
  echo "[PSA] start backend (background)"
  cd "$ROOT/server"
  nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 18765 > "$ROOT/server/uvicorn.log" 2>&1 &
  echo $! > "$ROOT/server/uvicorn.pid"
  wait_backend
fi

echo "[PSA] start desktop UI (Vite + Electron)"
echo "[PSA] 后端 http://127.0.0.1:18765"
echo "[PSA] 将打开登录页，请手动登录（默认账号 admin / admin）"
echo "[PSA] 关闭窗口或 Ctrl+C 结束界面（后端继续在本机运行）"
cd "$ROOT/apps/desktop"
if [[ -n "${ELECTRON_RUN_AS_NODE+x}" ]]; then
  unset ELECTRON_RUN_AS_NODE
fi
export PSA_SHOW_LOGIN=1
export VITE_PSA_SHOW_LOGIN=1
npm start
