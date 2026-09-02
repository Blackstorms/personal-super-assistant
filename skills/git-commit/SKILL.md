---
name: Git 提交说明
description: 根据变更生成规范、简洁的 commit message
triggers: [commit, 提交, git commit, 提交说明, message]
permissions: [fs_read, fs_list]
allowed-tools: [fs_read, fs_list]
version: "1.0"
---
# Git 提交说明

根据用户描述的 diff 或变更意图：
1. 优先 Conventional Commits：`type(scope): summary`
2. type 常用：feat / fix / docs / refactor / test / chore / perf
3. 标题 ≤72 字符，祈使语气，说明「为什么」而非堆砌文件名
4. 需要时附正文：动机、破坏性变更、关联 issue
5. 一次给出 1 个推荐 + 1–2 个备选
