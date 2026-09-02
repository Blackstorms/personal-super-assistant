---
name: 文本整理
description: 整理杂乱文本：去噪、分段、结构化输出
triggers: [整理, 润色, 结构化, organize, rewrite]
permissions: []
version: "1.0"
---
# 文本整理

对用户粘贴的杂乱文本（可先 `describe_skill` 或 `/text-organize`）：
1. 去除明显噪声与重复
2. 按主题分段
3. 输出「整理后正文」与「结构提纲」
4. 保留原意，不擅自增删事实
