# Third-Party Notices

## NousResearch / Hermes Agent

- **名称**: hermes-agent
- **版本**: 0.20.6（以 `third_party/hermes-agent/pyproject.toml` 为准）
- **许可证**: MIT License（Copyright (c) 2025 Nous Research）
- **仓库内路径**: `third_party/hermes-agent/`
- **上游**: https://github.com/NousResearch/hermes-agent
- **用途**: Skills / Tools registry / MCP 客户端等能力，经 `server/app/hermes_bridge` 适配接入本项目 FastAPI Agent Runtime
- **说明**: 相关源码已拷贝（vendored）进本仓库；运行时通过 `sys.path` 引用上述目录，不依赖本机外部 Hermes 安装路径。完整 LICENSE 见 `third_party/hermes-agent/LICENSE`。
