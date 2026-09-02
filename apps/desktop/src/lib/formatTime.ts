/** 格式化录入/创建时间为本地可读字符串 */
export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

/** 相对时间，如「2 天前」 */
export function formatRelativeTime(iso?: string | null): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(diff)) return ''
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return formatDateTime(iso)
}

/** 未来相对时间，如「14 小时后」 */
export function formatFutureRelative(iso?: string | null): string {
  if (!iso) return ''
  const diff = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(diff)) return ''
  if (diff <= 0) return '即将运行'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '不到 1 分钟后'
  if (mins < 60) return `${mins} 分钟后`
  const hours = Math.floor(mins / 60)
  if (hours < 48) return `${hours} 小时后`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天后`
  return formatDateTime(iso)
}

