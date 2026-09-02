---
name: 待办草稿
description: 把自然语言需求整理为清晰的待办清单条目
triggers: [待办, 清单, todo, 任务, checklist]
permissions: []
version: "1.0"
---
# 待办草稿

将用户描述拆成可执行待办（可先 `describe_skill` 或使用 `/todo-draft`）：
- 使用 `- [ ]` 清单格式
- 每条一事，动词开头
- 必要时标注优先级（P0/P1/P2）与预估耗时
- 可用 `run_skill` 传入原始需求文本以巩固上下文
