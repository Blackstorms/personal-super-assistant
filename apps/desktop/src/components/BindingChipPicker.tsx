/**
 * 绑定选择器：分区卡片展示已选项；可搜索添加（只读时仅展示）。
 * 下拉通过 portal + fixed 定位，避免被弹窗 overflow 裁切。
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export type BindingOption = {
  id: string
  name: string
  description?: string | null
}

export type BindingKind = 'skill' | 'mcp' | 'knowledge' | 'expert'

type Props = {
  label: string
  options: BindingOption[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
  /** 单选：点选即替换，最多一项 */
  single?: boolean
  /** 只读：仅展示已选项，不可增删 */
  readOnly?: boolean
  /** 视觉类型，用于图标与色点 */
  kind?: BindingKind
  searchPlaceholder?: string
}

type MenuPos = { top: number; left: number; width: number; maxHeight: number; place: 'below' | 'above' }

function KindGlyph({ kind }: { kind?: BindingKind }) {
  if (kind === 'mcp') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M8 8h8v8H8zM4 12h4M16 12h4M12 4v4M12 16v4" strokeLinecap="round" />
      </svg>
    )
  }
  if (kind === 'knowledge') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 5h7a3 3 0 013 3v11H7a3 3 0 00-3 3V5zM13 5h7v14a3 3 0 01-3 3h-4" strokeLinejoin="round" />
      </svg>
    )
  }
  if (kind === 'expert') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 19c1.5-3 4-4.5 7-4.5S17.5 16 19 19" strokeLinecap="round" />
      </svg>
    )
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3l2.2 4.5L19 9l-3.5 3.4L16.4 18 12 15.8 7.6 18l.9-5.6L5 9l4.8-1.5L12 3z" strokeLinejoin="round" />
    </svg>
  )
}

