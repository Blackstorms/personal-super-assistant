# third_party

本目录存放已拷贝进仓库的第三方源码（vendoring），打包时随 sidecar 分发。

## hermes-agent

- **来源**: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)（MIT）
- **路径**: `third_party/hermes-agent/`
- **用途**: Skills / Tools registry / MCP 客户端等能力，经 `server/app/hermes_bridge` 适配接入
- **说明**: 不依赖本机外部路径；运行时由 `app.hermes_bridge.paths` 将本目录加入 `sys.path`

详见仓库根目录 `THIRD_PARTY_NOTICES.md` 与 `docs/Hermes集成说明.md`。
