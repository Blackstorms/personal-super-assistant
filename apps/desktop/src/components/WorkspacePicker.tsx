/**
 * 新建对话时选择工作空间：已有项目 / 打开本地文件夹（首条消息再建空间）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import {
  folderBasename,
  isFolderWorkspace,
  pickLocalFolderPath,
  type WorkspaceItem,
} from '../lib/folderWorkspace'
import { useAppStore } from '../stores/app'

type Props = {
  /** 已有会话时仅展示当前绑定，不可切换 */
  locked?: boolean
}

const IconProject = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 7h16v12H4zM8 7V5h8v2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const IconFolder = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M3 7h6l2 2h10v10a1 1 0 01-1 1H4a1 1 0 01-1-1V7z" strokeLinejoin="round" />
  </svg>
)

const IconChevron = ({ up }: { up?: boolean }) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d={up ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export default function WorkspacePicker({ locked = false }: Props) {
  const navigate = useNavigate()
  const {
    workspaceId,
    pendingFolderPath,
    setWorkspaceId,
    setPendingFolderPath,
    clearWorkspaceSelection,
    requestApplyWorkspaceDefaults,
  } = useAppStore()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<WorkspaceItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    const data = await apiRequest<{ items: WorkspaceItem[] }>('GET', '/api/v1/workspaces')
    setItems((data.items || []).filter((w) => w.status === 'active' || !w.status))
  }

  useEffect(() => {
    void load().catch(() => setItems([]))
  }, [workspaceId])

  useEffect(() => {
    if (!open) return
    void load().catch((e) => setError(String(e)))
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const current = useMemo(() => items.find((w) => w.id === workspaceId) || null, [items, workspaceId])
  const q = query.trim().toLowerCase()
  const filtered = useMemo(() => {
    if (!q) return items
    return items.filter(
      (w) =>
        w.name.toLowerCase().includes(q) ||
        (w.description || '').toLowerCase().includes(q) ||
        (w.root_paths || []).some((p) => p.toLowerCase().includes(q)),
    )
  }, [items, q])

  const selectWorkspace = (id: string | null) => {
    if (locked) return
    if (id) {
      setWorkspaceId(id)
      requestApplyWorkspaceDefaults()
    } else {
      clearWorkspaceSelection()
    }
    setOpen(false)
    setQuery('')
  }

  const openLocalFolder = async () => {
    if (locked || busy) return
    setBusy(true)
    setError('')
    try {
      const path = await pickLocalFolderPath()
      if (!path) return
      // 仅暂存路径；首条消息时再创建空间并出现在侧栏
      setPendingFolderPath(path)
      setOpen(false)
      setQuery('')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const pendingName = pendingFolderPath ? folderBasename(pendingFolderPath) : null
  const label = current ? current.name : pendingName || '选择工作空间'
  const KindIcon = current && isFolderWorkspace(current) ? IconFolder : pendingFolderPath ? IconFolder : IconProject
  const titleHint =
    current?.description ||
    current?.root_paths?.[0] ||
    pendingFolderPath ||
    '选择工作空间'

  return (
    <div className={`ws-picker ${open ? 'open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className="ws-picker-trigger"
        disabled={locked}
        title={locked ? '当前会话已绑定工作空间' : titleHint}
        onClick={() => {
          if (locked) return
          setOpen((v) => !v)
        }}
      >
        <KindIcon />
        <span className="ws-picker-label">{label}</span>
        {!locked ? <IconChevron up={open} /> : null}
      </button>

      {open && !locked ? (
        <div className="ws-picker-menu" role="listbox">
          <div className="ws-picker-search">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索工作空间"
              autoFocus
            />
          </div>
          <div className="ws-picker-list">
            <button
              type="button"
              className={`ws-picker-item ${!workspaceId && !pendingFolderPath ? 'active' : ''}`}
              onClick={() => selectWorkspace(null)}
            >
              <span className="muted">不绑定（独立任务）</span>
            </button>
            {pendingFolderPath ? (
              <button type="button" className="ws-picker-item active" title={pendingFolderPath}>
                <IconFolder />
                <span className="ws-picker-item-text">
                  <span className="ws-picker-item-name">{pendingName}</span>
                  <span className="muted ws-picker-item-path">{pendingFolderPath}（发送后创建）</span>
                </span>
              </button>
            ) : null}
            {filtered.map((w) => {
              const folder = isFolderWorkspace(w)
              return (
                <button
                  key={w.id}
                  type="button"
                  className={`ws-picker-item ${workspaceId === w.id ? 'active' : ''}`}
                  title={w.root_paths?.[0] || w.description || w.name}
                  onClick={() => selectWorkspace(w.id)}
                >
                  {folder ? <IconFolder /> : <IconProject />}
                  <span className="ws-picker-item-text">
                    <span className="ws-picker-item-name">{w.name}</span>
                    {folder && w.root_paths?.[0] ? (
                      <span className="muted ws-picker-item-path">{w.root_paths[0]}</span>
                    ) : null}
                  </span>
                </button>
              )
            })}
            {filtered.length === 0 && !pendingFolderPath ? (
              <div className="muted ws-picker-empty">无匹配工作空间</div>
            ) : null}
          </div>
          <div className="ws-picker-actions">
            <button
              type="button"
              className="ws-picker-action"
              onClick={() => {
                setOpen(false)
                navigate('/projects')
              }}
            >
              <span aria-hidden>+</span>
              新建工作空间
            </button>
            <button type="button" className="ws-picker-action" disabled={busy} onClick={() => void openLocalFolder()}>
              <IconFolder />
              {busy ? '处理中…' : '打开本地文件夹'}
            </button>
          </div>
          {error ? <div className="ws-picker-error">{error}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
