import { describe, expect, it } from 'vitest'
import { parseChecklistPreview } from './checklist'

describe('checklist preview', () => {
  it('extracts actionable numbered and bullet items', () => {
    const text = `待办：
1. 写周报
- 发邮件
* 更新文档`
    expect(parseChecklistPreview(text)).toEqual(['写周报', '发邮件', '更新文档'])
  })

  it('keeps todos and reminders, drops analysis bullets', () => {
    const text = `## 背景分析
- 项目周期较长
- 例如人力不足

## 待办
- [ ] 提交方案
- 跟进客户反馈
- 记得明天催进度

## 总结
- 整体可行
- 风险可控`
    const items = parseChecklistPreview(text)
    expect(items).toContain('提交方案')
    expect(items).toContain('跟进客户反馈')
    expect(items).toContain('记得明天催进度')
    expect(items).not.toContain('项目周期较长')
    expect(items).not.toContain('例如人力不足')
    expect(items).not.toContain('整体可行')
    expect(items).not.toContain('风险可控')
  })
})
