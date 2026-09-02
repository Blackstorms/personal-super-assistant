/**
 * 上下文用量：composer 内紧凑触发器 + 分类明细弹层。
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  contextUsageBarSegments,
  formatContextUsageUsed,
  formatPercent,
  formatTokenCount,
  type ContextUsage,
} from '../lib/contextUsage'

type Props = { usage: ContextUsage }

type PopPos = { top: number; left: number; place: 'above' | 'below' }

function SegmentBar({ usage }: { usage: ContextUsage }) {
  const segs = contextUsageBarSegments(usage)
  return (
    <div className="ctx-usage-bar ctx-usage-bar-lg" aria-hidden>
      {segs.map((s) =>
        s.percent > 0 ? (
          <span
            key={s.key}
            className="ctx-usage-seg"
            style={{ width: `${Math.max(s.percent, 0.4)}%`, background: s.color }}
          />
        ) : null,
      )}
    </div>
  )
}

function UsageRing({ percent }: { percent: number }) {
  const size = 18
  const stroke = 2.2
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const pct = Math.min(100, Math.max(0, Number.isFinite(percent) ? percent : 0))
  const dash = (pct / 100) * c
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="ctx-usage-ring" aria-hidden>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={stroke}
        className="ctx-usage-ring-track"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${dash} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="ctx-usage-ring-fill"
      />
    </svg>
  )
}

export default function ContextUsageMeter({ usage }: Props) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<PopPos | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const compressed = Boolean(usage.compressed || usage.has_summary)
  const segs = contextUsageBarSegments(usage)

  const updatePos = () => {
    const el = triggerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const width = 300
    const gap = 8
    const left = Math.min(
      Math.max(12, rect.right - width),
      window.innerWidth - width - 12,
    )
    const spaceAbove = rect.top - 12
    const spaceBelow = window.innerHeight - rect.bottom - 12
    const preferAbove = spaceAbove >= 220 || spaceAbove >= spaceBelow
    if (preferAbove) {
      setPos({ left, top: rect.top - gap, place: 'above' })
    } else {
      setPos({ left, top: rect.bottom + gap, place: 'below' })
    }
  }

  useLayoutEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    updatePos()
    const onReposition = () => updatePos()
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
      if (triggerRef.current?.contains(t) || popRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const popover =
    open && pos
      ? createPortal(
          <div
            ref={popRef}
            className="ctx-usage-pop"
            role="dialog"
            aria-labelledby="ctx-usage-title"
            style={
              pos.place === 'above'
                ? { left: pos.left, bottom: Math.max(8, window.innerHeight - pos.top), top: 'auto' }
                : { left: pos.left, top: pos.top, bottom: 'auto' }
            }
          >
            <div className="ctx-usage-pop-head">
              <div className="ctx-usage-pop-title-row">
                <h3 id="ctx-usage-title">上下文用量</h3>
                {compressed ? <span className="ctx-usage-pop-tag">已压缩</span> : null}
              </div>
              <button
                type="button"
                className="ctx-usage-pop-close"
                onClick={() => setOpen(false)}
                aria-label="关闭"
              >
                ×
              </button>
            </div>
            <div className="ctx-usage-pop-summary">
              <span className="ctx-usage-pop-pct">{formatPercent(usage.percent)}</span>
              <span className="ctx-usage-pop-used">{formatContextUsageUsed(usage)}</span>
            </div>
            <SegmentBar usage={usage} />
            <ul className="ctx-usage-legend">
              {segs.map((s) => (
                <li key={s.key}>
                  <span className="ctx-usage-legend-left">
                    <i style={{ background: s.color }} />
                    {s.label}
                  </span>
                  <span className="ctx-usage-legend-val">~{formatTokenCount(s.tokens)}</span>
                </li>
              ))}
            </ul>
          </div>,
          document.body,
        )
      : null

  return (
    <div
      className={`composer-context-usage${usage.near_limit ? ' is-warn' : ''}${
        compressed ? ' is-compressed' : ''
      }`}
    >
      <button
        ref={triggerRef}
        type="button"
        className={`ctx-usage-trigger${open ? ' is-open' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`上下文用量 ${formatPercent(usage.percent)}，点击查看明细`}
        title={`上下文用量 ${formatPercent(usage.percent)}`}
        onClick={() => setOpen((v) => !v)}
      >
        <UsageRing percent={usage.percent} />
      </button>
      {popover}
    </div>
  )
}
