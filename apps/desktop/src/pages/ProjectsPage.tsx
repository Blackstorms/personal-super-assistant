/**
 * 项目主页：我的项目列表（不含本地文件夹型空间）。
 */
import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatRelativeTime } from '../lib/formatTime'
import { isFolderWorkspace } from '../lib/folderWorkspace'
import { useAppStore } from '../stores/app'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import WorkspaceFormFields, { emptyWorkspaceForm, type WorkspaceFormValues } from '../components/WorkspaceFormFields'

type Project = {
  id: string
  name: string
  description?: string | null
  instructions?: string | null
  expert_id?: string | null
  skill_ids?: string[]
  mcp_ids?: string[]
  knowledge_ids?: string[]
  root_paths?: string[]
  status: string
  created_at?: string
  updated_at?: string
}

type Expert = { id: string; name: string }
type Skill = { id: string; name: string }
type Mcp = { id: string; name: string }
type Knowledge = { id: string; name?: string | null; path?: string }

function ProjectIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 7h16v12H4zM8 7V5h8v2" />
    </svg>
  )
}

function formFromProject(p: Project): WorkspaceFormValues {
  return {
    name: p.name || '',
    description: p.description || '',
    instructions: p.instructions || '',
    expertId: p.expert_id || '',
    skillIds: p.skill_ids || [],
    mcpIds: p.mcp_ids || [],
    knowledgeIds: p.knowledge_ids || [],
  }
}

export default function ProjectsPage() {
  const navigate = useNavigate()
  const { setWorkspaceId, setSessionId, bumpWorkspaceList } = useAppStore()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<WorkspaceFormValues>(emptyWorkspaceForm())
  const [experts, setExperts] = useState<Expert[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [mcps, setMcps] = useState<Mcp[]>([])
  const [knowledge, setKnowledge] = useState<Knowledge[]>([])
  const [saving, setSaving] = useState(false)
  const [menuId, setMenuId] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiRequest<{ items: Project[] }>('GET', '/api/v1/workspaces')
      // 项目页只展示正式项目，本地文件夹型空间归侧栏/对话选择器
      setProjects(data.items.filter((p) => p.status === 'active' && !isFolderWorkspace(p)))
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!menuId) return
    const onDoc = (e: Event) => {
      const t = e.target as HTMLElement
      if (!t.closest?.('.project-card-menu-wrap')) setMenuId(null)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [menuId])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return projects
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q),
    )
  }, [projects, search])

  const loadMeta = useCallback(async () => {
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

  const openCreate = () => {
    setEditId(null)
    setForm(emptyWorkspaceForm())
    setModalOpen(true)
    setMenuId(null)
    void loadMeta()
  }

  const openEdit = async (p: Project, e?: MouseEvent) => {
    e?.stopPropagation()
    setMenuId(null)
    try {
      const detail = await apiRequest<Project>('GET', `/api/v1/workspaces/${p.id}`)
      setEditId(detail.id)
      setForm(formFromProject(detail))
      setModalOpen(true)
      void loadMeta()
    } catch (err) {
      showToast(String(err), 'error')
    }
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditId(null)
    setForm(emptyWorkspaceForm())
  }

  const save = async () => {
    setSaving(true)
    try {
      const body = {
        name: form.name.trim() || '未命名项目',
        description: form.description || null,
        instructions: form.instructions || null,
        expert_id: form.expertId || null,
        skill_ids: form.skillIds,
        mcp_ids: form.mcpIds,
        knowledge_ids: form.knowledgeIds,
      }
      if (editId) {
        await apiRequest('PATCH', `/api/v1/workspaces/${editId}`, body)
        showToast('项目已更新')
        closeModal()
        await refresh()
        bumpWorkspaceList()
      } else {
        const created = await apiRequest<Project>('POST', '/api/v1/workspaces', body)
        showToast('项目已创建')
        closeModal()
        await refresh()
        bumpWorkspaceList()
        openProject(created)
      }
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const openProject = (p: Project) => {
    setWorkspaceId(p.id)
    setSessionId(null)
    navigate(`/projects/${p.id}`)
  }

  const deleteProject = async (p: Project, e?: MouseEvent) => {
    e?.stopPropagation()
    setMenuId(null)
    if (!window.confirm(`删除项目「${p.name}」？工作空间将被归档。`)) return
    try {
      await apiRequest('DELETE', `/api/v1/workspaces/${p.id}`)
      showToast('项目已删除')
      await refresh()
      bumpWorkspaceList()
    } catch (err) {
      showToast(String(err), 'error')
    }
  }

  return (
    <div className="projects-page stack">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <header className="projects-hero panel">
        <div className="projects-hero-copy">
          <h1>项目</h1>
          <p className="muted">组织工作空间，配置专家与资源，协同完成复杂任务。</p>
          <button type="button" className="primary projects-new-btn" onClick={openCreate}>
            + 新建项目
          </button>
        </div>
      </header>

      <section className="projects-section">
        <div className="projects-section-head">
          <h2>我的项目</h2>
          <input
            type="search"
            className="projects-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索项目"
            aria-label="搜索项目"
          />
        </div>

        {loading ? (
          <p className="muted">加载中…</p>
        ) : filtered.length === 0 ? (
          <div className="projects-empty panel">
            <p className="muted">
              {search.trim() ? '没有匹配的项目，试试其他关键词。' : '还没有项目，点击「新建项目」创建。'}
            </p>
          </div>
        ) : (
          <div className="projects-grid">
            {filtered.map((p) => (
              <button
                key={p.id}
                type="button"
                className="project-card panel"
                onClick={() => openProject(p)}
              >
                <div className="project-card-top">
                  <span className="project-card-icon">
                    <ProjectIcon />
                  </span>
                  <div className="project-card-menu-wrap" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      className="project-card-menu"
                      title="更多"
                      aria-label="更多"
                      onClick={() => setMenuId((id) => (id === p.id ? null : p.id))}
                    >
                      ···
                    </button>
                    {menuId === p.id ? (
                      <div className="project-card-dropdown">
                        <button type="button" onClick={(e) => void openEdit(p, e)}>
                          编辑
                        </button>
                        <button type="button" className="danger" onClick={(e) => void deleteProject(p, e)}>
                          删除
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="project-card-title">{p.name}</div>
                <div className="project-card-desc muted">{p.description || ''}</div>
                <div className="project-card-meta muted">
                  添加于 {formatRelativeTime(p.created_at || p.updated_at) || '—'}
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <Modal
        open={modalOpen}
        wide
        title={editId ? '编辑项目' : '新建项目'}
        onClose={closeModal}
        footer={
          <>
            <button type="button" onClick={closeModal}>
              取消
            </button>
            <button type="button" className="primary" disabled={saving} onClick={() => void save()}>
              {saving ? '保存中…' : editId ? '保存' : '创建'}
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
          onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
        />
      </Modal>
    </div>
  )
}
