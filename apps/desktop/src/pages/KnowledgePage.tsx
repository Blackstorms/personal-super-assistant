/**
 * 资料库两级：先创建知识库，再在库内添加文件/文件夹。
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { apiRequest } from '../lib/api'
import { formatDateTime } from '../lib/formatTime'
import Modal from '../components/Modal'
import Toast from '../components/Toast'

type KnowledgeBase = {
  id: string
  name: string
  description?: string | null
  doc_count: number
  state: string
  created_at?: string
  updated_at: string
}

type Doc = {
  id: string
  name: string
  path: string
  indexed_at?: string
  source_type?: string
  viewable?: boolean
  editable?: boolean
  searchable?: boolean
  index_status?: string
}

const INDEX_STATUS_LABEL: Record<string, string> = {
  indexed: '可检索',
  pending: '待索引',
  empty: '无正文',
  pdf_empty: 'PDF 无文本',
  docx_empty: 'Word 无文本',
  unsupported: '不支持检索',
  missing: '文件缺失',
}

type SearchHit = { path: string; snippet: string; score?: number }

const TEXT_EXT = /\.(txt|md|json|csv|xml|html|htm|js|ts|tsx|jsx|py|yaml|yml|log|ini|toml|sql|rst)$/i

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const raw = String(reader.result || '')
      const idx = raw.indexOf(',')
      resolve(idx >= 0 ? raw.slice(idx + 1) : raw)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

async function fileToUploadPayload(file: File): Promise<{ name: string; content: string; encoding: string }> {
  const isText = file.type.startsWith('text/') || TEXT_EXT.test(file.name)
  if (isText && file.size <= 512_000) {
    return { name: file.name, content: await file.text(), encoding: 'utf-8' }
  }
  return { name: file.name, content: await readFileAsBase64(file), encoding: 'base64' }
}

function base64ToPdfUrl(b64: string): string {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'application/pdf' })
  return URL.createObjectURL(blob)
}

export default function KnowledgePage() {
  const [bases, setBases] = useState<KnowledgeBase[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [docs, setDocs] = useState<Doc[]>([])
  const [newName, setNewName] = useState('')
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [savingDoc, setSavingDoc] = useState(false)
  const [viewEditing, setViewEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [viewPdfUrl, setViewPdfUrl] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [searching, setSearching] = useState(false)
  const [viewDoc, setViewDoc] = useState<Doc | null>(null)
  const [viewContent, setViewContent] = useState('')
  const [viewLoading, setViewLoading] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; baseId: string } | null>(null)
  const [editingBaseId, setEditingBaseId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadingRef = useRef(false)

  const selected = bases.find((b) => b.id === selectedId) || null

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const loadBases = async () => {
    // 资料库为全局「我的资料」，不按侧栏当前工作空间过滤
    const data = await apiRequest<{ items: KnowledgeBase[] }>('GET', '/api/v1/knowledge/bases')
    setBases(data.items)
    if (selectedId && !data.items.some((b) => b.id === selectedId)) {
      setSelectedId(data.items[0]?.id || null)
    } else if (!selectedId && data.items[0]) {
      setSelectedId(data.items[0].id)
    }
  }

  const loadDocs = async (baseId: string) => {
    const data = await apiRequest<{ items: Doc[] }>('GET', `/api/v1/knowledge/bases/${baseId}/documents`)
    setDocs(data.items)
  }

  useEffect(() => {
    loadBases().catch((e) => showToast(String(e), 'error'))
  }, [])

  useEffect(() => {
    if (selectedId) loadDocs(selectedId).catch(console.error)
    else setDocs([])
  }, [selectedId])

  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [contextMenu])

  const openCreate = () => {
    setNewName('')
    setModalOpen(true)
  }

  const createBase = async () => {
    setSaving(true)
    try {
      const name = newName.trim() || '未命名知识库'
      const created = await apiRequest<KnowledgeBase>('POST', '/api/v1/knowledge/bases', {
        name,
        workspace_id: null,
      })
      setModalOpen(false)
      setNewName('')
      showToast(`已创建知识库「${created.name}」`)
      await loadBases()
      setSelectedId(created.id)
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const openEditBase = (base?: KnowledgeBase) => {
    const target = base ?? selected
    if (!target) return
    setEditingBaseId(target.id)
    setEditName(target.name)
    setEditDescription(target.description || '')
    setEditModalOpen(true)
    setContextMenu(null)
  }

  const saveBase = async () => {
    const baseId = editingBaseId || selected?.id
    if (!baseId) return
    const current = bases.find((b) => b.id === baseId)
    setSaving(true)
    try {
      const updated = await apiRequest<KnowledgeBase>('PATCH', `/api/v1/knowledge/bases/${baseId}`, {
        name: editName.trim() || current?.name || '未命名知识库',
        description: editDescription.trim() || null,
      })
      setEditModalOpen(false)
      setEditingBaseId(null)
      showToast('知识库已更新')
      setBases((prev) => prev.map((b) => (b.id === updated.id ? { ...b, ...updated } : b)))
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const deleteBase = async (base: KnowledgeBase) => {
    setContextMenu(null)
    if (!confirm(`删除知识库「${base.name}」？`)) return
    await apiRequest('DELETE', `/api/v1/knowledge/bases/${base.id}`)
    if (selectedId === base.id) setSelectedId(null)
    await loadBases()
    showToast('知识库已删除')
  }

  const uploadItems = async (payload: {
    paths?: string[]
    files?: Array<{ name: string; content: string; encoding: string }>
  }) => {
    if (!selectedId) {
      showToast('请先选择知识库', 'error')
      return
    }
    if (uploadingRef.current) return
    uploadingRef.current = true
    setUploading(true)
    const baseId = selectedId
    try {
      const r = await apiRequest<{
        copied?: string[]
        reindex?: { doc_count?: number; state?: string }
        documents?: Doc[]
        base?: KnowledgeBase
      }>('POST', `/api/v1/knowledge/bases/${baseId}/items`, payload)
      const copiedN = r.copied?.length ?? 0
      const indexedN = r.reindex?.doc_count ?? 0
      if (copiedN > 0) {
        showToast(
          indexedN > 0
            ? `已添加 ${copiedN} 个文件（${indexedN} 个已建立索引）`
            : `已添加 ${copiedN} 个文件（暂无可检索正文，仍可在列表中查看）`,
        )
      } else {
        showToast('已添加文件')
      }
      if (r.base) {
        setBases((prev) => prev.map((b) => (b.id === baseId ? { ...b, ...r.base! } : b)))
      } else {
        await loadBases()
      }
      if (r.documents) {
        setDocs(r.documents)
      } else {
        await loadDocs(baseId)
      }
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      uploadingRef.current = false
      setUploading(false)
    }
  }

  /** 快速添加：Electron 走本地路径复制；浏览器走文件内容上传 */
  const addFiles = async () => {
    if (!selectedId) {
      showToast('请先选择知识库', 'error')
      return
    }
    if (window.api?.selectFiles) {
      try {
        const paths = await window.api.selectFiles()
        if (!paths?.length) return
        await uploadItems({ paths })
      } catch (e) {
        showToast(String(e), 'error')
      }
      return
    }
    fileInputRef.current?.click()
  }

  /** 添加文件夹：复制本地目录进库 */
  const addFolder = async () => {
    if (!selectedId) {
      showToast('请先选择知识库', 'error')
      return
    }
    const dir = window.api?.selectDirectory ? await window.api.selectDirectory() : null
    if (!dir) return
    await uploadItems({ paths: [dir] })
  }

  const onFilesPicked = async (e: ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files
    e.target.value = ''
    if (!list?.length || !selectedId || uploadingRef.current) return
    try {
      const files = await Promise.all(Array.from(list).map((f) => fileToUploadPayload(f)))
      await uploadItems({ files })
    } catch (err) {
      showToast(String(err), 'error')
    }
  }

  const openDocument = async (d: Doc, editing = false) => {
    if (!selectedId) return
    if (d.viewable === false) {
      showToast('该文件类型暂不支持在线预览', 'error')
      return
    }
    if (editing && !d.editable) {
      showToast('该文件不可编辑', 'error')
      return
    }
    setViewDoc(d)
    setViewContent('')
    setEditContent('')
    setViewPdfUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
    setViewEditing(editing)
    setViewLoading(true)
    try {
      const data = await apiRequest<{
        content: string
        name: string
        encoding?: string
        mime_type?: string
      }>('GET', `/api/v1/knowledge/bases/${selectedId}/documents/${d.id}/content`)
      if (data.encoding === 'base64' && data.mime_type === 'application/pdf') {
        setViewPdfUrl(base64ToPdfUrl(data.content))
        setViewContent('')
      } else {
        setViewContent(data.content)
        setEditContent(data.content)
      }
    } catch (e) {
      setViewDoc(null)
      setViewEditing(false)
      showToast(String(e), 'error')
    } finally {
      setViewLoading(false)
    }
  }

  const closeView = () => {
    setViewDoc(null)
    setViewContent('')
    setEditContent('')
    setViewEditing(false)
    setViewPdfUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
  }

  const saveDocument = async () => {
    if (!selectedId || !viewDoc) return
    setSavingDoc(true)
    try {
      const data = await apiRequest<{ content: string }>(
        'PATCH',
        `/api/v1/knowledge/bases/${selectedId}/documents/${viewDoc.id}/content`,
        { content: editContent },
      )
      setViewContent(data.content)
      setViewEditing(false)
      showToast('文件已保存并重建索引')
      await loadDocs(selectedId)
      await loadBases()
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSavingDoc(false)
    }
  }

  const searchInBase = async () => {
    if (!selectedId || !query.trim()) {
      setHits([])
      return
    }
    setSearching(true)
    try {
      const r = await apiRequest<{ items: SearchHit[] }>('POST', '/api/v1/knowledge/search', {
        knowledge_ids: [selectedId],
        query,
      })
      setHits(r.items)
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="kb-layout">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <aside className="kb-side">
        <div className="kb-side-head">
          <h2>资料库</h2>
          <button type="button" className="icon-btn" title="新建知识库" onClick={openCreate}>
            +
          </button>
        </div>
        <div className="kb-side-label">我的资料</div>
        <div className="kb-base-list">
          {bases.length === 0 && (
            <div className="muted" style={{ padding: '8px 10px', fontSize: 12 }}>
              还没有知识库，点右上角 + 先创建
            </div>
          )}
          {bases.map((b) => (
            <button
              key={b.id}
              type="button"
              className={`kb-base-item ${selectedId === b.id ? 'active' : ''}`}
              onClick={() => setSelectedId(b.id)}
              onContextMenu={(e) => {
                e.preventDefault()
                setSelectedId(b.id)
                setContextMenu({ x: e.clientX, y: e.clientY, baseId: b.id })
              }}
            >
              <span className="kb-folder-icon">📁</span>
              <span className="kb-base-text">
                <span className="kb-base-name">{b.name}</span>
                <span className="kb-base-meta muted">录入 {formatDateTime(b.created_at)}</span>
              </span>
              <span className="muted">{b.doc_count}</span>
            </button>
          ))}
        </div>
      </aside>

      {contextMenu && (
        <div
          className="ctx-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            className="ctx-menu-item"
            onClick={() => {
              const base = bases.find((x) => x.id === contextMenu.baseId)
              if (base) openEditBase(base)
            }}
          >
            编辑
          </button>
          <button
            type="button"
            className="ctx-menu-item danger"
            onClick={() => {
              const base = bases.find((x) => x.id === contextMenu.baseId)
              if (base) void deleteBase(base)
            }}
          >
            删除
          </button>
        </div>
      )}

      <section className="kb-main">
        {!selected ? (
          <div className="kb-empty muted">
            <p>先创建知识库，再向库中添加文件或文件夹。</p>
            <button type="button" className="primary" onClick={openCreate}>
              新建知识库
            </button>
          </div>
        ) : (
          <>
            <div className="kb-crumb muted">我的资料 / {selected.name}</div>
            <div className="kb-main-head">
              <div>
                <h2>{selected.name}</h2>
                <p className="muted">
                  {selected.doc_count} 个文档 · {selected.state}
                  {selected.description ? ` · ${selected.description}` : ''}
                  {' · '}录入 {formatDateTime(selected.created_at)}
                </p>
              </div>
              <div className="row">
                <button type="button" className="primary" disabled={uploading} onClick={() => void addFiles()}>
                  {uploading ? '上传中…' : '快速添加'}
                </button>
                <button type="button" disabled={uploading} onClick={() => void addFolder()}>
                  添加文件夹
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await apiRequest('POST', `/api/v1/knowledge/bases/${selected.id}/reindex`)
                    showToast('已重建索引')
                    await loadBases()
                    await loadDocs(selected.id)
                  }}
                >
                  重建索引
                </button>
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              accept=".md,.txt,.json,.csv,.py,.js,.ts,.tsx,.jsx,.html,.htm,.xml,.yaml,.yml,.log,.pdf,.doc,.docx"
              onChange={(e) => void onFilesPicked(e)}
            />

            <div className="panel row kb-search-bar">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={`在「${selected.name}」中检索`}
                style={{ flex: 1 }}
                disabled={searching}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void searchInBase()
                  }
                }}
              />
            </div>

            {hits.length > 0 && (
              <div className="panel stack kb-hits">
                {hits.map((h, i) => (
                  <div key={`${h.path}-${i}`} className="kb-hit-item">
                    <div className="muted" style={{ fontSize: 12 }}>
                      {h.path}
                    </div>
                    <div>{h.snippet}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="panel kb-doc-panel">
              <div className="kb-doc-table-wrap">
              <table className="table kb-doc-table">
                <colgroup>
                  <col className="kb-col-name" />
                  <col className="kb-col-type" />
                  <col className="kb-col-time" />
                  <col className="kb-col-actions" />
                </colgroup>
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>类型</th>
                    <th>录入时间</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {docs.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted">
                        库内还没有文件。点击「快速添加」上传文件或文件夹。
                      </td>
                    </tr>
                  )}
                  {docs.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <button
                          type="button"
                          className="list-link"
                          disabled={d.viewable === false}
                          title={d.viewable === false ? '该类型暂不支持预览' : '查看文件'}
                          onClick={() => void openDocument(d)}
                        >
                          {d.name}
                        </button>
                      </td>
                      <td className="muted kb-doc-type">
                        {d.source_type === 'path' ? '挂载' : '上传'}
                        {' · '}
                        {INDEX_STATUS_LABEL[d.index_status || ''] ||
                          (d.searchable ? '可检索' : '不可检索')}
                      </td>
                      <td className="muted kb-doc-time">{formatDateTime(d.indexed_at)}</td>
                      <td className="actions-cell">
                        <div className="table-actions">
                          {d.viewable !== false && (
                            <button type="button" className="ghost sm" onClick={() => void openDocument(d)}>
                              查看
                            </button>
                          )}
                          {d.editable && (
                            <button type="button" className="ghost sm" onClick={() => void openDocument(d, true)}>
                              编辑
                            </button>
                          )}
                          <button
                            type="button"
                            className="ghost sm danger"
                            onClick={async () => {
                              await apiRequest('DELETE', `/api/v1/knowledge/bases/${selected.id}/documents/${d.id}`)
                              await loadDocs(selected.id)
                              await loadBases()
                            }}
                          >
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
              {docs.length > 0 && (
                <div className="muted" style={{ padding: '10px 12px', fontSize: 12 }}>
                  已经到底了
                </div>
              )}
            </div>
          </>
        )}
      </section>

      <Modal
        open={modalOpen}
        title="新建知识库"
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <button type="button" onClick={() => setModalOpen(false)}>
              取消
            </button>
            <button type="button" className="primary" disabled={saving} onClick={() => void createBase()}>
              {saving ? '创建中…' : '创建'}
            </button>
          </>
        }
      >
        <div className="stack">
          <label className="muted">知识库名称</label>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="知识库名称"
            onKeyDown={(e) => {
              if (e.key === 'Enter') void createBase()
            }}
          />
        </div>
      </Modal>

      <Modal
        open={editModalOpen}
        title="编辑知识库"
        onClose={() => {
          setEditModalOpen(false)
          setEditingBaseId(null)
        }}
        footer={
          <>
            <button
              type="button"
              onClick={() => {
                setEditModalOpen(false)
                setEditingBaseId(null)
              }}
            >
              取消
            </button>
            <button type="button" className="primary" disabled={saving || !editName.trim()} onClick={() => void saveBase()}>
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        }
      >
        <div className="stack">
          <label className="muted">知识库名称</label>
          <input
            autoFocus
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            placeholder="知识库名称"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && editName.trim() && !saving) void saveBase()
            }}
          />
          <label className="muted">描述（可选）</label>
          <textarea
            rows={3}
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
            placeholder="简要说明该知识库的用途"
          />
        </div>
      </Modal>

      <Modal
        open={Boolean(viewDoc)}
        wide
        title={viewDoc ? `${viewEditing ? '编辑' : '查看'} · ${viewDoc.name}` : '查看文件'}
        onClose={closeView}
        footer={
          <>
            {viewDoc?.editable && !viewEditing && !viewPdfUrl && (
              <button type="button" onClick={() => setViewEditing(true)}>
                编辑
              </button>
            )}
            {viewEditing && (
              <button type="button" onClick={() => {
                setViewEditing(false)
                setEditContent(viewContent)
              }}>
                取消编辑
              </button>
            )}
            {viewEditing && (
              <button
                type="button"
                className="primary"
                disabled={savingDoc}
                onClick={() => void saveDocument()}
              >
                {savingDoc ? '保存中…' : '保存'}
              </button>
            )}
            <button type="button" onClick={closeView}>
              关闭
            </button>
          </>
        }
      >
        {viewLoading ? (
          <p className="muted">加载中…</p>
        ) : viewEditing ? (
          <textarea
            className="kb-doc-edit"
            rows={20}
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            spellCheck={false}
          />
        ) : viewPdfUrl ? (
          <iframe className="kb-doc-pdf" src={viewPdfUrl} title={viewDoc?.name || 'PDF 预览'} />
        ) : (
          <pre className="kb-doc-view">{viewContent}</pre>
        )}
      </Modal>
    </div>
  )
}
