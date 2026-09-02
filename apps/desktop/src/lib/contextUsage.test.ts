import { describe, expect, it } from 'vitest'
import {
  contextUsageBarSegments,
  formatContextUsageUsed,
  formatPercent,
  formatTokenCount,
  parseContextUsage,
  resolveBreakdown,
} from './contextUsage'

describe('context usage display', () => {
  it('formats token counts like 41.5K / 192.0K', () => {
    expect(formatTokenCount(41500)).toBe('41.5K')
    expect(formatTokenCount(192000)).toBe('192.0K')
    expect(formatTokenCount(12)).toBe('12')
  })

  it('formats percent with one decimal', () => {
    expect(formatPercent(21.6)).toBe('21.6%')
    expect(formatPercent(8)).toBe('8.0%')
  })

  it('formats used line', () => {
    expect(
      formatContextUsageUsed({ used_tokens: 41500, limit_tokens: 192000, percent: 21.6 }),
    ).toBe('已使用 41.5K / 192.0K')
  })

  it('falls back to conversation when breakdown is empty', () => {
    const b = resolveBreakdown({ used_tokens: 1200, limit_tokens: 8000, percent: 15 })
    expect(b.conversation).toBe(1200)
    expect(b.tools).toBe(0)
  })

  it('builds bar segments against the limit', () => {
    const segs = contextUsageBarSegments({
      used_tokens: 1000,
      limit_tokens: 8000,
      percent: 12.5,
      breakdown: { system_prompt: 200, tools: 300, conversation: 500, mcp: 0, skills: 0 },
    })
    const byKey = Object.fromEntries(segs.map((s) => [s.key, s]))
    expect(byKey.system_prompt.percent).toBeCloseTo(2.5)
    expect(byKey.conversation.percent).toBeCloseTo(6.25)
    expect(byKey.mcp.tokens).toBe(0)
  })

  it('parses API payload breakdown', () => {
    const u = parseContextUsage({
      used_tokens: 10,
      limit_tokens: 8000,
      percent: 0.1,
      breakdown: { conversation: 10, tools: 0 },
    })
    expect(u.breakdown?.conversation).toBe(10)
  })
})
