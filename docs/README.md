# 文档索引

本目录为赛题一「个人超级助理（C/S 架构）」的交付文档。写作对照 [`AI-Coding大赛活动实施方案-v3.md`](./AI-Coding大赛活动实施方案-v3.md) 第六节「最终交付物标准」与第四节评分/加减分规则。

| 文档 | 对应大赛项 | 说明 |
|------|------------|------|
| [交付物清单.md](./交付物清单.md) | 第六节全部 7 项 | 压缩包结构、命名、验收对照、缺项风险 |
| [项目说明文档.md](./项目说明文档.md) | 1. 项目说明文档（≥1000 字） | 需求、架构、功能、难点、部署、教程 |
| [数据库配置说明.md](./数据库配置说明.md) | 3. 数据库相关文件与配置说明 | schema / 初始化 / 表实体 / 备份 |
| [构建产物说明.md](./构建产物说明.md) | 5. 可运行构建产物 | 交付包内产物清单与存放约定 |
| [三端打包说明.md](./三端打包说明.md) | 5 + 一键部署配套 | Windows x64 / macOS Intel / macOS ARM |
| [演示录屏清单.md](./演示录屏清单.md) | 7. 核心功能演示录屏 | 拍摄顺序与自检（MP4 由选手放入包根） |
| [测试报告.md](./测试报告.md) | 加分项：完整测试体系 | pytest + Vitest 范围与结果 |
| [Hermes集成说明.md](./Hermes集成说明.md) | 进阶：技能 / MCP 底座 | vendored Hermes 边界与降级 |
| [AI-Coding大赛活动实施方案-v3.md](./AI-Coding大赛活动实施方案-v3.md) | 赛题原文 | 评审对照用，非作品报告 |

源码侧配套（不在本目录，但属于交付包）：

- 工程源码：`apps/desktop/`、`server/`、`skills/`、`resources/`
- 一键安装：`scripts/install.sh`、`scripts/install.cmd`（Windows，内部调 `install.ps1`）
- 数据库脚本：`resources/db/schema.sql`、`resources/db/seed.sql`
- 许可证：仓库根 `THIRD_PARTY_NOTICES.md`

快速入口见仓库根 [`README.md`](../README.md)。
