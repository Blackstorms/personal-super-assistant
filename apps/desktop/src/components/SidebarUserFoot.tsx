import ThemeToggle from './ThemeToggle'

type Props = {
  username: string
  onLogout: () => void
}

function avatarInitial(name: string) {
  return (name.trim()[0] || '?').toUpperCase()
}

export default function SidebarUserFoot({ username, onLogout }: Props) {
  const initial = avatarInitial(username)

  return (
    <div className="sidebar-foot">
      <div className="sidebar-foot-user">
        <div className="sidebar-foot-avatar" aria-hidden="true">
          {initial}
        </div>
        <div className="sidebar-foot-meta">
          <div className="sidebar-foot-name" title={username}>
            {username}
          </div>
          <div className="sidebar-foot-hint">已登录</div>
        </div>
      </div>
      <ThemeToggle />
      <button
        type="button"
        className="sidebar-foot-logout"
        onClick={onLogout}
        title="退出登录"
        aria-label="退出登录"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
          <path d="M16 17l5-5-5-5" />
          <path d="M21 12H9" />
        </svg>
      </button>
    </div>
  )
}
