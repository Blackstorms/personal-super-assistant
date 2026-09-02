#!/usr/bin/env bash
# 构建 FastAPI sidecar（PyInstaller）。产物放入 resources/sidecars/{platform-arch}/
# 内置 third_party/hermes-agent（vendored MIT），打包后无需外部 Hermes 路径。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="$ROOT/server"
HERMES="$ROOT/third_party/hermes-agent"
OUT_BASE="$ROOT/resources/sidecars"

if [[ ! -f "$HERMES/model_tools.py" ]]; then
  echo "[PSA] ERROR: missing vendored Hermes at $HERMES"
  exit 1
fi

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Darwin)
    if [[ "$ARCH" == "arm64" ]]; then
      PLAT="darwin-arm64"
      NAME="server-darwin-arm64"
    else
      PLAT="darwin-x64"
      NAME="server-darwin-x64"
    fi
    ;;
  Linux)
    PLAT="linux-x64"
    NAME="server-linux-x64"
    ;;
  *)
    echo "Unsupported OS: $OS (use build-sidecar.ps1 on Windows)"
    exit 1
    ;;
esac

DEST="$OUT_BASE/$PLAT"
mkdir -p "$DEST"

# Hermès on --paths can confuse analysis; keep only server on pathex for imports,
# and pass Hermes solely via --add-data.
ADD_HERMES="--add-data=${HERMES}:third_party/hermes-agent"
ADD_SCHEMA="--add-data=${ROOT}/resources/db:resources/db"
if [[ -d "$ROOT/skills" ]]; then
  ADD_SKILLS="--add-data=${ROOT}/skills:skills"
else
  ADD_SKILLS=""
fi

echo "[PSA] building sidecar → $DEST/$NAME (vendored Hermes)"
cd "$SERVER"
if [[ -d .venv312 ]]; then
  # shellcheck disable=SC1091
  source .venv312/bin/activate
elif [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[PSA] creating server/.venv"
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[PSA] wipe previous PyInstaller outputs..."
rm -rf build dist "${NAME}.spec" 2>/dev/null || true

echo "[PSA] installing server requirements + pyinstaller..."
pip install -q -U pip
pip install -q -r requirements.txt "pyinstaller>=6.0"

echo "[PSA] verifying imports before PyInstaller..."
python - <<'PY'
import importlib
for m in ("uvicorn", "fastapi", "starlette", "anyio"):
    mod = importlib.import_module(m)
    print(m, "OK", getattr(mod, "__file__", "?"))
from app.main import app
print("app.main OK", type(app))
PY

ADD_TIKTOKEN=""
if python -c "import tiktoken" >/dev/null 2>&1; then
  ADD_TIKTOKEN="--collect-all=tiktoken"
else
  echo "[PSA] tiktoken not installed; skip"
fi

COLLECT_ALL=(
  --collect-all=uvicorn
  --collect-all=fastapi
  --collect-all=starlette
  --collect-all=anyio
  --collect-all=click
  --collect-all=h11
  --collect-all=httptools
  --collect-all=websockets
  --collect-all=watchfiles
)

# shellcheck disable=SC2086
pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --noupx \
  --name "$NAME" \
  --paths "$SERVER" \
  $ADD_HERMES \
  $ADD_SCHEMA \
  $ADD_SKILLS \
  "${COLLECT_ALL[@]}" \
  --hidden-import=uvicorn \
  --hidden-import=uvicorn.logging \
  --hidden-import=uvicorn.loops \
  --hidden-import=uvicorn.loops.auto \
  --hidden-import=uvicorn.protocols \
  --hidden-import=uvicorn.protocols.http \
  --hidden-import=uvicorn.protocols.http.auto \
  --hidden-import=uvicorn.protocols.websockets.auto \
  --hidden-import=uvicorn.lifespan \
  --hidden-import=uvicorn.lifespan.on \
  --collect-submodules=app \
  --collect-data=certifi \
  --copy-metadata=uvicorn \
  --copy-metadata=fastapi \
  $ADD_TIKTOKEN \
  --console \
  sidecar_entry.py

BIN="dist/$NAME"
if [[ -f "$BIN" ]]; then
  cp "$BIN" "$DEST/$NAME"
  chmod +x "$DEST/$NAME"
  SIZE=$(wc -c < "$DEST/$NAME" | tr -d ' ')
  echo "[PSA] wrote $DEST/$NAME ($SIZE bytes)"
  if [[ "$SIZE" -lt 15000000 ]]; then
    echo "[PSA] ERROR: sidecar suspiciously small; deps likely missing"
    exit 1
  fi
else
  echo "[PSA] ERROR: expected $BIN"
  exit 1
fi

# brief smoke: start, hit health, kill
SMOKE_PORT=18775
export PSA_HOST=127.0.0.1 PSA_PORT="$SMOKE_PORT"
"$DEST/$NAME" >"/tmp/psa-sidecar-smoke.out" 2>"/tmp/psa-sidecar-smoke.err" &
SMOKE_PID=$!
ok=0
for _ in $(seq 1 45); do
  if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
    echo "[PSA] ERROR: sidecar exited early during smoke"
    cat /tmp/psa-sidecar-smoke.err /tmp/psa-sidecar-smoke.out || true
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${SMOKE_PORT}/api/v1/health" >/dev/null; then
    ok=1
    break
  fi
  sleep 1
done
kill "$SMOKE_PID" 2>/dev/null || true
wait "$SMOKE_PID" 2>/dev/null || true
if [[ "$ok" -ne 1 ]]; then
  echo "[PSA] ERROR: smoke health check failed"
  cat /tmp/psa-sidecar-smoke.err /tmp/psa-sidecar-smoke.out || true
  exit 1
fi
echo "[PSA] smoke OK"

mkdir -p "$ROOT/resources/hermes_home_template"
cat > "$ROOT/resources/hermes_home_template/README.md" <<'EOF'
# HERMES_HOME 模板

打包后运行时由后端在 `{PSA_DATA_DIR}/hermes_home` 自动创建。
Hermes Agent 相关源码已 vendored 至 `third_party/hermes-agent`，并由 sidecar 一并打包。

详见 docs/Hermes集成说明.md。
EOF

echo "[PSA] sidecar build done (vendored Hermes included)."
