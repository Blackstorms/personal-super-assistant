import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatDateTime } from '../lib/formatTime'
import {
  appendScopeQuery,
  filterSessionsByScope,
  isStandaloneScope,
  isWorkspaceScope,
  scopeForSessionPick,
  scopeFromSidebarWorkspace,
  scopeWorkspaceIdForCreate,
  type ModuleScopeId,
} from '../lib/moduleScope'
import { useAppStore } from '../stores/app'
import WorkspaceScopeLayout from '../components/WorkspaceScopeLayout'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import SessionPickTree, { useSessionPickData } from '../components/SessionPickTree'

type Checklist = {
  id: string
  title: string
  session_id?: string | null
  workspace_id?: string | null
  created_at?: string
  updated_at?: string
}

export default function ChecklistPage() {
  const navigate = useNavigate()
  const { workspaceId, sessionId } = useAppStore()
  const [scopeId, setScopeId] = useState<ModuleScopeId>(scopeFromSidebarWorkspace(workspaceId))
  const [items, setItems] = useState<Checklist[]>([])
  const [filterSession, setFilterSession] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [parseModalOpen, setParseModalOpen] = useState(false)
  const { load: loadSessionsForPick } = useSessionPickData()
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [sessionFilter, setSessionFilter] = useState('')
  const [title, setTitle] = useState('手动清单')
  const [taskLines, setTaskLines] = useState('示例任务 A\n示例任务 B')
  const [saving, setSaving] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const load = async () => {
    const qs = new URLSearchParams()
    appendScopeQuery(qs, scopeId)
    if (filterSession && sessionId) qs.set('session_id', sessionId)
    const data = await apiRequest<{ items: Checklist[] }>('GET', `/api/v1/checklists?${qs}`)
    setItems(data.items)
  }

  useEffect(() => {
    setScopeId(scopeFromSidebarWorkspace(workspaceId))
  }, [workspaceId])

  useEffect(() => {
    load().catch((e) => showToast(String(e), 'error'))
  }, [scopeId, sessionId, filterSession])

  const openParseModal = () => {
    setSessionFilter('')
    setParseModalOpen(true)
    void loadSessionsForPick().then((items) => {
      const scoped = filterSessionsByScope(items, scopeId)
      setSelectedSessionId((prev) => {
        if (prev && scoped.some((s) => s.id === prev)) return prev
        if (sessionId && scoped.some((s) => s.id === sessionId)) return sessionId
        return scoped[0]?.id || ''
      })
    })
  }

  const createChecklist = async () => {
    setSaving(true)
    try {
      const taskItems = taskLines
        .split('\n')
        .map((x) => x.trim())
        .filter(Boolean)
      const created = await apiRequest<{ id: string }>('POST', '/api/v1/checklists', {
        workspace_id: scopeWorkspaceIdForCreate(scopeId),
        session_id: sessionId,
        title: title.trim() || '手动清单',
        items: taskItems.length ? taskItems : ['示例任务'],
      })
      setModalOpen(false)
      showToast('清单已创建')
      navigate(`/checklists/${created.id}`)
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const parseFromSession = async () => {
    if (!selectedSessionId) {
      showToast('请选择一个会话', 'error')
      return
    }
    setParsing(true)
    try {
      const r = await apiRequest<{ id: string; title?: string }>('POST', '/api/v1/checklists/parse', {
        session_id: selectedSessionId,
      })
      showToast(r?.title ? `已生成清单「${r.title}」` : '已从会话生成清单')
      setParseModalOpen(false)
      await load()
      if (r?.id) navigate(`/checklists/${r.id}`)
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setParsing(false)
    }
  }

  return (
    <>
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <WorkspaceScopeLayout title="任务清单" scopeId={scopeId} onScopeChange={setScopeId}>
        <div className="stack">
          <p className="muted" style={{ margin: 0 }}>
            从对话提取待办与提醒；说明、分析类内容不会列入。点击进入详情勾选进度或导出 Markdown。
          </p>

          <div className="panel row">
        <button type="button" className="primary" disabled={parsing} onClick={openParseModal}>
          {parsing ? '生成中…' : '从会话生成'}
        </button>
        <button type="button" onClick={() => setModalOpen(true)}>
          + 新建清单
        </button>
        <label className="row muted">
          <input type="checkbox" checked={filterSession} onChange={(e) => setFilterSession(e.target.checked)} />
          仅当前会话
        </label>
      </div>

      <div className="panel">
        {items.length === 0 ? (
          <p className="muted">还没有清单，点击「新建清单」或「从会话生成」创建。</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>标题</th>
                <th>录入时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <button type="button" className="list-link" onClick={() => navigate(`/checklists/${c.id}`)}>
                      {c.title}
                    </button>
                  </td>
                  <td className="muted">{formatDateTime(c.created_at)}</td>
                  <td className="row">
                    <button type="button" onClick={() => navigate(`/checklists/${c.id}`)}>
                      打开
                    </button>
                    <button
                      type="button"
                      className="danger"
                      onClick={async () => {
                        if (!confirm(`删除清单「${c.title}」？`)) return
                        try {
                          await apiRequest('DELETE', `/api/v1/checklists/${c.id}`)
                          showToast('清单已删除')
                          await load()
                        } catch (e) {
                          showToast(String(e), 'error')
                        }
                      }}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
        </div>
      </WorkspaceScopeLayout>

      <Modal
        open={modalOpen}
        title="新建清单"
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <button type="button" onClick={() => setModalOpen(false)}>
              取消
            </button>
            <button type="button" className="primary" disabled={saving} onClick={() => void createChecklist()}>
              {saving ? '创建中…' : '创建'}
            </button>
          </>
        }
      >
        <div className="stack">
          <label className="muted">标题</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="清单标题" />
          <label className="muted">任务项（每行一条）</label>
          <textarea
            rows={5}
            value={taskLines}
            onChange={(e) => setTaskLines(e.target.value)}
            placeholder="每行输入一个任务"
          />
        </div>
      </Modal>

      <Modal
        open={parseModalOpen}
        title="从会话生成清单"
        wide
        onClose={() => setParseModalOpen(false)}
        footer={
          <>
            <button type="button" onClick={() => setParseModalOpen(false)}>
              取消
            </button>
            <button
              type="button"
              className="primary"
              disabled={parsing || !selectedSessionId}
              onClick={() => void parseFromSession()}
            >
              {parsing ? '生成中…' : '开始生成'}
            </button>
          </>
        }
      >
        <div className="stack">
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            将从所选会话中最近一条含待办/提醒的助手回复生成任务清单（仅 checkbox、动作项与提醒，过滤说明与分析）。
          </p>
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
            selectedId={selectedSessionId}
            onSelect={(s) => setSelectedSessionId(s.id)}
            filter={sessionFilter}
            scopeWorkspaceId={scopeForSessionPick(scopeId)}
          />
        </div>
      </Modal>
    </>
  )
}
