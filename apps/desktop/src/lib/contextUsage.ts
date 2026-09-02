/** 上下文用量展示辅助。 */

export type ContextUsageBreakdown = {
  system_prompt: number
  tools: number
  conversation: number
  mcp: number
  skills: number
}

export type ContextUsage = {
  used_tokens: number
  raw_tokens?: number
  limit_tokens: number
  percent: number
  message_count?: number
  max_messages?: number
  compressed?: boolean
  has_summary?: boolean
  near_limit?: boolean
  kept_messages?: number
  summarized_messages?: number
  breakdown?: Partial<ContextUsageBreakdown>
}

export const CONTEXT_USAGE_SEGMENTS = [
  { key: 'system_prompt', label: 'System Prompt', color: '#4C8DFF' },
  { key: 'tools', label: 'Tools', color: '#2EC9A0' },
  { key: 'conversation', label: 'Conversation', color: '#F5A524' },
  { key: 'mcp', label: 'MCP', color: '#A78BFA' },
  { key: 'skills', label: 'Skills', color: '#F472B6' },
] as const

export type ContextUsageSegmentKey = (typeof CONTEXT_USAGE_SEGMENTS)[number]['key']

const EMPTY_BREAKDOWN: ContextUsageBreakdown = {
  system_prompt: 0,
  tools: 0,
  conversation: 0,
  mcp: 0,
  skills: 0,
}

export function formatTokenCount(n: number): string {
  const v = Math.max(0, Number(n) || 0)
  if (v < 1000) return `${Math.round(v)}`
  if (v < 1000000) return `${(v / 1000).toFixed(1)}K`
  return `${(v / 1000000).toFixed(1)}M`
}

export function formatPercent(n: number): string {
  const v = Number.isFinite(n) ? Math.max(0, n) : 0
  return `${v.toFixed(1)}%`
}

export function formatContextUsageLabel(u: ContextUsage): string {
  const used = formatTokenCount(u.used_tokens)
  const limit = formatTokenCount(u.limit_tokens)
  return `${formatPercent(u.percent)} · ${used} / ${limit}`
}

export function formatContextUsageUsed(u: ContextUsage): string {
  return `已使用 ${formatTokenCount(u.used_tokens)} / ${formatTokenCount(u.limit_tokens)}`
}

export function contextUsageTitle(u: ContextUsage): string {
  const parts = [`已用约 ${u.used_tokens} / 上限 ${u.limit_tokens} tokens`]
  if (u.message_count != null && u.max_messages != null) {
    parts.push(`消息 ${u.message_count} / ${u.max_messages}`)
  }
  if (u.compressed || u.has_summary) {
    parts.push('较早对话已压缩为摘要')
  }
  if (u.raw_tokens != null && u.raw_tokens !== u.used_tokens) {
    parts.push(`压缩前约 ${u.raw_tokens} tokens`)
  }
  return parts.join(' · ')
}

export function resolveBreakdown(u: ContextUsage): ContextUsageBreakdown {
  const raw = u.breakdown || {}
  const next: ContextUsageBreakdown = {
    system_prompt: Math.max(0, Number(raw.system_prompt) || 0),
    tools: Math.max(0, Number(raw.tools) || 0),
    conversation: Math.max(0, Number(raw.conversation) || 0),
    mcp: Math.max(0, Number(raw.mcp) || 0),
    skills: Math.max(0, Number(raw.skills) || 0),
  }
  const sum = Object.values(next).reduce((a, b) => a + b, 0)
  if (sum <= 0 && u.used_tokens > 0) {
    return { ...EMPTY_BREAKDOWN, conversation: Math.max(0, u.used_tokens) }
  }
  return next
}

export type ContextUsageBarSegment = {
  key: ContextUsageSegmentKey
  label: string
  color: string
  tokens: number
  percent: number
}

export function contextUsageBarSegments(u: ContextUsage): ContextUsageBarSegment[] {
  const breakdown = resolveBreakdown(u)
  const limit = Math.max(1, Number(u.limit_tokens) || 1)
  return CONTEXT_USAGE_SEGMENTS.map((seg) => {
    const tokens = breakdown[seg.key]
    return {
      ...seg,
      tokens,
      percent: Math.max(0, (tokens / limit) * 100),
    }
  })
}

function numOrUndef(v: unknown): number | undefined {
  if (v == null || v === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

export function parseContextUsage(
  d: Record<string, unknown>,
  prev?: ContextUsage | null,
): ContextUsage {
  const breakdownRaw = d.breakdown
  const breakdown =
    breakdownRaw && typeof breakdownRaw === 'object'
      ? (breakdownRaw as Partial<ContextUsageBreakdown>)
      : prev?.breakdown
  return {
    used_tokens: Number(d.used_tokens ?? d.after_tokens ?? prev?.used_tokens) || 0,
    raw_tokens: numOrUndef(d.raw_tokens ?? d.before_tokens) ?? prev?.raw_tokens,
    limit_tokens: Number(d.limit_tokens ?? prev?.limit_tokens) || 32000,
    percent: Number.isFinite(Number(d.percent))
      ? Number(d.percent)
      : prev?.percent || 0,
    message_count: numOrUndef(d.message_count) ?? prev?.message_count,
    max_messages: numOrUndef(d.max_messages) ?? prev?.max_messages,
    compressed: d.compressed != null ? Boolean(d.compressed) : Boolean(prev?.compressed),
    has_summary: d.has_summary != null ? Boolean(d.has_summary) : Boolean(prev?.has_summary),
    near_limit: Boolean(d.near_limit ?? prev?.near_limit),
    kept_messages: numOrUndef(d.kept_messages) ?? prev?.kept_messages,
    summarized_messages: numOrUndef(d.summarized_messages) ?? prev?.summarized_messages,
    breakdown,
  }
}
