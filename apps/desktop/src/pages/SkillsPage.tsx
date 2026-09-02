import { useEffect, useMemo, useRef, useState } from 'react'
import { apiRequest } from '../lib/api'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import {
  MarketCard,
  MarketScopeTabs,
  MarketSection,
  SKILL_MARKET_META,
  groupByCategory,
  type MarketScope,
} from '../components/MarketShelf'

type Skill = {
  id: string
  name: string
  description: string
  enabled: boolean
  triggers: string[]
  permissions?: string[]
  version?: string
  body?: string
}

type HermesSkillItem = {
  id: string
  name: string
  description: string
  source?: string
  identifier?: string
  imported?: boolean
  trust_level?: string
}

const HERMES_SOURCE_LABEL: Record<string, string> = {
  plugin: '插件',
  'hermes-home': '已安装',
  bundled: '内置',
  optional: '官方可选',
  official: '官方',
  hub: 'Hub',
  github: 'GitHub',
  clawhub: 'ClawHub',
  lobehub: 'LobeHub',
  'skills-sh': 'skills.sh',
}

type SkillForm = {
  id: string
  name: string
  description: string
  triggersText: string
  permissionsText: string
  body: string
  version: string
  enabled: boolean
}

const emptyForm = (): SkillForm => ({
  id: '',
  name: '',
  description: '',
  triggersText: '',
  permissionsText: '',
  body: '',
  version: '1.0',
  enabled: true,
})

const splitList = (text: string) =>
  text
    .split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean)

const joinList = (items: string[]) => items.join(', ')

const formFromSkill = (detail: Skill): SkillForm => ({
  id: detail.id,
  name: detail.name,
  description: detail.description || '',
  triggersText: joinList(detail.triggers || []),
  permissionsText: joinList(detail.permissions || []),
  body: detail.body || '',
  version: detail.version || '1.0',
  enabled: detail.enabled,
})

