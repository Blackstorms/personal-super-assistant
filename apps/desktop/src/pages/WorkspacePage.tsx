/** 项目详情：配置指令与绑定；从项目主页或侧栏空间进入。 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatDateTime, formatRelativeTime } from '../lib/formatTime'
import { deleteSession } from '../lib/sessionActions'
import { useAppStore } from '../stores/app'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import WorkspaceFormFields, { type WorkspaceFormValues } from '../components/WorkspaceFormFields'

type Project = {
  id: string
  name: string
  description?: string
  instructions?: string | null
  expert_id?: string | null
  skill_ids: string[]
  mcp_ids: string[]
  knowledge_ids: string[]
  status: string
}

type Expert = { id: string; name: string }
type Skill = { id: string; name: string }
type Mcp = { id: string; name: string }
type Knowledge = { id: string; name?: string | null; path?: string; root_path?: string }
type Session = { id: string; title: string; updated_at?: string }

export default function WorkspacePage() {
  const navigate = useNavigate()
  const { workspaceId: routeWorkspaceId } = useParams<{ workspaceId: string }>()
  const { workspaceId, setWorkspaceId, setSessionId, setMessages, activeRuns, requestApplyWorkspaceDefaults } =
    useAppStore()
  const activeWorkspaceId = routeWorkspaceId || workspaceId
  const [project, setProject] = useState<Project | null>(null)
  const [form, setForm] = useState<WorkspaceFormValues>({
    name: '',
    description: '',
    instructions: '',
    expertId: '',
    skillIds: [],
    mcpIds: [],
    knowledgeIds: [],
  })
  const [experts, setExperts] = useState<Expert[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [mcps, setMcps] = useState<Mcp[]>([])
  const [knowledge, setKnowledge] = useState<Knowledge[]>([])
  const [summary, setSummary] = useState<{ sessions?: Session[]; session_count?: number } | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const loadMeta = async () => {
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
  }

  const loadProject = async (id: string) => {
    const items = await apiRequest<{ items: Project[] }>('GET', '/api/v1/workspaces')
    const p = items.items.find((x) => x.id === id) || null
    setProject(p)
    if (p) {
      setForm({
        name: p.name,
        description: p.description || '',
        instructions: p.instructions || '',
        expertId: p.expert_id || '',
        skillIds: p.skill_ids || [],
        mcpIds: p.mcp_ids || [],
        knowledgeIds: p.knowledge_ids || [],
      })
    }
  }

  useEffect(() => {
    loadMeta().catch((e) => showToast(String(e), 'error'))
  }, [])

  useEffect(() => {
    if (routeWorkspaceId) setWorkspaceId(routeWorkspaceId)
  }, [routeWorkspaceId, setWorkspaceId])

  useEffect(() => {
    if (!activeWorkspaceId) {
      navigate('/projects', { replace: true })
      return
    }
    loadProject(activeWorkspaceId).catch((e) => showToast(String(e), 'error'))
    apiRequest<{ sessions?: Session[]; session_count?: number }>(
      'GET',
      `/api/v1/workspaces/${activeWorkspaceId}/summary`,
    )
      .then(setSummary)
      .catch(console.error)
  }, [activeWorkspaceId, navigate])

  const openEdit = () => {
    if (!project) return
    setModalOpen(true)
  }

  const save = async () => {
    if (!activeWorkspaceId) return
    setSaving(true)
    try {
      const body = {
        name: form.name || '未命名工作空间',
        description: form.description,
        instructions: form.instructions,
        expert_id: form.expertId || null,
        skill_ids: form.skillIds,
        mcp_ids: form.mcpIds,
        knowledge_ids: form.knowledgeIds,
      }
      await apiRequest('PATCH', `/api/v1/workspaces/${activeWorkspaceId}`, body)
      showToast('工作空间已更新')
      setModalOpen(false)
      await loadProject(activeWorkspaceId)
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const patchForm = (patch: Partial<WorkspaceFormValues>) => {
    setForm((prev) => ({ ...prev, ...patch }))
  }

  const reloadSummary = async () => {
    if (!activeWorkspaceId) return
    const data = await apiRequest<{ sessions?: Session[]; session_count?: number }>(
      'GET',
      `/api/v1/workspaces/${activeWorkspaceId}/summary`,
    )
    setSummary(data)
  }

  const removeSessionInProject = async (s: Session) => {
    if (activeRuns[s.id]) {
      showToast('该会话正在生成回复，请先停止后再删除', 'error')
      return
    }
    if (!window.confirm(`确定删除会话「${s.title || '未命名会话'}」？`)) return
    try {
      const deletedCurrent = await deleteSession(s.id)
      await reloadSummary()
      if (deletedCurrent) navigate('/tasks')
      showToast('会话已删除', 'success')
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const openSession = async (sid: string) => {
    setSessionId(sid)
    const data = await apiRequest<{ items: Array<{ id: string; role: string; content: string }> }>(
      'GET',
      `/api/v1/sessions/${sid}/messages`,
    )
    setMessages(
      data.items
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ id: m.id, role: m.role as 'user' | 'assistant', content: m.content || '' })),
      sid,
    )
    navigate(`/tasks?session=${sid}&from=workspace`)
  }

  const newSessionInProject = () => {
    if (!activeWorkspaceId) return
    // 不预先落库：发送第一条消息时再由 ChatPage.ensureSession 创建
    requestApplyWorkspaceDefaults()
    setWorkspaceId(activeWorkspaceId)
    setSessionId(null)
    setMessages([])
    navigate('/tasks?from=workspace')
  }

  if (!activeWorkspaceId || !project) {
    return (
      <div className="stack">
        <p className="muted">加载项目…</p>
      </div>
    )
  }

  return (
    <div className="stack">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <button type="button" className="ghost sm projects-back" onClick={() => navigate('/projects')}>
            ← 全部项目
          </button>
          <h2 style={{ margin: 0 }}>{project.name}</h2>
          <p className="muted">
            {project.description || '工作空间详情 · 配置指令与资源绑定'}
            {project.instructions ? ' · 含项目指令' : ''}
          </p>
        </div>
        <div className="row">
          <button type="button" onClick={openEdit}>
            编辑配置
          </button>
          <button
            type="button"
            className="danger"
            onClick={async () => {
              if (!confirm(`删除工作空间「${project.name}」？`)) return
              try {
                await apiRequest('DELETE', `/api/v1/workspaces/${activeWorkspaceId}`)
                setWorkspaceId(null)
                showToast('已删除')
                navigate('/projects')
              } catch (e) {
                showToast(String(e), 'error')
              }
            }}
          >
            删除
          </button>
        </div>
      </div>

      {summary && (
        <div className="panel stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h3>空间内会话（{summary.session_count ?? 0}）</h3>
            <button type="button" className="primary" onClick={() => newSessionInProject()}>
              + 新建会话
            </button>
          </div>
          {(summary.sessions || []).length === 0 ? (
            <p className="muted">还没有会话。点「新建会话」进入对话，发送第一条消息后才会出现在此列表。</p>
          ) : (
            <div className="ws-page-sessions">
              {(summary.sessions || []).map((s) => {
                const timeLabel = formatRelativeTime(s.updated_at)
                const timeFull = formatDateTime(s.updated_at)
                return (
                <div key={s.id} className="ws-session-row ws-page-session-row">
                  <button
                    type="button"
                    className="ws-item"
                    onClick={() => void openSession(s.id)}
                    title={s.title || '未命名会话'}
                  >
                    <svg className="ws-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M4 5h16v10H8l-4 4V5z" />
                    </svg>
                    <span className="ws-item-label">{s.title || '未命名会话'}</span>
                    {timeLabel ? (
                      <span className="ws-item-time muted" title={timeFull}>
                        {timeLabel}
                      </span>
                    ) : null}
                  </button>
                  <button
                    type="button"
                    className="ws-del-btn ws-page-del-btn"
                    title="删除会话"
                    aria-label="删除会话"
                    onClick={(e) => {
                      e.stopPropagation()
                      void removeSessionInProject(s)
                    }}
                  >
                    <svg className="ws-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M4 7h16M9 7V5h6v2M10 11v6M14 11v6M6 7l1 12h10l1-12" />
                    </svg>
                  </button>
                </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      <Modal
        open={modalOpen}
        wide
        title="编辑工作空间"
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <button type="button" onClick={() => setModalOpen(false)}>
              取消
            </button>
            <button type="button" className="primary" disabled={saving} onClick={() => void save()}>
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        }
      >
        <WorkspaceFormFields
          values={form}
          experts={experts}
          skills={skills}
          mcps={mcps}
          knowledge={knowledge}
          onChange={patchForm}
        />
      </Modal>
    </div>
  )
}
