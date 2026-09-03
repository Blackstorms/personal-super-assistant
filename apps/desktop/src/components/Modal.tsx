import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}

/**
 * 遮罩点击关闭：仅当 pointerdown 与 click 都发生在 overlay 本身时关闭。
 * 避免在弹框内长按拖选文字、鼠标在遮罩上松开时误关。
 */
export default function Modal({ open, title, onClose, children, footer, wide }: Props) {
  const closeOnOverlayRef = useRef(false)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="modal-overlay"
      onPointerDown={(e) => {
        closeOnOverlayRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return
        if (!closeOnOverlayRef.current) return
        closeOnOverlayRef.current = false
        onClose()
      }}
    >
      <div
        className={`modal-box ${wide ? 'modal-wide' : ''}`}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-head">
          <h3 id="modal-title">{title}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
