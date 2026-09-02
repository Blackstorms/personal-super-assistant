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

# PyInstaller --add-data：macOS/Linux 用冒号分隔 src:dest
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
fi
pip install -q pyinstaller
# tiktoken 未装时 --copy-metadata 会直接失败；压缩路径本身有字符回退
ADD_TIKTOKEN=""
if python -c "import tiktoken" >/dev/null 2>&1; then
  ADD_TIKTOKEN="--collect-data=tiktoken"
else
  echo "[PSA] tiktoken not installed; skip collect-data (compress fallback OK)"
fi
# shellcheck disable=SC2086
pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name "$NAME" \
  --paths "$SERVER" \
  --paths "$HERMES" \
  $ADD_HERMES \
  $ADD_SCHEMA \
  $ADD_SKILLS \
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
  $ADD_TIKTOKEN \
  --console \
  sidecar_entry.py

# PyInstaller 默认输出到 dist/
BIN="dist/$NAME"
if [[ -f "$BIN" ]]; then
  cp "$BIN" "$DEST/$NAME"
  chmod +x "$DEST/$NAME"
  echo "[PSA] wrote $DEST/$NAME"
else
  echo "[PSA] ERROR: expected $BIN"
  exit 1
fi

mkdir -p "$ROOT/resources/hermes_home_template"
cat > "$ROOT/resources/hermes_home_template/README.md" <<'EOF'
# HERMES_HOME 模板

打包后运行时由后端在 `{PSA_DATA_DIR}/hermes_home` 自动创建。
Hermes Agent 相关源码已 vendored 至 `third_party/hermes-agent`，并由 sidecar 一并打包。

详见 docs/Hermes集成说明.md。
EOF

echo "[PSA] sidecar build done (vendored Hermes included)."
