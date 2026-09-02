import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatDateTime } from '../lib/formatTime'
import Toast from '../components/Toast'

type Detail = {
  id: string
  title: string
  created_at?: string
  updated_at?: string
  items: Array<{ id: string; content: string; done: boolean }>
}

export default function ChecklistDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [mdPath, setMdPath] = useState('')
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const load = async () => {
    if (!id) return
    setLoading(true)
    try {
      const d = await apiRequest<Detail>('GET', `/api/v1/checklists/${id}`)
      setDetail(d)
    } catch (e) {
      showToast(String(e), 'error')
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load().catch(console.error)
  }, [id])

  const doneCount = detail?.items.filter((i) => i.done).length ?? 0
  const total = detail?.items.length ?? 0

  const toggleItem = async (itemId: string, done: boolean) => {
    if (!detail) return
    try {
      await apiRequest('PATCH', `/api/v1/checklists/${detail.id}/items/${itemId}`, { done })
      setDetail({
        ...detail,
        items: detail.items.map((i) => (i.id === itemId ? { ...i, done } : i)),
      })
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const exportMarkdown = async () => {
    if (!detail) return
    try {
      let path = mdPath
      if (!path) {
        path =
          (window.api?.selectDirectory
            ? `${(await window.api.selectDirectory()) || ''}/checklist.md`
            : prompt('Markdown 文件绝对路径（须在白名单内）') || '') || ''
      }
      if (!path) return
      await apiRequest('POST', `/api/v1/checklists/${detail.id}/sync`, { target: 'file', path })
      showToast(`已写入 ${path}`)
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  if (!id) {
    return (
      <div className="stack">
        <p className="muted">无效的清单 ID</p>
        <Link to="/checklists">返回列表</Link>
      </div>
    )
  }

  return (
    <div className="stack">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <button type="button" className="ghost" onClick={() => navigate('/checklists')}>
            ← 返回清单列表
          </button>
          {detail && (
            <>
              <h2 style={{ margin: '8px 0 4px' }}>{detail.title}</h2>
              <p className="muted">
                进度 {doneCount}/{total}
                {total > 0 ? ` · ${Math.round((doneCount / total) * 100)}%` : ''}
                {' · '}录入 {formatDateTime(detail.created_at)}
              </p>
            </>
          )}
        </div>
        {detail && (
          <div className="row">
            <button type="button" onClick={() => void exportMarkdown()}>
              导出 Markdown
            </button>
          </div>
        )}
      </div>

      {loading && <div className="panel muted">加载中…</div>}

      {!loading && !detail && (
        <div className="panel stack">
          <p className="muted">清单不存在或已删除。</p>
          <button type="button" onClick={() => navigate('/checklists')}>
            返回列表
          </button>
        </div>
      )}

      {detail && (
        <>
          <div className="panel stack">
            {detail.items.length === 0 ? (
              <p className="muted">此清单还没有任务项。</p>
            ) : (
              detail.items.map((i) => (
                <label key={i.id} className="row checklist-item">
                  <input type="checkbox" checked={i.done} onChange={(e) => void toggleItem(i.id, e.target.checked)} />
                  <span className={i.done ? 'muted' : ''} style={i.done ? { textDecoration: 'line-through' } : undefined}>
                    {i.content}
                  </span>
                </label>
              ))
            )}
          </div>
          <div className="panel row">
            <input
              value={mdPath}
              onChange={(e) => setMdPath(e.target.value)}
              placeholder="可选：默认 Markdown 导出路径（白名单内）"
              style={{ flex: 1 }}
            />
          </div>
        </>
      )}
    </div>
  )
}