export default function BindingChipPicker({
  label,
  options,
  selectedIds,
  onChange,
  single = false,
  readOnly = false,
  kind,
  searchPlaceholder = '搜索并添加…',
}: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [menuPos, setMenuPos] = useState<MenuPos | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const byId = useMemo(() => {
    const m = new Map<string, BindingOption>()
    for (const o of options) m.set(o.id, o)
    return m
  }, [options])

  const selected = useMemo(
    () =>
      selectedIds
        .map((id) => byId.get(id) || { id, name: id })
        .filter(Boolean) as BindingOption[],
    [selectedIds, byId],
  )

  const q = query.trim().toLowerCase()
  const suggestions = useMemo(() => {
    const pool = options
    if (!q) return pool.slice(0, 40)
    return pool
      .filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          (o.description || '').toLowerCase().includes(q) ||
          o.id.toLowerCase().includes(q),
      )
      .slice(0, 40)
  }, [options, q])

  const updateMenuPos = () => {
    const el = inputRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const gap = 4
    const spaceBelow = window.innerHeight - rect.bottom - 12
    const spaceAbove = rect.top - 12
    const preferBelow = spaceBelow >= 160 || spaceBelow >= spaceAbove
    const available = preferBelow ? spaceBelow : spaceAbove
    const maxHeight = Math.min(240, Math.max(96, available))
    if (preferBelow) {
      setMenuPos({
        left: Math.max(8, rect.left),
        width: Math.max(160, rect.width),
        maxHeight,
        place: 'below',
        top: rect.bottom + gap,
      })
    } else {
      setMenuPos({
        left: Math.max(8, rect.left),
        width: Math.max(160, rect.width),
        maxHeight,
        place: 'above',
        top: rect.top - gap,
      })
    }
  }

  useLayoutEffect(() => {
    if (!open) {
      setMenuPos(null)
      return
    }
    updateMenuPos()
    const onReposition = () => updateMenuPos()
    window.addEventListener('resize', onReposition)
    window.addEventListener('scroll', onReposition, true)
    return () => {
      window.removeEventListener('resize', onReposition)
      window.removeEventListener('scroll', onReposition, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node
      if (rootRef.current?.contains(t) || menuRef.current?.contains(t)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const toggle = (id: string) => {
    if (single) {
      if (selectedIds[0] === id) {
        onChange([])
      } else {
        onChange([id])
      }
      setQuery('')
      setOpen(false)
      return
    }
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id))
    } else {
      onChange([...selectedIds, id])
    }
    setQuery('')
    setOpen(true)
    requestAnimationFrame(updateMenuPos)
  }

  const remove = (id: string) => {
    onChange(selectedIds.filter((x) => x !== id))
  }

  const menu =
    open && menuPos
      ? createPortal(
          <div
            ref={menuRef}
            className="binding-suggest binding-suggest-portal"
            role="listbox"
            aria-label={`${label}可选列表`}
            style={
              menuPos.place === 'below'
                ? {
                    left: menuPos.left,
                    width: menuPos.width,
                    maxHeight: menuPos.maxHeight,
                    top: menuPos.top,
                    bottom: 'auto',
                    zIndex: 5000,
                  }
                : {
                    left: menuPos.left,
                    width: menuPos.width,
                    maxHeight: menuPos.maxHeight,
                    top: 'auto',
                    bottom: Math.max(8, window.innerHeight - menuPos.top),
                    zIndex: 5000,
                  }
            }
          >
            {suggestions.length === 0 ? (
              <div className="binding-suggest-empty muted">
                {q ? '无匹配项，换个关键词试试' : '暂无可选项'}
              </div>
            ) : (
              suggestions.map((o) => {
                const picked = selectedIds.includes(o.id)
                return (
                  <button
                    key={o.id}
                    type="button"
                    role="option"
                    aria-selected={picked}
                    className={`binding-suggest-item${picked ? ' is-picked' : ''}`}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => toggle(o.id)}
                  >
                    <span className="binding-suggest-row">
                      <span className="binding-suggest-name">{o.name}</span>
                      {picked ? (
                        <span className="binding-suggest-check" aria-hidden>
                          ✓
                        </span>
                      ) : null}
                    </span>
                    {o.description ? <span className="muted">{o.description}</span> : null}
                  </button>
                )
              })
            )}
          </div>,
          document.body,
        )
      : null

  return (
    <div
      className={`binding-picker${readOnly ? ' readonly' : ''}${kind ? ` kind-${kind}` : ''}${open ? ' is-open' : ''}`}
      ref={rootRef}
    >
      <div className="binding-picker-head">
        <span className="binding-picker-title">
          <span className="binding-picker-glyph" aria-hidden>
            <KindGlyph kind={kind} />
          </span>
          {label}
        </span>
        <span className="binding-picker-count">{selected.length}</span>
      </div>

      <div className="binding-picker-body">
        {selected.length > 0 ? (
          <div className="binding-chip-grid">
            {selected.map((item) => (
              <span key={item.id} className="binding-chip" title={item.description || item.name}>
                <span className="binding-chip-dot" aria-hidden />
                <span className="binding-chip-name">{item.name}</span>
                {!readOnly ? (
                  <button
                    type="button"
                    className="binding-chip-remove"
                    aria-label={`移除 ${item.name}`}
                    onClick={() => remove(item.id)}
                  >
                    ×
                  </button>
                ) : null}
              </span>
            ))}
          </div>
        ) : (
          <div className="binding-picker-empty">
            <span>{readOnly ? '暂未绑定' : single ? '尚未选择' : '暂无绑定，可在下方搜索添加'}</span>
          </div>
        )}

        {!readOnly ? (
          <div className={`binding-picker-search ${open ? 'open' : ''}`}>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setOpen(true)
              }}
              onFocus={() => setOpen(true)}
              onClick={() => setOpen(true)}
              placeholder={searchPlaceholder}
              aria-label={`搜索${label}`}
              aria-expanded={open}
              aria-haspopup="listbox"
              autoComplete="off"
            />
            <button
              type="button"
              className="binding-picker-caret"
              aria-label={open ? '收起列表' : '展开列表'}
              tabIndex={-1}
              onMouseDown={(e) => {
                e.preventDefault()
                setOpen((v) => !v)
              }}
            >
              {open ? '▴' : '▾'}
            </button>
          </div>
        ) : null}
      </div>
      {menu}
    </div>
  )
}
