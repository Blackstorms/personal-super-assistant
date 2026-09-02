import { useEffect, useState } from 'react'

export type BuddyMood = 'idle' | 'typing' | 'busy' | 'ready'

type Props = {
  mood?: BuddyMood
  className?: string
}

/**
 * 主页探头虚拟形象（参考 WorkBuddy 输入框右上角角色）。
 * 纯 SVG + CSS 动画，随输入/流式状态切换情绪。
 */
export default function BuddyMascot({ mood = 'idle', className = '' }: Props) {
  const [hovered, setHovered] = useState(false)
  const [wink, setWink] = useState(false)

  useEffect(() => {
    if (mood === 'busy') return
    const id = window.setInterval(() => {
      setWink(true)
      window.setTimeout(() => setWink(false), 160)
    }, 4200 + Math.random() * 2800)
    return () => window.clearInterval(id)
  }, [mood])

  const label =
    mood === 'busy' ? '思考中' : mood === 'typing' ? '听着呢' : mood === 'ready' ? '可以发啦' : '在这儿'

  return (
    <button
      type="button"
      className={`buddy-mascot mood-${mood}${hovered ? ' is-hover' : ''}${wink ? ' is-wink' : ''} ${className}`.trim()}
      aria-label={`助理虚拟形象：${label}`}
      title={label}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
    >
      <svg className="buddy-svg" viewBox="0 0 120 110" width="88" height="80" aria-hidden>
        <defs>
          <linearGradient id="buddyFace" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="var(--buddy-face-from)" />
            <stop offset="100%" stopColor="var(--buddy-face-to)" />
          </linearGradient>
          <linearGradient id="buddyVisor" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--brand-from)" />
            <stop offset="100%" stopColor="var(--brand-to)" />
          </linearGradient>
          <filter id="buddyGlow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="1.4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* 耳机弓 */}
        <path
          className="buddy-band"
          d="M28 52c4-22 22-36 32-36s28 14 32 36"
          fill="none"
          stroke="#3a414b"
          strokeWidth="7"
          strokeLinecap="round"
        />

        {/* 左耳 */}
        <g className="buddy-ear buddy-ear-l">
          <path d="M34 48 L22 18 L48 38 Z" fill="url(#buddyFace)" stroke="var(--buddy-stroke)" strokeWidth="1.5" />
          <path d="M34 42 L28 26 L42 36 Z" fill="var(--buddy-ear-fill)" opacity="0.85" />
        </g>
        {/* 右耳 */}
        <g className="buddy-ear buddy-ear-r">
          <path d="M86 48 L98 18 L72 38 Z" fill="url(#buddyFace)" stroke="var(--buddy-stroke)" strokeWidth="1.5" />
          <path d="M86 42 L92 26 L78 36 Z" fill="var(--buddy-ear-fill)" opacity="0.85" />
        </g>

        {/* 头 */}
        <ellipse cx="60" cy="62" rx="38" ry="34" fill="url(#buddyFace)" stroke="var(--buddy-stroke)" strokeWidth="1.5" />
        <ellipse cx="60" cy="68" rx="30" ry="22" fill="#fafbfc" opacity="0.55" />

        {/* 耳机罩 */}
        <ellipse className="buddy-cup buddy-cup-l" cx="24" cy="58" rx="11" ry="16" fill="#3a414b" />
        <ellipse className="buddy-cup buddy-cup-r" cx="96" cy="58" rx="11" ry="16" fill="#3a414b" />
        <ellipse cx="24" cy="58" rx="5" ry="8" fill="#5a6572" opacity="0.55" />
        <ellipse cx="96" cy="58" rx="5" ry="8" fill="#5a6572" opacity="0.55" />

        {/* 面罩 */}
        <rect x="34" y="48" width="52" height="26" rx="13" fill="url(#buddyVisor)" />

        {/* 星形眼睛 */}
        <g className="buddy-eyes" filter="url(#buddyGlow)">
          <path className="buddy-eye buddy-eye-l" d={starPath(48, 61, 7)} fill="#3dd6c6" />
          <path className="buddy-eye buddy-eye-r" d={starPath(72, 61, 7)} fill="#3dd6c6" />
        </g>

        {/* 腮红 */}
        <ellipse cx="40" cy="78" rx="5" ry="2.5" fill="#ffb4b8" opacity="0.35" />
        <ellipse cx="80" cy="78" rx="5" ry="2.5" fill="#ffb4b8" opacity="0.35" />
      </svg>
    </button>
  )
}

function starPath(cx: number, cy: number, r: number): string {
  const spikes = 4
  const outer = r
  const inner = r * 0.38
  const pts: string[] = []
  for (let i = 0; i < spikes * 2; i++) {
    const ang = (Math.PI / spikes) * i - Math.PI / 2
    const rad = i % 2 === 0 ? outer : inner
    pts.push(`${cx + Math.cos(ang) * rad},${cy + Math.sin(ang) * rad}`)
  }
  return `M${pts.join('L')}Z`
}

export function resolveBuddyMood(input: string, streaming: boolean): BuddyMood {
  if (streaming) return 'busy'
  const t = input.trim()
  if (!t) return 'idle'
  if (t.length >= 2) return 'ready'
  return 'typing'
}