export default function SkillsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const importModeRef = useRef<'direct' | 'fill'>('direct')
  const addMenuRef = useRef<HTMLDivElement>(null)
  const [items, setItems] = useState<Skill[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [viewOnly, setViewOnly] = useState(false)
  const [form, setForm] = useState(emptyForm())
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [bundles, setBundles] = useState<Array<{ id: string; name: string; skills: string[] }>>([])
  const [pendingWrites, setPendingWrites] = useState<Array<{ id: string; skill_id: string; action: string }>>([])
  const [hubQuery, setHubQuery] = useState('')
  const [hubItems, setHubItems] = useState<HermesSkillItem[]>([])
  const [hubBusy, setHubBusy] = useState(false)
  const [addingId, setAddingId] = useState<string | null>(null)
  const [hubMode, setHubMode] = useState<'local' | 'search'>('local')
  const [scope, setScope] = useState<MarketScope>('public')
  const [menuId, setMenuId] = useState<string | null>(null)
  const [addMenuOpen, setAddMenuOpen] = useState(false)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  useEffect(() => {
    if (!addMenuOpen) return
    const onDoc = (e: MouseEvent) => {
      if (addMenuRef.current && !addMenuRef.current.contains(e.target as Node)) {
        setAddMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [addMenuOpen])

  const load = async () => {
    const data = await apiRequest<{ items: Skill[] }>('GET', '/api/v1/skills')
    setItems(data.items)
    try {
      const b = await apiRequest<{ items: Array<{ id: string; name: string; skills: string[] }> }>(
        'GET',
        '/api/v1/skills/bundles',
      )
      setBundles(b.items || [])
    } catch {
      setBundles([])
    }
    try {
      const p = await apiRequest<{ items: Array<{ id: string; skill_id: string; action: string }> }>(
        'GET',
        '/api/v1/skills/pending-writes',
      )
      setPendingWrites(p.items || [])
    } catch {
      setPendingWrites([])
    }
  }

  const loadHermesCatalog = async () => {
    setHubBusy(true)
    try {
      const r = await apiRequest<{ items: HermesSkillItem[] }>('GET', '/api/v1/skills/hermes/catalog')
      setHubItems(r.items || [])
      setHubMode('local')
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setHubBusy(false)
    }
  }

  const searchHermesHub = async () => {
    const q = hubQuery.trim()
    if (!q) {
      await loadHermesCatalog()
      return
    }
    setHubBusy(true)
    try {
      const r = await apiRequest<{ items: HermesSkillItem[] }>('POST', '/api/v1/skills/hub/search', {
        query: q,
      })
      setHubItems(r.items || [])
      setHubMode('search')
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setHubBusy(false)
    }
  }

  const addHermesSkill = async (h: HermesSkillItem) => {
    const identifier = h.identifier || h.id
    if (!identifier || identifier === 'hint' || identifier === 'error') return
    setAddingId(identifier)
    try {
      const created = await apiRequest<Skill>('POST', '/api/v1/skills/hermes/import', { identifier })
      showToast(`已添加 /${created.id}`)
      await load()
      setHubItems((prev) =>
        prev.map((it) =>
          (it.identifier || it.id) === identifier || it.id === created.id ? { ...it, imported: true, id: created.id } : it,
        ),
      )
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setAddingId(null)
    }
  }

  useEffect(() => {
    load().catch((e) => showToast(String(e), 'error'))
    loadHermesCatalog().catch((e) => showToast(String(e), 'error'))
  }, [])

  const openCreate = () => {
    setEditId(null)
    setViewOnly(false)
    setForm(emptyForm())
    setModalOpen(true)
  }

  const openDetail = async (s: Skill, mode: 'edit' | 'view' = 'edit') => {
    const preset = !!SKILL_MARKET_META[s.id]
    setEditId(s.id)
    setViewOnly(mode === 'view' || preset)
    try {
      const detail = await apiRequest<Skill>('GET', `/api/v1/skills/${s.id}`)
      setForm(formFromSkill(detail))
      setModalOpen(true)
      setMenuId(null)
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const pickMdFile = (mode: 'direct' | 'fill') => {
    importModeRef.current = mode
    fileInputRef.current?.click()
  }

  const handleMdFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.md')) {
      showToast('请选择 .md 文件', 'error')
      return
    }
    const content = await file.text()
    const fallbackId = file.name.replace(/\.md$/i, '')
    try {
      if (importModeRef.current === 'fill') {
        const detail = await apiRequest<Skill>('POST', '/api/v1/skills/parse', {
          content,
          fallback_id: fallbackId,
        })
        setEditId(null)
        setViewOnly(false)
        setForm(formFromSkill(detail))
        setModalOpen(true)
        showToast('已从 MD 填充表单，确认后保存')
      } else {
        const created = await apiRequest<Skill>('POST', '/api/v1/skills/import', {
          content,
          fallback_id: fallbackId,
        })
        showToast(`已导入技能 /${created.id}`)
        setScope('personal')
        await load()
      }
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditId(null)
    setViewOnly(false)
    setForm(emptyForm())
  }

  const save = async () => {
    if (viewOnly) return
    const skillId = form.id.trim()
    if (!editId && !skillId) {
      showToast('请填写技能 ID（斜杠名）', 'error')
      return
    }
    if (!editId && !/^[a-zA-Z0-9_-]+$/.test(skillId)) {
      showToast('技能 ID 仅允许字母、数字、下划线与连字符', 'error')
      return
    }
    if (!form.name.trim()) {
      showToast('请填写名称', 'error')
      return
    }

    setSaving(true)
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim(),
        triggers: splitList(form.triggersText),
        permissions: splitList(form.permissionsText),
        body: form.body,
        version: form.version.trim() || '1.0',
        enabled: form.enabled,
      }
      if (editId) {
        await apiRequest('PATCH', `/api/v1/skills/${editId}`, payload)
        showToast('技能已更新')
      } else {
        await apiRequest('POST', '/api/v1/skills', { id: skillId, ...payload })
        showToast('技能已创建')
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

  const removeSkill = async (s: Skill) => {
    if (!window.confirm(`确定删除技能「/${s.id} · ${s.name}」？此操作不可恢复。`)) return
    try {
      await apiRequest('DELETE', `/api/v1/skills/${s.id}`)
      showToast('技能已删除')
      await load()
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const toggleEnabled = async (s: Skill) => {
    try {
      await apiRequest('PATCH', `/api/v1/skills/${s.id}`, { enabled: !s.enabled })
      await load()
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const dryRun = async (s: Skill) => {
    try {
      await apiRequest('POST', `/api/v1/skills/${s.id}/run`, { input: '试运行示例输入' })
      showToast(`/${s.id} 试运行完成`)
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const localCards = useMemo(
    () =>
      items.map((s) => {
        const meta = SKILL_MARKET_META[s.id] || { category: '个人', icon: 'skill' }
        return {
          ...s,
          category: meta.category,
          icon: meta.icon,
          badge: meta.badge,
          installed: true as const,
        }
      }),
    [items],
  )

  const hubCards = useMemo(() => {
    const own = new Set(items.map((x) => x.id))
    return (hubItems || [])
      .filter((h) => h.id !== 'error' && h.id !== 'hint')
      .map((h) => {
        const identifier = h.identifier || h.id
        const imported = own.has(h.id) || !!h.imported
        return {
          id: identifier,
          name: h.name || h.id,
          description: h.description,
          category: HERMES_SOURCE_LABEL[h.source || ''] || h.source || 'Hub',
          icon: 'skill',
          badge: h.trust_level === 'official' ? '官方' : undefined,
          installed: imported,
          raw: h,
        }
      })
  }, [hubItems, items])

  const publicSections = useMemo(() => {
    if (hubMode === 'search' || hubQuery.trim()) {
      return groupByCategory(hubCards, 'Hub')
    }
    // 公开：本地预置技能按类别 + Hub 目录
    const localPreset = localCards.filter((s) => SKILL_MARKET_META[s.id])
    const sections: Array<{
      category: string
      items: Array<(typeof localCards)[number] | (typeof hubCards)[number]>
    }> = groupByCategory(localPreset, '生产力')
    if (hubCards.length) {
      sections.push({
        category: 'Hermes / Hub',
        items: hubCards.filter((h) => !h.installed).slice(0, 24),
      })
    }
    return sections
  }, [localCards, hubCards, hubMode, hubQuery])

  const personalSections = useMemo(() => {
    // 个人：仅自建 / 导入，不含公开预置（预置在「公开」Tab）
    const personal = localCards.filter((s) => !SKILL_MARKET_META[s.id])
    return groupByCategory(personal, '个人')
  }, [localCards])

  const sections = scope === 'public' ? publicSections : personalSections

  return (
    <div className="market-page">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <MarketScopeTabs
        scope={scope}
        onChange={setScope}
        trailing={
          <>
            <input
              style={{ width: 200 }}
              value={hubQuery}
              placeholder="搜索 Hub 技能"
              onChange={(e) => setHubQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  setScope('public')
                  void searchHermesHub()
                }
              }}
            />
            <div className="mcp-add-wrap" ref={addMenuRef}>
              <button type="button" className="primary" onClick={() => setAddMenuOpen((v) => !v)}>
                新增技能 ▾
              </button>
              {addMenuOpen ? (
                <div className="mcp-add-menu">
                  <button
                    type="button"
                    onClick={() => {
                      setAddMenuOpen(false)
                      openCreate()
                    }}
                  >
                    手动新增
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAddMenuOpen(false)
                      pickMdFile('direct')
                    }}
                  >
                    导入 MD
                  </button>
                </div>
              ) : null}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,text/markdown"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void handleMdFile(file)
              }}
            />
          </>
        }
      />

      {(bundles.length > 0 || pendingWrites.length > 0) && scope === 'personal' ? (
        <div className="panel stack">
          {bundles.length > 0 && (
            <>
              <h3 style={{ margin: 0 }}>技能 Bundle</h3>
              <ul>
                {bundles.map((b) => (
                  <li key={b.id}>
                    <code>/{b.name}</code> → {(b.skills || []).join(', ')}
                  </li>
                ))}
              </ul>
            </>
          )}
          {pendingWrites.length > 0 && (
            <>
              <h3 style={{ margin: 0 }}>待审批技能写入</h3>
              <ul>
                {pendingWrites.map((p) => (
                  <li key={p.id}>
                    {p.action} <code>{p.skill_id}</code>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : null}

      {sections.length === 0 || sections.every((s) => s.items.length === 0) ? (
        <div className="market-empty">
          {scope === 'public' ? '暂无公开技能，可搜索 Hub 或导入 MD。' : '还没有个人技能。'}
        </div>
      ) : (
        sections.map((sec) =>
          sec.items.length === 0 ? null : (
            <MarketSection key={sec.category} title={sec.category}>
              {sec.items.map((card) => {
                const isLocal = 'enabled' in card && typeof (card as Skill).enabled === 'boolean'
                const skill = isLocal ? (card as (typeof localCards)[number]) : null
                const hub = !isLocal ? (card as (typeof hubCards)[number]) : null
                const isPreset = skill ? !!SKILL_MARKET_META[skill.id] : false
                return (
                  <MarketCard
                    key={card.id}
                    item={{
                      id: card.id,
                      name: card.name,
                      description: card.description,
                      category: card.category,
                      badge: card.badge,
                      icon: card.icon,
                      installed: card.installed,
                    }}
                    installing={hub ? addingId === hub.id : false}
                    installLabel="安装"
                    onInstall={
                      hub
                        ? () => void addHermesSkill(hub.raw)
                        : undefined
                    }
                    onClick={skill ? () => void openDetail(skill, isPreset ? 'view' : 'edit') : undefined}
                    menu={
                      skill ? (
                        <div className="market-menu-wrap">
                          <button
                            type="button"
                            className="market-menu-btn"
                            onClick={() => setMenuId((id) => (id === skill.id ? null : skill.id))}
                          >
                            ···
                          </button>
                          {menuId === skill.id ? (
                            <div className="market-menu">
                              {isPreset ? (
                                <button type="button" onClick={() => void openDetail(skill, 'view')}>
                                  查看
                                </button>
                              ) : (
                                <>
                                  <button type="button" onClick={() => void openDetail(skill, 'edit')}>
                                    编辑
                                  </button>
                                  <button type="button" onClick={() => void toggleEnabled(skill)}>
                                    {skill.enabled ? '禁用' : '启用'}
                                  </button>
                                  <button type="button" onClick={() => void dryRun(skill)}>
                                    试运行
                                  </button>
                                  <button type="button" className="danger" onClick={() => void removeSkill(skill)}>
                                    删除
                                  </button>
                                </>
                              )}
                            </div>
                          ) : null}
                        </div>
                      ) : undefined
                    }
                  />
                )
              })}
            </MarketSection>
          ),
        )
      )}

      <p className="market-foot">公开预置与 Hub 仅可查看/安装；个人区可编辑与删除。对话中可用 /技能名 调用。</p>

      <Modal
        open={modalOpen}
        wide
        title={viewOnly ? '查看技能' : editId ? '编辑技能' : '新增技能'}
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
          {!editId && !viewOnly && (
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="ghost" onClick={() => pickMdFile('fill')}>
                从 MD 文件填充
              </button>
            </div>
          )}
          <label className="muted">技能 ID（斜杠名）</label>
          <input
            value={form.id}
            disabled={!!editId || viewOnly}
            onChange={(e) => setForm({ ...form, id: e.target.value })}
            placeholder="如 my-skill，对话中使用 /my-skill"
          />
          <label className="muted">名称</label>
          <input
            value={form.name}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="显示名称"
          />
          <label className="muted">描述</label>
          <input
            value={form.description}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="简短说明技能用途"
          />
          <label className="muted">触发词（逗号或换行分隔）</label>
          <input
            value={form.triggersText}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, triggersText: e.target.value })}
            placeholder="摘要, 总结, summarize"
          />
          <label className="muted">权限 / allowed-tools（逗号分隔）</label>
          <input
            value={form.permissionsText}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, permissionsText: e.target.value })}
            placeholder="fs_read, fs_list"
          />
          <label className="muted">版本</label>
          <input
            value={form.version}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, version: e.target.value })}
          />
          <label className="row muted">
            <input
              type="checkbox"
              checked={form.enabled}
              disabled={viewOnly}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            启用
          </label>
          <label className="muted">技能正文（Markdown）</label>
          <textarea
            rows={10}
            value={form.body}
            disabled={viewOnly}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            placeholder="# 技能指引&#10;&#10;1. 第一步…&#10;2. 第二步…"
          />
        </div>
      </Modal>
    </div>
  )
}
