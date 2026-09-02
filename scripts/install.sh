#!/usr/bin/env bash
# macOS / Linux 一键安装与启动脚本
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
npm install

echo "[PSA] start backend (background)"
cd "$ROOT/server"
nohup python -m uvicorn app.main:app --host 127.0.0.1 --port 18765 > "$ROOT/server/uvicorn.log" 2>&1 &
echo $! > "$ROOT/server/uvicorn.pid"
sleep 2
curl -sf http://127.0.0.1:18765/api/v1/health >/dev/null && echo "[PSA] backend healthy"

echo "[PSA] Done. Start UI with:"
echo "  cd $ROOT/apps/desktop && npm run electron:dev"
echo "Or open web UI: cd apps/desktop && npm run dev  (http://127.0.0.1:5173)"
