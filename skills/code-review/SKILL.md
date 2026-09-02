---
name: 代码审查
description: 按严重级别审查代码变更，给出可执行修复建议（对齐热门 code-review）
triggers: [代码审查, review, code review, 评审, CR]
permissions: [fs_read, fs_list]
allowed-tools: [fs_read, fs_list]
version: "1.0"
---
# 代码审查

审查用户给出的 diff / 文件时：
1. 需要时用 `fs_read`/`fs_list` 读取相关上下文
2. 按严重级别输出：
   - 🔴 必须修（正确性、安全、数据丢失）
   - 🟠 应当修（性能、可维护性、边界）
   - 🟡 建议（风格、命名、测试缺口）
3. 每条包含：位置 → 问题 → 为什么 → 建议改法（可给短补丁示意）
4. 先总结「整体风险与是否建议合并」再列明细
5. 不因风格偏好刷屏；聚焦真实缺陷
