import { useRef, type ChangeEvent } from 'react'

type Props = {
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
  readOnly?: boolean
}

export default function JsonCodeEditor({ value, onChange, rows = 16, placeholder, readOnly }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const gutterRef = useRef<HTMLDivElement>(null)
  const lineCount = Math.max(value.split('\n').length, 1)

  const syncScroll = () => {
    const ta = textareaRef.current
    const gutter = gutterRef.current
    if (ta && gutter) gutter.scrollTop = ta.scrollTop
  }

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value)
  }

  return (
    <div className="json-code-editor" style={{ ['--json-code-rows' as string]: String(rows) }}>
      <div ref={gutterRef} className="json-code-gutter" aria-hidden="true">
        {Array.from({ length: lineCount }, (_, i) => (
          <span key={i}>{i + 1}</span>
        ))}
      </div>
      <textarea
        ref={textareaRef}
        className="json-code-input"
        value={value}
        onChange={handleChange}
        onScroll={syncScroll}
        spellCheck={false}
        readOnly={readOnly}
        placeholder={placeholder}
      />
    </div>
  )
}
