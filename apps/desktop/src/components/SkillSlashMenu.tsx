import { useEffect, useRef } from 'react'
import type { SkillOption } from '../lib/skillSlashMenu'

type Props = {
  open: boolean
  items: SkillOption[]
  activeIndex: number
  onPick: (id: string) => void
  onHover: (index: number) => void
}

export default function SkillSlashMenu({ open, items, activeIndex, onPick, onHover }: Props) {
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [open, activeIndex, items.length])

  if (!open || items.length === 0) return null

  return (
    <div className="skill-slash-menu" role="listbox" ref={listRef}>
      <div className="skill-slash-head muted">技能 · ↑↓ 选择 · Enter 确认</div>
      {items.map((s, i) => (
        <button
          key={s.id}
          type="button"
          role="option"
          data-index={i}
          aria-selected={i === activeIndex}
          className={`skill-slash-item ${i === activeIndex ? 'active' : ''}`}
          onMouseEnter={() => onHover(i)}
          onMouseDown={(e) => {
            e.preventDefault()
            onPick(s.id)
          }}
        >
          <span className="skill-slash-id">/{s.id}</span>
          <span className="skill-slash-name">{s.name}</span>
          {s.description && <span className="skill-slash-desc muted">{s.description}</span>}
        </button>
      ))}
    </div>
  )
}
