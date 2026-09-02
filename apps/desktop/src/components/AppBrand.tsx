/**
 * 应用品牌条：侧栏 / 登录 / 启动页共用同一图标与「超级助理」标题。
 */
type Props = {
  /** sidebar：紧凑侧栏；hero：登录/启动页稍大 */
  size?: 'sidebar' | 'hero'
  /** 是否显示英文副标题（登录/启动页） */
  showSub?: boolean
  /** 后端状态点；不传则不显示 */
  healthy?: boolean | null
  className?: string
}

export function BrandMarkIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.92" />
      <circle cx="9" cy="10.5" r="1.2" fill="#fff" />
      <circle cx="15" cy="10.5" r="1.2" fill="#fff" />
      <path
        d="M9.5 14.2c.8.6 1.7.9 2.5.9s1.7-.3 2.5-.9"
        stroke="#fff"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  )
}

export default function AppBrand({
  size = 'sidebar',
  showSub = false,
  healthy = null,
  className = '',
}: Props) {
  const iconSize = size === 'hero' ? 20 : 16
  const statusTitle =
    healthy === null ? undefined : healthy ? '后端正常' : '后端异常'

  return (
    <div className={`brand app-brand app-brand--${size}${className ? ` ${className}` : ''}`}>
      <div className="brand-mark" aria-hidden>
        <BrandMarkIcon size={iconSize} />
      </div>
      <div className="brand-copy">
        <h1>超级助理</h1>
        {showSub ? <div className="brand-sub">Personal Super Assistant</div> : null}
      </div>
      {healthy !== null ? (
        <span className={`dot ${healthy ? 'ok' : 'bad'}`} title={statusTitle} />
      ) : null}
    </div>
  )
}
