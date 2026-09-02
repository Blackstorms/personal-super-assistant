/**
 * 专家市场：公开预置 / 个人自建，卡片栅格。
 * 专家仅管理人设；技能 / 连接器 / 资料库由对话或工作空间单独绑定。
 */
import { useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../lib/api'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import {
  MarketCard,
  MarketScopeTabs,
  MarketSection,
  groupByCategory,
  type MarketScope,
} from '../components/MarketShelf'

type Expert = {
  id: string
  name: string
  description?: string | null
  system_prompt: string
  model_profile_id?: string | null
  is_preset?: boolean
  category?: string
  badge?: string | null
  icon?: string
}

const emptyForm = () => ({
  name: '',
  description: '',
  system_prompt: '',
})

export default function ExpertsPage() {
  const [items, setItems] = useState<Expert[]>([])
  const [scope, setScope] = useState<MarketScope>('public')
  const [menuId, setMenuId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)
  const [viewOnly, setViewOnly] = useState(false)
  const [form, setForm] = useState(emptyForm())
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const load = async () => {
    const ex = await apiRequest<{ items: Expert[] }>('GET', '/api/v1/experts')
    setItems(ex.items)
  }

  useEffect(() => {
    load().catch((e) => showToast(String(e), 'error'))
  }, [])

  const visible = useMemo(() => {
    if (scope === 'public') return items.filter((e) => e.is_preset)
    return items.filter((e) => !e.is_preset)
  }, [items, scope])

  const sections = useMemo(() => groupByCategory(visible, scope === 'public' ? '其他' : '个人'), [visible, scope])

  const openCreate = () => {
    setEditId(null)
    setViewOnly(false)
    setForm(emptyForm())
    setModalOpen(true)
  }

  const openDetail = (e: Expert, mode: 'edit' | 'view') => {
    setEditId(e.id)
    setViewOnly(mode === 'view' || !!e.is_preset)
    setForm({
      name: e.name,
      description: e.description || '',
      system_prompt: e.system_prompt,
    })
    setModalOpen(true)
    setMenuId(null)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditId(null)
    setViewOnly(false)
    setForm(emptyForm())
  }

  const save = async () => {
    if (viewOnly) return
    setSaving(true)
    try {
      const body = {
        name: form.name || '未命名专家',
        description: form.description,
        system_prompt: form.system_prompt || '你是一名专业助手。',
        // 模型以对话时选择为准，专家不再绑定默认模型
        model_profile_id: null,
        // 页面不再关联技能 / 连接器 / 资料库；提交空列表以免保留旧绑定
        skill_ids: [] as string[],
        mcp_ids: [] as string[],
        knowledge_ids: [] as string[],
      }
      if (editId) {
        await apiRequest('PATCH', `/api/v1/experts/${editId}`, body)
        showToast('专家已更新')
      } else {
        await apiRequest('POST', '/api/v1/experts', body)
        showToast('专家已创建')
        setScope('personal')
      }
      closeModal()
      await load()
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (e: Expert) => {
    if (!window.confirm(`确定删除专家「${e.name}」？`)) return
    try {
      await apiRequest('DELETE', `/api/v1/experts/${e.id}`)
      showToast('已删除')
      setMenuId(null)
      await load()
    } catch (err) {
      showToast(String(err), 'error')
    }
  }

  return (
    <div className="market-page">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <MarketScopeTabs
        scope={scope}
        onChange={setScope}
        trailing={
          <button type="button" className="primary" onClick={openCreate}>
            新增专家
          </button>
        }
      />

      {sections.length === 0 ? (
        <div className="market-empty">
          {scope === 'public' ? '暂无公开专家预置。' : '还没有个人专家，点击「新增专家」创建。'}
        </div>
      ) : (
        sections.map((sec) => (
          <MarketSection key={sec.category} title={sec.category}>
            {sec.items.map((e) => (
              <MarketCard
                key={e.id}
                item={{
                  id: e.id,
                  name: e.name,
                  description: e.description || e.system_prompt,
                  category: e.category,
                  badge: e.badge,
                  icon: e.icon,
                  installed: true,
                }}
                onClick={() => openDetail(e, e.is_preset ? 'view' : 'edit')}
                menu={
                  <div className="market-menu-wrap">
                    <button
                      type="button"
                      className="market-menu-btn"
                      aria-label="更多"
                      onClick={() => setMenuId((id) => (id === e.id ? null : e.id))}
                    >
                      ···
                    </button>
                    {menuId === e.id ? (
                      <div className="market-menu">
                        {e.is_preset ? (
                          <button type="button" onClick={() => openDetail(e, 'view')}>
                            查看
                          </button>
                        ) : (
                          <>
                            <button type="button" onClick={() => openDetail(e, 'edit')}>
                              编辑
                            </button>
                            <button type="button" className="danger" onClick={() => void remove(e)}>
                              删除
                            </button>
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                }
              />
            ))}
          </MarketSection>
        ))
      )}

      <p className="market-foot">公开预置仅可查看；个人专家可编辑与删除。对话中可绑定专家人设。</p>

      <Modal
        open={modalOpen}
        wide
        title={viewOnly ? '查看专家' : editId ? '编辑专家' : '新增专家'}
        onClose={closeModal}
        footer={
          viewOnly ? (
            <button type="button" className="primary" onClick={closeModal}>
              关闭
            </button>
          ) : (
            <>
              <button type="button" onClick={closeModal}>
                取消
              </button>
              <button type="button" className="primary" disabled={saving} onClick={() => void save()}>
                {saving ? '保存中…' : '保存'}
              </button>
            </>
          )
        }
      >
        <div className="stack">
          <label className="muted">名称</label>
          <input
            value={form.name}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <label className="muted">描述</label>
          <input
            value={form.description}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <label className="muted">人设 / 系统提示</label>
          <textarea
            rows={5}
            value={form.system_prompt}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
            placeholder="例如：你是资深产品经理，擅长需求拆解与验收标准…"
          />
        </div>
      </Modal>
    </div>
  )
}
