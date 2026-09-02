/**
 * 会话选择树：「任务」与「空间」平级；无工作空间的会话在「任务」，工作空间下嵌套会话。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../lib/api'
import { isStandaloneScope, isWorkspaceScope, type ModuleScopeId } from '../lib/moduleScope'

export type SessionOption = {
  id: string
  title: string
  workspace_id?: string | null
  message_count?: number
  updated_at?: string
}

type Project = { id: string; name: string; status?: string }

type Props = {
  selectedId: string
  onSelect: (session: SessionOption) => void
  filter?: string
  /** null=全部；STANDALONE_SCOPE=仅独立任务；工作空间 id=该空间下会话 */
  scopeWorkspaceId?: ModuleScopeId
}

function formatSessionTime(iso?: string) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function SessionRow({
  session,
  active,
  nested,
  onSelect,
}: {
  session: SessionOption
  active: boolean
  nested?: boolean
  onSelect: (session: SessionOption) => void
}) {
  return (
    <button
      type="button"
      className={`session-pick-item ${nested ? 'nested' : ''} ${active ? 'active' : ''}`}
      onClick={() => onSelect(session)}
    >
      <span className="session-pick-title">{session.title || '未命名会话'}</span>
      <span className="muted session-pick-meta">
        {formatSessionTime(session.updated_at)}
        {(session.message_count ?? 0) > 0 ? ` · ${session.message_count} 条消息` : ''}
      </span>
    </button>
  )
}

export default function SessionPickTree({
  selectedId,
  onSelect,
  filter = '',
  scopeWorkspaceId = null,
}: Props) {
  const [sessions, setSessions] = useState<SessionOption[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [sess, proj] = await Promise.all([
        apiRequest<{ items: SessionOption[] }>('GET', '/api/v1/sessions?limit=200'),
        apiRequest<{ items: Project[] }>('GET', '/api/v1/workspaces'),
      ])
      setSessions(sess.items)
      setProjects(proj.items.filter((p) => p.status !== 'archived'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const q = filter.trim().toLowerCase()

  const matchSession = (s: SessionOption) => {
    if (!q) return true
    return (s.title || '').toLowerCase().includes(q) || s.id.toLowerCase().includes(q)
  }

  const scopedWorkspaceSessions = useMemo(() => {
    if (!isWorkspaceScope(scopeWorkspaceId)) return []
    return sessions.filter((s) => s.workspace_id === scopeWorkspaceId).filter(matchSession)
  }, [sessions, scopeWorkspaceId, q])

  const projectTree = useMemo(() => {
    if (scopeWorkspaceId !== null) return []
    const list = projects
      .map((project) => ({
        project,
        sessions: sessions.filter((s) => s.workspace_id === project.id).filter(matchSession),
      }))
      .filter(({ project, sessions: ss }) => {
        if (!q) return true
        const nameHit = project.name.toLowerCase().includes(q)
        return nameHit || ss.length > 0
      })
    return list
  }, [projects, sessions, q, scopeWorkspaceId])

  const standaloneSessions = useMemo(() => {
    if (isWorkspaceScope(scopeWorkspaceId)) return []
    return sessions.filter((s) => !s.workspace_id).filter(matchSession)
  }, [sessions, q, scopeWorkspaceId])

  useEffect(() => {
    setExpanded((prev) => {
      const next = { ...prev }
      for (const { project, sessions: ss } of projectTree) {
        if (next[project.id] === undefined) {
          next[project.id] = ss.some((s) => s.id === selectedId) || Boolean(q)
        }
      }
      if (q) {
        for (const { project } of projectTree) {
          next[project.id] = true
        }
      }
      return next
    })
  }, [projectTree, selectedId, q])

  const toggleProject = (id: string) => {
    setExpanded((e) => ({ ...e, [id]: !e[id] }))
  }

  if (loading) {
    return <p className="muted">加载会话列表…</p>
  }

  const isEmpty =
    isWorkspaceScope(scopeWorkspaceId)
      ? scopedWorkspaceSessions.length === 0
      : isStandaloneScope(scopeWorkspaceId)
        ? standaloneSessions.length === 0
        : projectTree.length === 0 && standaloneSessions.length === 0

  if (isEmpty) {
    return (
      <p className="muted">
        {sessions.length === 0
          ? '暂无会话，请先在任务页创建对话。'
          : isWorkspaceScope(scopeWorkspaceId)
            ? '没有匹配的会话。'
            : isStandaloneScope(scopeWorkspaceId)
              ? '没有匹配的独立任务会话。'
              : '没有匹配的会话或工作空间。'}
      </p>
    )
  }

  if (isWorkspaceScope(scopeWorkspaceId)) {
    return (
      <div className="session-pick-list">
        {scopedWorkspaceSessions.map((s) => (
          <SessionRow key={s.id} session={s} active={selectedId === s.id} onSelect={onSelect} />
        ))}
      </div>
    )
  }

  if (isStandaloneScope(scopeWorkspaceId)) {
    return (
      <div className="session-pick-list">
        {standaloneSessions.map((s) => (
          <SessionRow key={s.id} session={s} active={selectedId === s.id} onSelect={onSelect} />
        ))}
      </div>
    )
  }

  return (
    <div className="session-pick-list">
      {standaloneSessions.length > 0 && (
        <>
          <div className="session-pick-section-label">任务 ({standaloneSessions.length})</div>
          {standaloneSessions.map((s) => (
            <SessionRow key={s.id} session={s} active={selectedId === s.id} onSelect={onSelect} />
          ))}
        </>
      )}

      {projectTree.length > 0 && (
        <>
          <div className="session-pick-section-label">空间 ({projectTree.length})</div>
          {projectTree.map(({ project, sessions: projectSessions }) => (
            <div key={project.id} className="session-pick-group">
              <div className="session-pick-project-row">
                <button
                  type="button"
                  className="session-pick-expand"
                  onClick={() => toggleProject(project.id)}
                  aria-label={expanded[project.id] ? '收起' : '展开'}
                >
                  {expanded[project.id] ? '▾' : '▸'}
                </button>
                <span className="session-pick-project-name">{project.name}</span>
                <span className="muted session-pick-project-count">{projectSessions.length}</span>
              </div>
              {expanded[project.id] &&
                projectSessions.map((s) => (
                  <SessionRow
                    key={s.id}
                    session={s}
                    nested
                    active={selectedId === s.id}
                    onSelect={onSelect}
                  />
                ))}
              {expanded[project.id] && projectSessions.length === 0 && (
                <div className="muted session-pick-empty-nested">暂无会话</div>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  )
}

export function useSessionPickData() {
  const [sessions, setSessions] = useState<SessionOption[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiRequest<{ items: SessionOption[] }>('GET', '/api/v1/sessions?limit=200')
      setSessions(data.items)
      return data.items
    } finally {
      setLoading(false)
    }
  }, [])

  return { sessions, loading, load }
}
