---
name: PR 描述
description: 为 Pull Request 撰写清晰的 Summary 与 Test plan
triggers: [PR, pull request, 合并请求, PR描述, changelog]
permissions: [fs_read, fs_list]
allowed-tools: [fs_read, fs_list]
version: "1.0"
---
# PR 描述

撰写 PR 说明时输出 Markdown：
## Summary
- 1–3 条：改了什么、为什么

## Test plan
- [ ] 可勾选的验证步骤

可选：Breaking changes / 迁移说明 / 截图占位。
聚焦读者（审查者）需要的信息，避免复制整段 commit 历史。
