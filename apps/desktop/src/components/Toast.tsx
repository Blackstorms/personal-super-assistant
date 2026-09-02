type Props = {
  message: string
  type?: 'info' | 'success' | 'error'
  onClose?: () => void
}

export default function Toast({ message, type = 'info', onClose }: Props) {
  if (!message) return null
  return (
    <div className={`toast toast-${type}`} role="status">
      <span>{message}</span>
      {onClose && (
        <button type="button" className="toast-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
      )}
    </div>
  )
}
