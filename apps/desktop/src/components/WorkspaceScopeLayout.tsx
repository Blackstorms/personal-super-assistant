/**
 * 模块页左侧范围选择：全部 / 独立任务 / 各工作空间（空间）。
 */
import { useEffect, useState, type ReactNode } from 'react'
import { apiRequest } from '../lib/api'
import {
  STANDALONE_SCOPE,
  isAllScope,
  isStandaloneScope,
  isWorkspaceScope,
  scopeCrumbLabel,
  type ModuleScopeId,
} from '../lib/moduleScope'

export type WorkspaceOption = { id: string; name: string; status?: string }

type Props = {
  title: string
  scopeId: ModuleScopeId
  onScopeChange: (id: ModuleScopeId) => void
  children: ReactNode
}

const IconAll = () => (
  <svg className="scope-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="3" />
  </svg>
)

const IconTask = () => (
  <svg className="scope-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M9 6h11M9 12h11M9 18h11M5 6l.8.8L7.5 5M5 12l.8.8L7.5 11M5 18l.8.8L7.5 17" strokeLinecap="round" />
  </svg>
)

const IconFolder = () => (
  <svg className="scope-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M3 7h6l2 2h10v10a1 1 0 01-1 1H4a1 1 0 01-1-1V7z" strokeLinejoin="round" />
  </svg>
)

export function useWorkspaceScope(initialFrom?: ModuleScopeId) {
  const [scopeId, setScopeId] = useState<ModuleScopeId>(initialFrom ?? STANDALONE_SCOPE)
  useEffect(() => {
    if (initialFrom !== undefined) setScopeId(initialFrom)
  }, [initialFrom])
  return [scopeId, setScopeId] as const
}

export default function WorkspaceScopeLayout({ title, scopeId, onScopeChange, children }: Props) {
  const [workspaces, setWorkspaces] = useState<WorkspaceOption[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      setLoading(true)
      try {
        const data = await apiRequest<{ items: WorkspaceOption[] }>('GET', '/api/v1/workspaces')
        setWorkspaces(data.items.filter((w) => w.status !== 'archived'))
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const activeName = scopeCrumbLabel(
    scopeId,
    isWorkspaceScope(scopeId) ? workspaces.find((w) => w.id === scopeId)?.name : undefined,
  )

  return (
    <div className="kb-layout module-scope-layout">
      <aside className="kb-side">
        <div className="kb-side-head">
          <h2>{title}</h2>
        </div>
        <div className="kb-base-list module-scope-list">
          <button
            type="button"
            className={`kb-base-item ${isAllScope(scopeId) ? 'active' : ''}`}
            onClick={() => onScopeChange(null)}
          >
            <IconAll />
            <span className="kb-base-text">
              <span className="kb-base-name">全部</span>
              <span className="kb-base-meta muted">不限范围</span>
            </span>
          </button>

          <div className="module-scope-section-label">任务</div>
          <button
            type="button"
            className={`kb-base-item ${isStandaloneScope(scopeId) ? 'active' : ''}`}
            onClick={() => onScopeChange(STANDALONE_SCOPE)}
          >
            <IconTask />
            <span className="kb-base-text">
              <span className="kb-base-name">独立任务</span>
              <span className="kb-base-meta muted">未绑定工作空间</span>
            </span>
          </button>

          <div className="module-scope-section-label">空间</div>
          {loading && <div className="muted module-scope-empty">加载中…</div>}
          {!loading && workspaces.length === 0 && (
            <div className="muted module-scope-empty">暂无工作空间</div>
          )}
          {workspaces.map((w) => (
            <button
              key={w.id}
              type="button"
              className={`kb-base-item ${scopeId === w.id ? 'active' : ''}`}
              onClick={() => onScopeChange(w.id)}
              title={w.name}
            >
              <IconFolder />
              <span className="kb-base-text">
                <span className="kb-base-name">{w.name}</span>
              </span>
            </button>
          ))}
        </div>
      </aside>
      <section className="kb-main module-scope-main">
        <div className="module-scope-crumb muted">{activeName}</div>
        {children}
      </section>
    </div>
  )
}
