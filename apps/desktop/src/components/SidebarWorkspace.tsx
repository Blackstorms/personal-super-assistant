/**
 * 侧栏：「空间」与「任务」列表（对齐 Cursor Agent 侧栏：胶囊切换 + 分区空状态）。
 * 「任务」tab：按时间分组展示会话；「空间」tab：项目与本地文件夹空间（白名单同步），图标区分。
 */
import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatHistoryMessages } from '../lib/chatDisplay'
import { deleteSession } from '../lib/sessionActions'
import { isFolderWorkspace } from '../lib/folderWorkspace'
import { useAppStore } from '../stores/app'
import Modal from './Modal'
import WorkspaceFormFields, { emptyWorkspaceForm, type WorkspaceFormValues } from './WorkspaceFormFields'

type Session = { id: string; title: string; workspace_id?: string | null; updated_at?: string }
type Project = { id: string; name: string; status: string; root_paths?: string[]; description?: string | null }
type Expert = { id: string; name: string }
type Skill = { id: string; name: string }
type Mcp = { id: string; name: string }
type Knowledge = { id: string; name?: string | null; path?: string }

const IconProject = () => (
  <svg className="ws-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 7h16v12H4zM8 7V5h8v2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const IconFolder = () => (
  <svg className="ws-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M3 7h6l2 2h10v10a1 1 0 01-1 1H4a1 1 0 01-1-1V7z" strokeLinejoin="round" />
  </svg>
)

const IconChat = () => (
  <svg className="ws-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 5h16v10H8l-4 4V5z" />
  </svg>
)

const IconTask = () => (
  <svg className="ws-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M9 6h11M9 12h11M9 18h11M5 6l.8.8L7.5 5M5 12l.8.8L7.5 11M5 18l.8.8L7.5 17" />
  </svg>
)

const IconPlus = () => (
  <svg className="ws-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 5v14M5 12h14" />
  </svg>
)

const IconTrash = () => (
  <svg className="ws-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 7h16M9 7V5h6v2M10 11v6M14 11v6M6 7l1 12h10l1-12" />
  </svg>
)

const IconHash = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M5 9h14M5 15h14M9 5l-1 14M16 5l-1 14" strokeLinecap="round" />
  </svg>
)

const IconFilter = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 6h16M7 12h10M10 18h4" strokeLinecap="round" />
  </svg>
)

