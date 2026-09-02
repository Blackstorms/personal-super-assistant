# Sidecars

PyInstaller 产物按平台放入本目录子文件夹，由 Electron 主进程在打包态拉起。

```bash
# macOS / Linux（会把 third_party/hermes-agent 打进 sidecar）
./scripts/build-sidecar.sh
```

```bat
REM Windows（cmd / Git Bash；会绕过 PowerShell 执行策略）
scripts\build-sidecar.cmd
```

详见 `docs/Hermes集成说明.md`。
