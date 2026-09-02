/** 前端清单预览：仅待办 / 提醒等可执行项（与后端规则对齐）。 */

const ACTION =
  /^(完成|实现|编写|撰写|写|发|发送|回复|更新|修改|修复|检查|确认|核实|联系|通知|准备|提交|合并|部署|发布|测试|验证|同步|整理|归档|备份|删除|添加|新增|创建|开会|约|安排|处理|跟进|催|购买|下单|安装|配置|对接|迁移|重构|review|fix|add|update|send|check|call|schedule|deploy|test|merge|create|write|reply|remind)/i

const REMINDER = /(记得|别忘|提醒|截止|ddl|deadline|明天|后天|下周|本周|今日|今晚|asap|urgent|优先级|p[0-2]\b|todo|待办|需要|必须|务必)/i

const NOISE = /^(例如|比如|如下|如上|总之|综上|因此|所以|因为|如果|首先|其次|再次|最后|另外|此外|注[:：]|说明[:：]|注意[:：]|提示[:：]|优点|缺点|背景|结论|摘要|总结)/i

const SECTION_TODO = /(待办|任务|清单|todo|checklist|提醒|下一步|action\s*items?|to-?do|跟进|计划)/i
const SECTION_SKIP = /(总结|结论|背景|分析|原因|优缺点|对比|说明|注意|参考|摘要|概述)/i

function isActionable(content: string, inTodoSection: boolean): boolean {
  const c = content.trim()
  if (!c || c.length < 2 || c.length > 200) return false
  if (NOISE.test(c)) return false
  if (ACTION.test(c) || REMINDER.test(c)) return true
  if (inTodoSection && c.length <= 80) return true
  return false
}

export function parseChecklistPreview(text: string): string[] {
  const items: string[] = []
  let inTodo = false
  let inSkip = false

  for (const line of text.split('\n')) {
    const heading = line.match(/^\s{0,3}#{1,3}\s+(.+)$/)
    if (heading) {
      const t = heading[1].trim()
      inTodo = SECTION_TODO.test(t)
      inSkip = SECTION_SKIP.test(t) && !inTodo
      continue
    }

    if (inSkip) continue

    const checkbox = line.match(/^\s*[-*]\s+\[[ xX]\]\s+(.+)$/)
    if (checkbox?.[1]) {
      items.push(checkbox[1].trim())
      continue
    }

    const bullet =
      line.match(/^\s*[-*]\s+(.+)$/) || line.match(/^\s*\d+[\.\)、]\s*(.+)$/)
    if (bullet?.[1]) {
      const c = bullet[1].trim()
      if (isActionable(c, inTodo)) items.push(c)
    }
  }

  return [...new Set(items)]
}
