# Personal Super Assistant

前后端分离的桌面个人超级助理（Electron + React + TS / Python FastAPI）。赛题一交付文档从 [`docs/README.md`](docs/README.md) 进入，压缩包对照见 [`docs/交付物清单.md`](docs/交付物清单.md)。

## 快速开始

```bash
# macOS / Linux：安装依赖并启动后端 + 桌面端
chmod +x scripts/*.sh
./scripts/install.sh
```

Windows：`scripts\install.cmd`（内部调用 `install.ps1` 并绕过执行策略）。脚本会检测 Python/Node、安装依赖、拉起 FastAPI（`/health` 检查）并打开 Electron 窗口。默认账号 `admin / admin`。

仅 Web UI（后端已由 install 拉起时）：

```bash
cd apps/desktop && npm run dev   # http://127.0.0.1:5173
```

侧栏绿点表示后端（`127.0.0.1:18765`）正常；红点时按钮调用会失败，可点页面顶部「重试连接 / 重启后端」。

### 常见问题

桌面依赖与打包默认走 npmmirror（见 `apps/desktop/.npmrc`）。若 `electron-builder` 仍从 GitHub 下载 `electron-v*-darwin-*.zip`，先中断再导出镜像后重打；Apple Silicon 可用 `npm run electron:build:mac` 只出 arm64。

若 `npm run electron:dev` 报 `Electron failed to install correctly`，多半是 Electron 二进制未下完（官方源超时）。可执行：

```bash
cd apps/desktop
rm -rf node_modules/electron
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
npm install electron@33.2.0 --save-dev
```

若报 `No module named uvicorn`：请用 `./scripts/install.sh` 创建 `server/.venv`；开发态会优先用该虚拟环境启动后端。

### 联网搜索

对话内置 `web_search`。推荐配置 **Syncotech HTTP API**（`server/.env`，已 gitignore）：

```bash
PSA_WEB_SEARCH_PROVIDER=api
PSA_WEB_SEARCH_API_URL=https://ogw.syncotechai.com/websearch/search
PSA_WEB_SEARCH_API_KEY=你的密钥
```

未配置 API 时：自动级联 **Bing → DuckDuckGo**；也可设 `TAVILY_API_KEY`。
打包后请在「设置 → 联网搜索」填写密钥（会写入 `~/.personal-super-assistant/`，不会打进安装包）。
须走系统代理时：`PSA_WEB_SEARCH_TRUST_ENV=1`。

若在 Cursor / 部分 IDE 终端里 Electron 启动异常（`app.whenReady` 为 undefined），多半是环境变量 `ELECTRON_RUN_AS_NODE=1`；本项目的 `electron:dev` 脚本已自动取消该变量。

## 结构

- `apps/desktop` — Electron 客户端
- `server` — FastAPI 后端（LLM / Agent / Skills / MCP / Memory / Knowledge / Audit / Checklist）
- `skills` — 内置技能包
- `resources/db` — schema.sql
- `docs` — 交付清单、项目说明、数据库/构建/录屏/测试（见 [docs/README.md](docs/README.md)）
- `third_party/hermes-agent/` — 已拷贝进仓库的 Hermes 相关源码（MIT）
- `THIRD_PARTY_NOTICES.md` — 第三方许可证声明

### Hermes（内置）

Skills / Tools / MCP 相关逻辑参考 Hermes Agent，源码已拷贝到 `third_party/hermes-agent/`，经 `hermes_bridge` 接入；**不依赖**本机外部路径。缺失该目录时自动降级为内置 Skills/MCP。详见 [`docs/Hermes集成说明.md`](docs/Hermes集成说明.md)。

## 打包与测试

- 安装包 / sidecar：[`docs/三端打包说明.md`](docs/三端打包说明.md)、[`docs/构建产物说明.md`](docs/构建产物说明.md)
- 一键测试：`./scripts/run_tests.sh`，报告见 [`docs/测试报告.md`](docs/测试报告.md)
- Sidecar **包含** vendored Hermes，打包后可离线使用完整 Skills/MCP toolsets。
