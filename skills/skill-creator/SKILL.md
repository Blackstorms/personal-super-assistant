---
name: 技能创作
description: 指导编写符合本项目约定的 SKILL.md 技能包（对齐热门 skill-creator）
triggers: [创建技能, 写技能, skill creator, SKILL.md, 新技能]
permissions: []
version: "1.0"
---
# 技能创作

帮助用户新增本地技能时遵循：
1. 目录：`skills/<skill-id>/SKILL.md`，`skill-id` 仅字母数字下划线连字符
2. Frontmatter 必填：`name`、`description`、`triggers`、`permissions`/`allowed-tools`、`version`
3. 正文写**可执行工作流**（步骤、输出格式、何时调用工具），避免空话
4. 权限最小化：只需读文件才声明 `fs_read`/`fs_list`
5. 输出完整 SKILL.md 草稿，并说明斜杠调用方式 `/skill-id`
6. 提醒：技能靠 `describe_skill` 渐进加载，description 要便于匹配
