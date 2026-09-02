# Hermes 集成说明

> 本文是技能 / MCP 进阶底座的技术附录，不替代 [`项目说明文档.md`](./项目说明文档.md)。交付对照见 [`交付物清单.md`](./交付物清单.md)。

Personal Super Assistant（PSA）将 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 中 Skills / Tools / MCP 相关源码**拷贝**到仓库 `third_party/hermes-agent/`，经 `hermes_bridge` 适配接入 FastAPI Agent Runtime。**不**依赖本机外部 Hermes 路径，也**不**把 Hermes CLI/Gateway/TUI 打进启动主路径。

引入目的是**参考 Hermes 架构**（Tools registry、MCP 连接池、Skills），不是平行维护两套业务实现。

## 源码位置

| 项 | 路径 |
|----|------|
| Vendored Hermes | `third_party/hermes-agent/`（须含 `model_tools.py` 与 `tools/`） |
| 运行时数据 `HERMES_HOME` | `{PSA_DATA_DIR}/hermes_home`（后端自动创建） |

缺失 vendored 目录时桥接降级：内置 `SkillRegistry` + 可选官方 `mcp` SDK 仍可工作，但无 Hermes toolsets / Hub / 斜杠堆叠。

## 职责边界

| 层 | 负责 | 不负责 |
|----|------|--------|
| PSA | 鉴权、SSE、确认闸、审计、白名单 `fs_*`、`knowledge_search`、`schedule_task`、调度器、SQLite、Workspace/Expert | Hermes CLI/Gateway |
| hermes_bridge | sys.path、HERMES_HOME、DB↔MCP 映射、toolset 过滤、dispatch | 业务 UI |
| Vendored Hermes | Tools registry、MCP 连接池、Skills 扫描/执行 | Electron、本地 Token |

## 热路径约定（禁止双写）

- **Hermes on**：对话工具面中的 Skills / MCP / toolsets **只**经 `hermes_bridge`；`mcp_manager.openai_tools` 不并入同一张对话工具表。
- **Hermes off**：才用 `SkillRegistry` + 官方 MCP SDK 缓存降级；降级路径只修稳定性，不加 Hub/toolsets 对等功能。
- **新 Skills/MCP 能力优先接到 Hermes 侧**，禁止在 `SkillRegistry` 与 `hermes_bridge` 各实现一份。
- MCP OAuth 元数据字段已从 PSA API/schema 移除；如需 OAuth 请在 Hermes/MCP 服务端自行配置，勿在 PSA 双写。

## 健康检查

`GET /api/v1/health` 的 `hermes` 字段包含：

- `available` / `model_tools_loaded`
- `root` / `home`（`root` 指向仓库内 `third_party/hermes-agent`）
- `mcp_tools_count` / `mcp_tools`
- `missing_deps` / `error`

关于页与设置页「Hermes Toolsets」会展示上述状态。启动失败时写入 `app_settings.hermes_last_error`。

## 降级行为

| Hermes | Skills | MCP | 文件工具 |
|--------|--------|-----|----------|
| on | `skills_list` / `skill_view` / `skill_manage` | `register_mcp_servers` → `mcp__*` | 仅 PSA `fs_*`（白名单） |
| off | `describe_skill` / `run_skill`（指引） | 官方 SDK / 缓存 | `fs_*` |

高风险工具（`fs_write`、`write_file`、`skill_manage` 写操作、部分 MCP）统一走 PSA SSE `tool_confirm`，禁止静默执行。

## 交付注意

PyInstaller sidecar **包含** `third_party/hermes-agent`（见 `scripts/build-sidecar.sh` / `.ps1`）。安装包可离线使用完整 Skills/MCP toolsets，无需设置外部路径。

## 录屏检查项

与 [`演示录屏清单.md`](./演示录屏清单.md) 第 8–9 步对齐：

1. 设置 → 关于：`/health` 中 `hermes.available: true`（sidecar / 开发态均应 vendored 成功）
2. 设置 → Hermes 工具组：启停 toolset（terminal 等可默认关闭）
3. 对话斜杠 `/file-summarize`（可演示堆叠 `/skill-a /skill-b`）
4. 连接器 Discover → 重载 → 对话出现 `mcp__*` 工具卡片
5. 技能页 Hub / skills.sh 搜索（有网络则安装一条，无网络则展示入口即可）
