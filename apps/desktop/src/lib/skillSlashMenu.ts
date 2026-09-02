import { useMemo, useRef, useState, type KeyboardEvent } from 'react'

export type SkillOption = {
  id: string
  name: string
  description: string
  triggers: string[]
  enabled: boolean
}

type SlashState = {
  query: string
  start: number
  end: number
} | null

export function detectSlashQuery(text: string, cursor: number): SlashState {
  const before = text.slice(0, cursor)
  const m = before.match(/(?:^|\s)\/([a-zA-Z0-9_-]*)$/)
  if (!m) return null
  const query = m[1]
  const start = cursor - query.length - 1
  return { query, start, end: cursor }
}

export function filterSkills(skills: SkillOption[], query: string): SkillOption[] {
  const q = query.toLowerCase()
  const enabled = skills.filter((s) => s.enabled)
  if (!q) return enabled
  return enabled.filter((s) => {
    if (s.id.toLowerCase().includes(q)) return true
    if (s.name.toLowerCase().includes(q)) return true
    if (s.description.toLowerCase().includes(q)) return true
    return s.triggers.some((t) => t.toLowerCase().includes(q))
  })
}

export function useSkillSlashMenu(
  input: string,
  setInput: (v: string) => void,
  skills: SkillOption[],
  enabled: boolean,
) {
  const [slash, setSlash] = useState<SlashState>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const slashRef = useRef<SlashState>(null)

  const filtered = useMemo(
    () => (slash && enabled ? filterSkills(skills, slash.query) : []),
    [skills, slash, enabled],
  )

  const open = Boolean(slash && enabled && filtered.length > 0)

  const sync = (text: string, cursor: number) => {
    if (!enabled) {
      slashRef.current = null
      setSlash(null)
      return
    }
    const next = detectSlashQuery(text, cursor)
    const prev = slashRef.current
    const sameContext =
      Boolean(prev && next && prev.start === next.start && prev.query === next.query)
    slashRef.current = next
    setSlash(next)
    if (!sameContext) setActiveIndex(0)
  }

  const close = () => {
    slashRef.current = null
    setSlash(null)
  }

  const pick = (skillId: string, textarea: HTMLTextAreaElement | null) => {
    if (!slash) return
    const next = `${input.slice(0, slash.start)}/${skillId} ${input.slice(slash.end)}`
    setInput(next)
    close()
    if (textarea) {
      const pos = slash.start + skillId.length + 2
      window.requestAnimationFrame(() => {
        textarea.focus()
        textarea.setSelectionRange(pos, pos)
      })
    }
  }

  const handleKeyDown = (
    e: KeyboardEvent<HTMLTextAreaElement>,
    onSend: () => void,
  ): boolean => {
    if (!open) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        onSend()
        return true
      }
      return false
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => (i + 1) % filtered.length)
      return true
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => (i - 1 + filtered.length) % filtered.length)
      return true
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      close()
      return true
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      const skill = filtered[activeIndex]
      if (skill) pick(skill.id, e.currentTarget)
      return true
    }
    return false
  }

  return {
    open,
    filtered,
    activeIndex,
    setActiveIndex,
    sync,
    close,
    pick,
    handleKeyDown,
  }
}
