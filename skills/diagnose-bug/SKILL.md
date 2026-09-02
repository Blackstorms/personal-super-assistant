---
name: 问题诊断
description: 系统化排查缺陷：复现→假设→验证→修复（对齐 diagnosing-bugs / systematic-debugging）
triggers: [排查, 诊断, debug, bug, 报错, 不工作]
permissions: [fs_read, fs_list]
allowed-tools: [fs_read, fs_list]
version: "1.0"
---
# 问题诊断

面对报错或异常行为：
1. **复现**：期望 vs 实际；最小复现步骤
2. **收集**：错误信息、最近变更、环境差异
3. **假设**：列出 2–4 个可能根因并排序
4. **验证**：每条假设对应最小验证动作（读日志、读相关文件、对比配置）
5. **修复**：给最小修复方案 + 回归检查点
禁止一上来大范围重写；先定位再改。需要时用 `fs_read` 查看相关代码。
