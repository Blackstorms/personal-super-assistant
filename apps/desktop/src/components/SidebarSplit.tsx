/**
 * 侧栏下半区：上方菜单 + 可拖动分割线 + 空间·任务列表。
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'psa-sidebar-workspace-height'
const DEFAULT_HEIGHT = 240
const MIN_WORKSPACE = 100
const MIN_NAV = 120

type Props = {
  nav: ReactNode
  workspace: ReactNode
}

function readSavedHeight(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_HEIGHT
    const n = Number(raw)
    return Number.isFinite(n) && n >= MIN_WORKSPACE ? n : DEFAULT_HEIGHT
  } catch {
    return DEFAULT_HEIGHT
  }
}

export default function SidebarSplit({ nav, workspace }: Props) {
  const splitRef = useRef<HTMLDivElement>(null)
  const heightRef = useRef(readSavedHeight())
  const [workspaceHeight, setWorkspaceHeight] = useState(heightRef.current)
  const [dragging, setDragging] = useState(false)

  const clampHeight = useCallback((next: number, containerHeight: number) => {
    const max = Math.max(MIN_WORKSPACE, containerHeight - MIN_NAV)
    return Math.min(Math.max(MIN_WORKSPACE, next), max)
  }, [])

  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      const container = splitRef.current
      if (!container) return

      const startY = e.clientY
      const startHeight = heightRef.current
      const containerHeight = container.getBoundingClientRect().height

      setDragging(true)
      document.body.classList.add('sidebar-resizing')

      const onMove = (ev: MouseEvent) => {
        const delta = startY - ev.clientY
        const next = clampHeight(startHeight + delta, containerHeight)
        heightRef.current = next
        setWorkspaceHeight(next)
      }

      const onUp = () => {
        setDragging(false)
        document.body.classList.remove('sidebar-resizing')
        try {
          localStorage.setItem(STORAGE_KEY, String(heightRef.current))
        } catch {
          /* 忽略 */
        }
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [clampHeight],
  )

  useEffect(() => {
    const container = splitRef.current
    if (!container || typeof ResizeObserver === 'undefined') return

    const ro = new ResizeObserver(() => {
      const h = container.getBoundingClientRect().height
      const clamped = clampHeight(heightRef.current, h)
      if (clamped !== heightRef.current) {
        heightRef.current = clamped
        setWorkspaceHeight(clamped)
      }
    })
    ro.observe(container)
    return () => ro.disconnect()
  }, [clampHeight])

  return (
    <div ref={splitRef} className="sidebar-split">
      <div className="sidebar-nav">{nav}</div>
      <div
        className={`sidebar-resize-handle ${dragging ? 'dragging' : ''}`}
        role="separator"
        aria-orientation="horizontal"
        aria-label="调整工作空间高度"
        title="拖动调整工作空间区域高度"
        onMouseDown={onResizeStart}
      />
      <div className="sidebar-workspace-wrap" style={{ height: workspaceHeight }}>
        {workspace}
      </div>
    </div>
  )
}