function formatRelativeTime(iso?: string) {
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
  return new Date(iso).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

function dayBucket(iso?: string): string {
  if (!iso) return '更早'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '更早'
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const t = d.getTime()
  if (t >= startToday) return '今天'
  if (t >= startToday - 86400000) return '昨天'
  if (t >= startToday - 7 * 86400000) return '近 7 天'
  return '更早'
}

type SessionRowProps = {
  session: Session
  active: boolean
  nested?: boolean
  icon: 'chat' | 'task'
  streaming: boolean
  showTime?: boolean
  onOpen: (s: Session) => void
  onDeleted: () => void
}

function SessionRow({ session, active, nested, icon, streaming, showTime, onOpen, onDeleted }: SessionRowProps) {
  const handleDelete = async (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    if (streaming) {
      window.alert('该会话正在生成回复，请先停止后再删除')
      return
    }
    const title = session.title || '未命名会话'
    if (!window.confirm(`确定删除会话「${title}」？此操作不可恢复。`)) return
    try {
      const deletedCurrent = await deleteSession(session.id)
      if (deletedCurrent) onDeleted()
    } catch (err) {
      window.alert(String(err))
    }
  }

  const timeLabel = showTime ? formatRelativeTime(session.updated_at) : ''

  return (
    <div className={`ws-session-row ${nested ? 'nested' : ''}`} data-session-id={session.id}>
      <button
        type="button"
        className={`ws-item ${nested ? 'ws-item-nested' : ''} ${active ? 'active' : ''}`}
        onClick={() => onOpen(session)}
        title={session.title}
      >
        {icon === 'chat' ? <IconChat /> : <IconTask />}
        <span className="ws-item-label">{session.title || '未命名会话'}</span>
        {timeLabel ? <span className="ws-item-time muted">{timeLabel}</span> : null}
      </button>
      <button
        type="button"
        className="ws-del-btn"
        title="删除会话"
        aria-label="删除会话"
        onClick={(e) => void handleDelete(e)}
      >
        <IconTrash />
      </button>
    </div>
  )
}

export default function SidebarWorkspace() {
  const navigate = useNavigate()
  const location = useLocation()
  const {
    sessionId,
    workspaceId,
    setSessionId,
    setWorkspaceId,
    setMessages,
    activeRuns,
    sessionListTick,
    workspaceListTick,
    bumpWorkspaceList,
    sidebarViewMode,
    setSidebarViewMode,
  } = useAppStore()
  const anyStreaming = Object.keys(activeRuns).length > 0
  const [sessions, setSessions] = useState<Session[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const viewMode = sidebarViewMode
  const setViewMode = setSidebarViewMode
  const [filterOpen, setFilterOpen] = useState(false)
  const [filterQuery, setFilterQuery] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<WorkspaceFormValues>(emptyWorkspaceForm())
  const [experts, setExperts] = useState<Expert[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [mcps, setMcps] = useState<Mcp[]>([])
  const [knowledge, setKnowledge] = useState<Knowledge[]>([])
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    const onFilter = () => setFilterOpen(true)
    window.addEventListener('psa-sidebar-filter', onFilter)
    return () => window.removeEventListener('psa-sidebar-filter', onFilter)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([
        apiRequest<{ items: Session[] }>('GET', '/api/v1/sessions'),
        apiRequest<{ items: Project[] }>('GET', '/api/v1/workspaces'),
      ])
      setSessions(s.items)
      setProjects(p.items.filter((x) => x.status === 'active'))
    } catch {
      /* 后端未就绪时静默 */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), 8000)
    return () => clearInterval(t)
  }, [refresh, sessionId, workspaceId, anyStreaming, sessionListTick, workspaceListTick])

  const q = filterQuery.trim().toLowerCase()

  const projectTree = useMemo(
    () =>
      projects
        .filter((p) => !q || p.name.toLowerCase().includes(q))
        .map((p) => ({
          project: p,
          sessions: sessions
            .filter((s) => s.workspace_id === p.id)
            .filter((s) => !q || (s.title || '').toLowerCase().includes(q) || p.name.toLowerCase().includes(q))
            .slice(0, 30),
        })),
    [projects, sessions, q],
  )

  const groupedSessions = useMemo(() => {
    // 「任务」只展示独立会话，项目内对话归「空间」
    let list = sessions.filter((s) => !s.workspace_id)
    if (q) list = list.filter((s) => (s.title || '').toLowerCase().includes(q))
    list.sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime())
    const buckets: Array<{ label: string; items: Session[] }> = []
    const order = ['今天', '昨天', '近 7 天', '更早']
    const map = new Map<string, Session[]>()
    for (const s of list.slice(0, 60)) {
      const key = dayBucket(s.updated_at)
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(s)
    }
    for (const label of order) {
      const items = map.get(label)
      if (items?.length) buckets.push({ label, items })
    }
    return buckets
  }, [sessions, q])

  useEffect(() => {
    setExpanded((prev) => {
      const next = { ...prev }
      for (const { project, sessions: ss } of projectTree) {
        if (next[project.id] === undefined) {
          next[project.id] = workspaceId === project.id || ss.some((s) => s.id === sessionId)
        }
      }
      return next
    })
  }, [projectTree, workspaceId, sessionId])

  /** 当前会话出现时切到正确侧栏视图，并滚入可视区 */
  useEffect(() => {
    if (!sessionId) return
    const hit = sessions.find((s) => s.id === sessionId)
    if (!hit) return
    if (hit.workspace_id) {
      setViewMode('space')
      setExpanded((e) => ({ ...e, [hit.workspace_id!]: true }))
    } else {
      setViewMode('group')
    }
    const t = window.setTimeout(() => {
      document
        .querySelector<HTMLElement>(`[data-session-id="${sessionId}"]`)
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }, 80)
    return () => window.clearTimeout(t)
  }, [sessionId, sessions, setViewMode])

  const openSession = async (s: Session) => {
    const sid = s.id
    setWorkspaceId(s.workspace_id || null)
    setSessionId(sid)
    const running = Boolean(useAppStore.getState().activeRuns[sid])
    if (running) {
      const cached = useAppStore.getState().messageCache[sid]
      if (cached?.length) setMessages(cached, sid)
      navigate(s.workspace_id ? `/tasks?session=${sid}&from=workspace` : `/tasks?session=${sid}`)
      return
    }
    try {
      const data = await apiRequest<{
        items: Array<{
          id: string
          role: string
          content: string
          tool_calls?: Array<{ id: string; function?: { name?: string; arguments?: string } }>
          tool_call_id?: string
        }>
      }>('GET', `/api/v1/sessions/${sid}/messages`)
      // 始终写入目标会话缓存；若用户已切走则不影响当前展示
      if (useAppStore.getState().activeRuns[sid]) {
        const cached = useAppStore.getState().messageCache[sid]
        if (cached?.length) setMessages(cached, sid)
      } else {
        setMessages(formatHistoryMessages(data.items), sid)
      }
    } catch {
      if (!useAppStore.getState().activeRuns[sid]) setMessages([], sid)
    }
    navigate(s.workspace_id ? `/tasks?session=${sid}&from=workspace` : `/tasks?session=${sid}`)
  }

  const handleSessionDeleted = () => {
    navigate('/tasks')
  }

  const openProject = (p: Project) => {
    setWorkspaceId(p.id)
    setSessionId(null)
    setExpanded((e) => ({ ...e, [p.id]: true }))
    navigate(`/projects/${p.id}`)
  }

  const loadCreateMeta = useCallback(async () => {
    try {
      const [ex, sk, mcp, kn] = await Promise.all([
        apiRequest<{ items: Expert[] }>('GET', '/api/v1/experts'),
        apiRequest<{ items: Skill[] }>('GET', '/api/v1/skills'),
        apiRequest<{ items: Mcp[] }>('GET', '/api/v1/mcp/servers'),
        apiRequest<{ items: Knowledge[] }>('GET', '/api/v1/knowledge/bases'),
      ])
      setExperts(ex.items)
      setSkills(sk.items)
      setMcps(mcp.items)
      setKnowledge(kn.items)
    } catch {
      /* 静默 */
    }
  }, [])

  const openCreateWorkspace = () => {
    setCreateForm(emptyWorkspaceForm())
    setCreateOpen(true)
    void loadCreateMeta()
  }

  const closeCreateWorkspace = () => {
    setCreateOpen(false)
    setCreateForm(emptyWorkspaceForm())
  }

  const patchCreateForm = (patch: Partial<WorkspaceFormValues>) => {
    setCreateForm((prev) => ({ ...prev, ...patch }))
  }

  const toggleProject = (id: string) => {
    setExpanded((e) => ({ ...e, [id]: !e[id] }))
  }

  const createWorkspace = async () => {
    setCreating(true)
    try {
      const created = await apiRequest<Project>('POST', '/api/v1/workspaces', {
        name: createForm.name.trim() || '未命名工作空间',
        description: createForm.description || null,
        instructions: createForm.instructions || null,
        expert_id: createForm.expertId || null,
        skill_ids: createForm.skillIds,
        mcp_ids: createForm.mcpIds,
        knowledge_ids: createForm.knowledgeIds,
      })
      closeCreateWorkspace()
      setWorkspaceId(created.id)
      setExpanded((e) => ({ ...e, [created.id]: true }))
      bumpWorkspaceList()
      await refresh()
      navigate(`/projects/${created.id}`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="sidebar-workspace">
      <div className="ws-toolbar">
        <div className="ws-seg" role="tablist" aria-label="侧栏视图">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'group'}
            className={`ws-seg-btn ${viewMode === 'group' ? 'active' : ''}`}
            onClick={() => setViewMode('group')}
          >
            <IconHash />
            <span>任务</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'space'}
            className={`ws-seg-btn ${viewMode === 'space' ? 'active' : ''}`}
            onClick={() => setViewMode('space')}
          >
            <IconFolder />
            <span>空间</span>
          </button>
        </div>
        <div className="ws-toolbar-actions">
          <button
            type="button"
            className={`ws-tool-btn ${filterOpen ? 'active' : ''}`}
            title="筛选"
            aria-label="筛选"
            onClick={() => setFilterOpen((v) => !v)}
          >
            <IconFilter />
          </button>
        </div>
      </div>

      {filterOpen ? (
        <div className="ws-filter-row">
          <input
            className="ws-filter-input"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="筛选空间或任务…"
            autoFocus
          />
        </div>
      ) : null}

      <div className="ws-scroll">
        {viewMode === 'space' ? (
          <>
            <div className="ws-section">
              <div className="ws-section-title-row">
                <h3 className="ws-section-title">空间</h3>
                <button type="button" className="ws-add-btn" title="新建工作空间" onClick={openCreateWorkspace}>
                  <IconPlus />
                </button>
              </div>
              <div className="ws-section-body">
                {projectTree.length === 0 ? (
                  <div className="ws-empty muted">尚未打开空间</div>
                ) : (
                  projectTree.map(({ project, sessions: projectSessions }) => (
                    <div key={project.id} className="ws-group">
                      <div className="ws-row">
                        <button
                          type="button"
                          className="ws-expand"
                          onClick={() => toggleProject(project.id)}
                          aria-label={expanded[project.id] ? '收起' : '展开'}
                        >
                          {expanded[project.id] ? '▾' : '▸'}
                        </button>
                        <button
                          type="button"
                          className={`ws-item ws-item-project ${
                            workspaceId === project.id && location.pathname.startsWith('/projects/') ? 'active' : ''
                          }`}
                          onClick={() => openProject(project)}
                          title={project.root_paths?.[0] || project.description || project.name}
                        >
                          {isFolderWorkspace(project) ? <IconFolder /> : <IconProject />}
                          <span className="ws-item-label">{project.name}</span>
                        </button>
                      </div>
                      {expanded[project.id] &&
                        projectSessions.map((s) => (
                          <SessionRow
                            key={s.id}
                            session={s}
                            active={sessionId === s.id}
                            nested
                            icon="chat"
                            showTime
                            streaming={Boolean(activeRuns[s.id])}
                            onOpen={(sess) => void openSession(sess)}
                            onDeleted={handleSessionDeleted}
                          />
                        ))}
                      {expanded[project.id] && projectSessions.length === 0 && (
                        <div className="ws-empty-nested muted">暂无会话</div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="ws-section">
            <div className="ws-section-title-row">
              <h3 className="ws-section-title">最近任务</h3>
            </div>
            <div className="ws-section-body">
              {groupedSessions.length === 0 ? (
                <div className="ws-empty muted">还没有任务</div>
              ) : (
                groupedSessions.map((bucket) => (
                  <div key={bucket.label} className="ws-group ws-group-bucket">
                    <div className="ws-bucket-label muted">{bucket.label}</div>
                    {bucket.items.map((s) => (
                      <SessionRow
                        key={s.id}
                        session={s}
                        active={sessionId === s.id}
                        icon="task"
                        showTime
                        streaming={Boolean(activeRuns[s.id])}
                        onOpen={(sess) => void openSession(sess)}
                        onDeleted={handleSessionDeleted}
                      />
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      <Modal
        open={createOpen}
        wide
        title="新建工作空间"
        onClose={closeCreateWorkspace}
        footer={
          <>
            <button type="button" onClick={closeCreateWorkspace}>
              取消
            </button>
            <button type="button" className="primary" disabled={creating} onClick={() => void createWorkspace()}>
              {creating ? '创建中…' : '创建'}
            </button>
          </>
        }
      >
        <WorkspaceFormFields
          values={createForm}
          experts={experts}
          skills={skills}
          mcps={mcps}
          knowledge={knowledge}
          onChange={patchCreateForm}
        />
      </Modal>
    </div>
  )
}
