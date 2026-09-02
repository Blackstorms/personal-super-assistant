---
name: 本地文件摘要
description: 对白名单内文本文件做要点摘要，适合快速了解文档内容
triggers: [摘要, 总结, 文件, summarize, summary]
permissions: [fs_read, fs_list]
allowed-tools: [fs_read, fs_list]
version: "1.0"
---
# 本地文件摘要

当用户希望总结某个本地文件时：
1. 若尚未加载本技能全文，先确认已通过 `describe_skill` 或 `/file-summarize` 取得指引
2. 使用 `fs_read` 读取白名单路径下的文件（必要时先 `fs_list`）
3. 提炼出 3-7 条要点与一段总览
4. 若文件过长，优先覆盖开头与关键段落
5. 末尾列出「未覆盖章节 / 建议再读」
