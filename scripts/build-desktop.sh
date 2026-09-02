#!/usr/bin/env bash
# One-click desktop installer for the current Mac/Linux machine.
# Requires the matching sidecar (see scripts/build-sidecar.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/apps/desktop"

export ELECTRON_MIRROR="${ELECTRON_MIRROR:-https://npmmirror.com/mirrors/electron/}"
export ELECTRON_BUILDER_BINARIES_MIRROR="${ELECTRON_BUILDER_BINARIES_MIRROR:-https://npmmirror.com/mirrors/electron-builder-binaries/}"

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Darwin)
    if [[ "$ARCH" == "arm64" ]]; then
      PLAT="darwin-arm64"
      SIDECAR="$ROOT/resources/sidecars/darwin-arm64/server-darwin-arm64"
      NPM_SCRIPT="electron:build:mac"
    else
      PLAT="darwin-x64"
      SIDECAR="$ROOT/resources/sidecars/darwin-x64/server-darwin-x64"
      NPM_SCRIPT="electron:build:mac:x64"
    fi
    ;;
  Linux)
    echo "[PSA] Linux is not a contest target. Use build-desktop.cmd on Windows, or this script on macOS."
    exit 1
    ;;
  *)
    echo "[PSA] Unsupported OS: $OS (use scripts/build-desktop.cmd on Windows)"
    exit 1
    ;;
esac

# shellcheck source=lib/ensure-node.sh
. "$ROOT/scripts/lib/ensure-node.sh"
psa_ensure_npm

echo "[PSA] desktop build for $PLAT"
if [[ ! -f "$SIDECAR" ]]; then
  echo "[PSA] ERROR: missing sidecar: $SIDECAR"
  echo "[PSA] Run ./scripts/build-sidecar.sh first, then retry."
  exit 1
fi

cd "$DESKTOP"
npm install
npm run "$NPM_SCRIPT"

echo "[PSA] done. Installers are under $DESKTOP/release/"
ls -lh "$DESKTOP/release"/*.{dmg,zip,exe} 2>/dev/null || ls -lh "$DESKTOP/release" || true
