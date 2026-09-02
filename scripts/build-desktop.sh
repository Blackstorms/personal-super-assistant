#!/usr/bin/env bash
# 构建说明：在本机架构生成桌面产物；sidecar 需另用 PyInstaller 按目标 arch 构建
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OS="$(uname -s)"
ARCH="$(uname -m)"
echo "Building desktop for $OS $ARCH"
cd "$ROOT/apps/desktop"
npm install
npm run build || true
# electron-builder 需要本机环境；文档中说明三端产物目录约定
npx electron-builder --dir || echo "electron-builder skipped/failed — see docs for cross-build"
mkdir -p "$ROOT/resources/sidecars"
echo "Place PyInstaller outputs under resources/sidecars/{darwin-arm64,darwin-x64,win32-x64}/"
