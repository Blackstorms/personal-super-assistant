# 内置技能包（约 20 个）

启动时由后端 `SkillRegistry.reload()` 扫描本目录下的 `*/SKILL.md` 写入 SQLite。对话中可用 `/skill-id` 斜杠激活，或由 Agent 经 `describe_skill` 渐进加载。

| ID | 名称 | 参考类别 |
|----|------|----------|
| `file-summarize` | 本地文件摘要 | 文档 |
| `text-organize` | 文本整理 | 写作 |
| `todo-draft` | 待办草稿 | 效率 |
| `research-brief` | 调研简报 | research |
| `frontend-design` | 前端界面设计 | frontend-design |
| `code-review` | 代码审查 | code-review |
| `skill-creator` | 技能创作 | skill-creator |
| `translate` | 中英互译 | 语言 |
| `meeting-notes` | 会议纪要 | 会议摘要 |
| `email-draft` | 邮件起草 | 办公 |
| `git-commit` | Git 提交说明 | 工程 |
| `pr-description` | PR 描述 | 工程 |
| `prompt-optimize` | 提示词优化 | Agent |
| `brainstorm` | 头脑风暴 | brainstorming |
| `compare-options` | 方案对比 | 决策 |
| `rewrite-tone` | 语气改写 | 写作 |
| `explain-simple` | 通俗讲解 | teach |
| `daily-plan` | 日程规划 | 效率 |
| `diagnose-bug` | 问题诊断 | diagnosing-bugs |
| `copywriting` | 营销文案 | copywriting |

说明：内容为本项目自写的工作流指引，对齐 [skills.sh](https://skills.sh/) 等生态中的常见技能类别，非第三方 SKILL.md 原文拷贝。可在「技能」页继续从 Hermes Hub / skills.sh 导入更多。
