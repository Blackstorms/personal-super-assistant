/**
 * 输入框左侧 + 菜单：文件 / 专家 / 技能 / 连接器 / 资料库。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'

export type AttachedFile = {
  id: string
  name: string
  localPath?: string
  textContent?: string
  base64?: string
  attachmentId?: string
}

type Expert = { id: string; name: string }
type Skill = { id: string; name: string }
type Mcp = { id: string; name: string }
type Knowledge = { id: string; name?: string | null; path?: string }

type Props = {
  experts: Expert[]
  skills: Skill[]
  mcps: Mcp[]
  knowledge: Knowledge[]
  expertId: string
  skillIds: string[]
  mcpIds: string[]
  knowledgeIds: string[]
  files: AttachedFile[]
  onExpertChange: (id: string) => void
  onSkillToggle: (id: string) => void
  onMcpToggle: (id: string) => void
  onKnowledgeToggle: (id: string) => void
  onFilesChange: (files: AttachedFile[]) => void
}

type Panel = 'root' | 'expert' | 'skill' | 'mcp' | 'knowledge'

const IconFile = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M8 4h8l4 4v12H8zM14 4v4h4" />
  </svg>
)
const IconExpert = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M12 12a4 4 0 100-8 4 4 0 000 8zM4 20a8 8 0 0116 0" />
  </svg>
)
const IconSkill = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M14 6l-1-4-1 4-4 1 4 1 1 4 1-4 4-1-4-1zM6 16l-1-2-1 2-2 1 2 1 1 2 1-2 2-1-2-1z" />
  </svg>
)
const IconMcp = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M8 12h8M7 8a3 3 0 010-6h2v6H7zM17 22a3 3 0 000-6h-2v6h2z" />
  </svg>
)
const IconKnowledge = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 5h7a3 3 0 013 3v11H7a3 3 0 01-3-3V5zM20 5h-7a3 3 0 00-3 3v11h7a3 3 0 003-3V5z" />
  </svg>
)

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

function readFileAsText(file: File): Promise<string | undefined> {
  const textLike =
    file.type.startsWith('text/') ||
    /\.(txt|md|json|csv|xml|html|js|ts|tsx|jsx|py|yaml|yml|log)$/i.test(file.name)
  if (!textLike) return Promise.resolve(undefined)
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || '').slice(0, 120_000))
    reader.onerror = () => resolve(undefined)
    reader.readAsText(file)
  })
}

export default function ComposerAttachMenu({
  experts,
  skills,
  mcps,
  knowledge,
  expertId,
  skillIds,
  mcpIds,
  knowledgeIds,
  files,
  onExpertChange,
  onSkillToggle,
  onMcpToggle,
  onKnowledgeToggle,
  onFilesChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const [panel, setPanel] = useState<Panel>('root')
  const wrapRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) {
        setOpen(false)
        setPanel('root')
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const pickFiles = async (list: FileList | null) => {
    if (!list?.length) return
    const next = [...files]
    for (const f of Array.from(list)) {
      const textLike =
        f.type.startsWith('text/') ||
        /\.(txt|md|json|csv|xml|html|js|ts|tsx|jsx|py|yaml|yml|log)$/i.test(f.name)
      if (textLike) {
        const text = await readFileAsText(f)
        next.push({
          id: `${f.name}-${f.size}-${Date.now()}`,
          name: f.name,
          textContent: text || '',
        })
      } else {
        try {
          const base64 = await readFileAsBase64(f)
          next.push({
            id: `${f.name}-${f.size}-${Date.now()}`,
            name: f.name,
            base64,
          })
        } catch {
          next.push({
            id: `${f.name}-${f.size}-${Date.now()}`,
            name: f.name,
            textContent: `[二进制文件 ${f.name}]`,
          })
        }
      }
    }
    onFilesChange(next)
    setOpen(false)
    setPanel('root')
  }

  const pickFromDialog = async () => {
    if (window.api?.selectFiles) {
      const paths = await window.api.selectFiles()
      if (paths?.length) {
        const next = [
          ...files,
          ...paths.map((p) => ({
            id: p,
            name: p.split(/[/\\]/).pop() || p,
            localPath: p,
          })),
        ]
        onFilesChange(next)
      }
      setOpen(false)
      setPanel('root')
      return
    }
    fileRef.current?.click()
  }

  const rootItems: { key: Panel | 'file'; label: string; icon: ReactNode; action?: () => void }[] = [
    {
      key: 'file',
      label: '添加文件',
      icon: <IconFile />,
      action: () => void pickFromDialog(),
    },
    { key: 'expert', label: '专家', icon: <IconExpert /> },
    { key: 'skill', label: '技能', icon: <IconSkill /> },
    { key: 'mcp', label: '连接器', icon: <IconMcp /> },
    { key: 'knowledge', label: '资料库', icon: <IconKnowledge /> },
  ]

  const panelTitle: Record<Exclude<Panel, 'root'>, string> = {
    expert: '选择专家',
    skill: '选择技能',
    mcp: '选择连接器',
    knowledge: '选择资料库',
  }

  return (
    <div className="composer-attach-wrap" ref={wrapRef}>
      <input
        ref={fileRef}
        type="file"
        multiple
        hidden
        onChange={(e) => void pickFiles(e.target.files)}
      />
      {open && (
        <div className="composer-attach-menu">
          {panel === 'root' ? (
            rootItems.map((item) => (
              <button
                key={item.key}
                type="button"
                className="composer-attach-item"
                onClick={() => {
                  if (item.action) {
                    item.action()
                    return
                  }
                  setPanel(item.key as Panel)
                }}
              >
                <span className="composer-attach-item-left">
                  {item.icon}
                  {item.label}
                </span>
                {!item.action && <span className="muted">›</span>}
              </button>
            ))
          ) : (
            <>
              <button
                type="button"
                className="composer-attach-back"
                onClick={() => setPanel('root')}
              >
                ‹ 返回
              </button>
              <div className="composer-attach-subhead">{panelTitle[panel]}</div>
              <div className="composer-attach-list">
                {panel === 'expert' && (
                  <>
                    <button
                      type="button"
                      className={`composer-attach-pick ${!expertId ? 'active' : ''}`}
                      onClick={() => {
                        onExpertChange('')
                        setOpen(false)
                        setPanel('root')
                      }}
                    >
                      不选用专家
                    </button>
                    {experts.map((e) => (
                      <button
                        key={e.id}
                        type="button"
                        className={`composer-attach-pick ${expertId === e.id ? 'active' : ''}`}
                        onClick={() => {
                          onExpertChange(e.id)
                          setOpen(false)
                          setPanel('root')
                        }}
                      >
                        {e.name}
                      </button>
                    ))}
                    {experts.length === 0 && <div className="muted composer-attach-empty">暂无专家</div>}
                  </>
                )}
                {panel === 'skill' &&
                  (skills.length ? (
                    skills.map((s) => (
                      <label key={s.id} className="composer-attach-check">
                        <input
                          type="checkbox"
                          checked={skillIds.includes(s.id)}
                          onChange={() => onSkillToggle(s.id)}
                        />
                        <span>{s.name}</span>
                      </label>
                    ))
                  ) : (
                    <div className="muted composer-attach-empty">暂无技能</div>
                  ))}
                {panel === 'mcp' &&
                  (mcps.length ? (
                    mcps.map((m) => (
                      <label key={m.id} className="composer-attach-check">
                        <input
                          type="checkbox"
                          checked={mcpIds.includes(m.id)}
                          onChange={() => onMcpToggle(m.id)}
                        />
                        <span>{m.name}</span>
                      </label>
                    ))
                  ) : (
                    <div className="muted composer-attach-empty">暂无连接器</div>
                  ))}
                {panel === 'knowledge' &&
                  (knowledge.length ? (
                    knowledge.map((k) => (
                      <label key={k.id} className="composer-attach-check">
                        <input
                          type="checkbox"
                          checked={knowledgeIds.includes(k.id)}
                          onChange={() => onKnowledgeToggle(k.id)}
                        />
                        <span>{k.name || k.path || k.id}</span>
                      </label>
                    ))
                  ) : (
                    <div className="muted composer-attach-empty">暂无资料库</div>
                  ))}
              </div>
              {panel !== 'expert' && (
                <button
                  type="button"
                  className="composer-attach-done primary"
                  onClick={() => {
                    setOpen(false)
                    setPanel('root')
                  }}
                >
                  完成
                </button>
              )}
            </>
          )}
        </div>
      )}
      <button
        type="button"
        className="icon-btn composer-plus"
        title="添加文件 / 专家 / 技能 / 连接器 / 资料库"
        onClick={() => {
          setOpen((v) => !v)
          setPanel('root')
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
    </div>
  )
}

export function ComposerChips({
  experts,
  skills,
  mcps,
  knowledge,
  expertId,
  skillIds,
  mcpIds,
  knowledgeIds,
  files,
  onExpertChange,
  onSkillToggle,
  onMcpToggle,
  onKnowledgeToggle,
  onFilesChange,
}: Props) {
  const expert = experts.find((e) => e.id === expertId)
  const chips: { key: string; label: string; onRemove: () => void }[] = []

  if (expert) chips.push({ key: `ex-${expert.id}`, label: expert.name, onRemove: () => onExpertChange('') })
  for (const id of skillIds) {
    const s = skills.find((x) => x.id === id)
    if (s) chips.push({ key: `sk-${id}`, label: s.name, onRemove: () => onSkillToggle(id) })
  }
  for (const id of mcpIds) {
    const m = mcps.find((x) => x.id === id)
    if (m) chips.push({ key: `mcp-${id}`, label: m.name, onRemove: () => onMcpToggle(id) })
  }
  for (const id of knowledgeIds) {
    const k = knowledge.find((x) => x.id === id)
    if (k) chips.push({ key: `kn-${id}`, label: k.name || k.path || id, onRemove: () => onKnowledgeToggle(id) })
  }
  for (const f of files) {
    chips.push({
      key: f.id,
      label: f.name,
      onRemove: () => onFilesChange(files.filter((x) => x.id !== f.id)),
    })
  }

  if (!chips.length) return null

  return (
    <div className="composer-chips">
      {chips.map((c) => (
        <span key={c.key} className="composer-chip">
          {c.label}
          <button type="button" className="composer-chip-x" onClick={c.onRemove} aria-label="移除">
            ×
          </button>
        </span>
      ))}
    </div>
  )
}
