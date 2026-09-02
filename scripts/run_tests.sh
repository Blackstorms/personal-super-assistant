#!/usr/bin/env bash
# 一键跑前后端测试
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/server"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
export PYTHONPATH="$ROOT/server"
python -m pytest -q
cd "$ROOT/apps/desktop"
if [[ -d node_modules ]]; then
  npm test
else
  echo "skip frontend tests (npm install first)"
fi
echo "ALL TESTS DONE"
