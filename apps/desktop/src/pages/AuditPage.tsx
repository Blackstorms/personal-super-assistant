/**
 * 审计舱：工具调用记录列表、筛选、回放与导出。
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../lib/api'
import {
  appendScopeQuery,
  filterSessionsByScope,
  isStandaloneScope,
  isWorkspaceScope,
  scopeBodyForExport,
  scopeForSessionPick,
  type ModuleScopeId,
} from '../lib/moduleScope'
import {
  confirmLabel,
  formatAuditDetail,
  sourceLabel,
  statusLabel,
  toolLabel,
  type AuditItem,
} from '../lib/auditLabels'
import { formatDateTime, formatRelativeTime } from '../lib/formatTime'
import { useAppStore } from '../stores/app'
import Modal from '../components/Modal'
import SessionPickTree, { useSessionPickData } from '../components/SessionPickTree'
import WorkspaceScopeLayout from '../components/WorkspaceScopeLayout'

function statusClass(item: AuditItem): string {
  const label = statusLabel(item)
  if (item.is_error || label === '失败') return 'bad'
  if (item.confirm_status === 'rejected' || label === '已取消') return 'warn'
  return 'ok'
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export default function AuditPage() {
  const { sessionId } = useAppStore()
  const [scopeId, setScopeId] = useState<ModuleScopeId>(null)
  const [items, setItems] = useState<AuditItem[]>([])
  const [loading, setLoading] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailTitle, setDetailTitle] = useState('回放')
  const [detail, setDetail] = useState('')
  const [nameFilter, setNameFilter] = useState('')
  const [filterSessionId, setFilterSessionId] = useState('')
  const [sessionModalOpen, setSessionModalOpen] = useState(false)
  const [sessionFilter, setSessionFilter] = useState('')
  const [pickedSessionTitle, setPickedSessionTitle] = useState('')
  const { load: loadSessionsForPick } = useSessionPickData()

  const load = async () => {
    setLoading(true)
    try {
      const qs = new URLSearchParams()
      appendScopeQuery(qs, scopeId)
      if (filterSessionId) qs.set('session_id', filterSessionId)
      if (nameFilter.trim()) qs.set('name', nameFilter.trim())
      const data = await apiRequest<{ items: AuditItem[] }>('GET', `/api/v1/audit/tool-calls?${qs}`)
      setItems(data.items)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load().catch(console.error)
  }, [scopeId, filterSessionId])

  const openSessionPicker = () => {
    setSessionFilter('')
    setSessionModalOpen(true)
    void loadSessionsForPick().then((list) => {
      const scoped = filterSessionsByScope(list, scopeId)
      const initial =
        (filterSessionId && scoped.some((s) => s.id === filterSessionId) && filterSessionId) ||
        (sessionId && scoped.some((s) => s.id === sessionId) && sessionId) ||
        scoped[0]?.id ||
        ''
      setFilterSessionId(initial)
      const hit = scoped.find((s) => s.id === initial)
      setPickedSessionTitle(hit?.title || '')
    })
  }

  const applySessionFilter = () => {
    setSessionModalOpen(false)
    void load()
  }

  const clearSessionFilter = () => {
    setFilterSessionId('')
    setPickedSessionTitle('')
  }

  const exportAudit = async (format: 'markdown' | 'json') => {
    const text = await apiRequest('POST', '/api/v1/audit/tool-calls/export', {
      ...scopeBodyForExport(scopeId),
      format,
    })
    setDetailTitle(format === 'markdown' ? '导出 Markdown' : '导出 JSON')
    setDetail(typeof text === 'string' ? text : JSON.stringify(text, null, 2))
    setDetailOpen(true)
  }

  const replay = async (a: AuditItem) => {
    const d = await apiRequest<AuditItem>('GET', `/api/v1/audit/tool-calls/${a.id}`)
    setDetailTitle(`${toolLabel(d)} · 回放`)
    setDetail(formatAuditDetail(d))
    setDetailOpen(true)
  }

  return (
    <>
      <WorkspaceScopeLayout title="审计舱" scopeId={scopeId} onScopeChange={setScopeId}>
        <div className="audit-page">
          <header className="audit-head">
            <div className="audit-head-copy">
              <h3 className="audit-title">工具调用</h3>
              <p className="audit-desc">记录工具调用、入参结果与确认状态，支持回放与导出。</p>
            </div>
            <div className="audit-head-actions">
              <button type="button" className="ghost sm" onClick={() => void exportAudit('markdown')}>
                导出 MD
              </button>
              <button type="button" className="ghost sm" onClick={() => void exportAudit('json')}>
                导出 JSON
              </button>
            </div>
          </header>

          <div className="audit-toolbar">
            <input
              className="audit-search"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
              placeholder="按工具 ID 筛选"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void load()
                }
              }}
            />
            <button type="button" className="ghost sm" onClick={openSessionPicker}>
              {filterSessionId ? '更换会话' : '选择会话'}
            </button>
            {filterSessionId ? (
              <button type="button" className="audit-session-chip" onClick={clearSessionFilter} title="清除会话筛选">
                <span>{pickedSessionTitle || filterSessionId.slice(0, 8)}</span>
                <span aria-hidden>×</span>
              </button>
            ) : null}
          </div>

          <div className="audit-list">
            {loading && items.length === 0 ? (
              <div className="audit-empty muted">加载中…</div>
            ) : items.length === 0 ? (
              <div className="audit-empty muted">
                当前范围暂无审计记录。在对话中调用工具后会出现在这里；也可切换左侧「全部」或「独立任务」。
              </div>
            ) : (
              items.map((a) => {
                const st = statusClass(a)
                return (
                  <article key={a.id} className={`audit-card status-${st}`}>
                    <div className="audit-card-main">
                      <div className="audit-card-top">
                        <div className="audit-tool">
                          <strong>{toolLabel(a)}</strong>
                          <code className="audit-tool-id">{a.name}</code>
                        </div>
                      </div>
                      {a.labels?.tool?.description || a.labels?.summary ? (
                        <p className="audit-card-desc">
                          {a.labels?.summary || a.labels?.tool?.description}
                        </p>
                      ) : null}
                      <div className="audit-meta">
                        <span title={a.created_at}>{formatRelativeTime(a.created_at) || formatDateTime(a.created_at)}</span>
                        <span>{sourceLabel(a)}</span>
                        <span>{formatDuration(a.duration_ms)}</span>
                        <span>{confirmLabel(a)}</span>
                      </div>
                    </div>
                    <div className="audit-card-aside">
                      <span className={`audit-status ${st}`}>{statusLabel(a)}</span>
                      <button type="button" className="audit-replay" onClick={() => void replay(a)}>
                        回放
                      </button>
                    </div>
                  </article>
                )
              })
            )}
          </div>
        </div>
      </WorkspaceScopeLayout>

      <Modal
        open={detailOpen}
        wide
        title={detailTitle}
        onClose={() => setDetailOpen(false)}
        footer={
          <button type="button" className="primary" onClick={() => setDetailOpen(false)}>
            关闭
          </button>
        }
      >
        <pre className="audit-detail-pre">{detail}</pre>
      </Modal>

      <Modal
        open={sessionModalOpen}
        wide
        title="选择会话"
        onClose={() => setSessionModalOpen(false)}
        footer={
          <>
            <button type="button" className="ghost sm" onClick={() => setSessionModalOpen(false)}>
              取消
            </button>
            <button type="button" className="primary" disabled={!filterSessionId} onClick={applySessionFilter}>
              确定
            </button>
          </>
        }
      >
        <div className="stack">
          <input
            value={sessionFilter}
            onChange={(e) => setSessionFilter(e.target.value)}
            placeholder={
              isWorkspaceScope(scopeId)
                ? '搜索会话标题…'
                : isStandaloneScope(scopeId)
                  ? '搜索独立任务会话…'
                  : '搜索工作空间或会话标题…'
            }
          />
          <SessionPickTree
            selectedId={filterSessionId}
            onSelect={(s) => {
              setFilterSessionId(s.id)
              setPickedSessionTitle(s.title || '')
            }}
            filter={sessionFilter}
            scopeWorkspaceId={scopeForSessionPick(scopeId)}
          />
        </div>
      </Modal>
    </>
  )
}
