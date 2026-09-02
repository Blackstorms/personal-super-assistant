/**
 * 审计舱展示：优先使用 API 返回的 labels，本地兜底中文标签。
 */
export type AuditLabels = {
  tool?: { id: string; label: string; description?: string }
  source?: { id: string; label: string; description?: string }
  confirm_status?: { id: string; label: string; description?: string }
  risk?: { id: string; label: string; description?: string }
  status?: { label: string }
  summary?: string
  arguments_hint?: Array<{ key: string; label: string; value: string }>
}

export type AuditItem = {
  id: string
  name: string
  source: string
  duration_ms: number
  confirm_status: string
  created_at: string
  is_error: boolean
  arguments?: unknown
  result?: unknown
  labels?: AuditLabels
}

const FALLBACK_TOOL: Record<string, string> = {
  fs_list: '列出目录',
  fs_read: '读取文件',
  fs_write: '写入文件',
  current_time: '当前时间',
  describe_skill: '加载技能说明',
  run_skill: '运行技能',
}

const FALLBACK_SOURCE: Record<string, string> = {
  builtin_fs: '内置文件工具',
  builtin_time: '当前时间',
  skill: '技能系统',
  mcp: 'MCP 连接器',
  error: '执行异常',
}

const FALLBACK_CONFIRM: Record<string, string> = {
  none: '无需确认',
  approved: '用户已确认',
  rejected: '用户已拒绝',
}

export function toolLabel(item: AuditItem): string {
  return item.labels?.tool?.label || FALLBACK_TOOL[item.name] || item.name
}

export function sourceLabel(item: AuditItem): string {
  return item.labels?.source?.label || FALLBACK_SOURCE[item.source] || item.source
}

export function confirmLabel(item: AuditItem): string {
  return item.labels?.confirm_status?.label || FALLBACK_CONFIRM[item.confirm_status] || item.confirm_status
}

export function statusLabel(item: AuditItem): string {
  if (item.labels?.status?.label) return item.labels.status.label
  if (item.confirm_status === 'rejected') return '已取消'
  return item.is_error ? '失败' : '成功'
}

export function formatAuditDetail(item: AuditItem): string {
  const labels = item.labels
  const lines: string[] = []

  if (labels?.summary) {
    lines.push(`摘要：${labels.summary}`)
    lines.push('')
  }

  lines.push('【中文说明】')
  lines.push(`工具：${toolLabel(item)}（${item.name}）`)
  if (labels?.tool?.description) lines.push(`说明：${labels.tool.description}`)
  lines.push(`来源：${sourceLabel(item)}（${item.source}）`)
  if (labels?.source?.description) lines.push(`来源说明：${labels.source.description}`)
  lines.push(`确认：${confirmLabel(item)}（${item.confirm_status}）`)
  if (labels?.confirm_status?.description) lines.push(`确认说明：${labels.confirm_status.description}`)
  if (labels?.risk?.label) {
    lines.push(`风险：${labels.risk.label}（${labels.risk.id}）`)
    if (labels.risk.description) lines.push(`风险说明：${labels.risk.description}`)
  }
  lines.push(`状态：${statusLabel(item)} · 耗时：${item.duration_ms}ms`)
  lines.push(`时间：${item.created_at}`)

  if (labels?.arguments_hint?.length) {
    lines.push('')
    lines.push('【入参摘要】')
    for (const h of labels.arguments_hint) {
      lines.push(`- ${h.label}：${h.value}`)
    }
  }

  lines.push('')
  lines.push('【原始数据】')
  lines.push(
    JSON.stringify(
      {
        name: item.name,
        source: item.source,
        confirm_status: item.confirm_status,
        duration_ms: item.duration_ms,
        is_error: item.is_error,
        arguments: item.arguments,
        result: item.result,
      },
      null,
      2,
    ),
  )

  return lines.join('\n')
}
