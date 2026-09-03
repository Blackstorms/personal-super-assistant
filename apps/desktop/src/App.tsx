/**
 * 应用壳：新建任务 / 项目 / 插件市场 / 资料库 / 自动化 / 审计 / 任务清单 / 设置 + 侧栏空间·任务。
 */
import { useEffect, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAppStore } from './stores/app'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import KnowledgePage from './pages/KnowledgePage'
import AuditPage from './pages/AuditPage'
import ChecklistPage from './pages/ChecklistPage'
import ChecklistDetailPage from './pages/ChecklistDetailPage'
import ScheduledTasksPage from './pages/ScheduledTasksPage'
import ScheduledTaskEditorPage from './pages/ScheduledTaskEditorPage'
import ProjectsPage from './pages/ProjectsPage'
import WorkspacePage from './pages/WorkspacePage'
import PluginMarketPage from './pages/PluginMarketPage'
import LoginPage from './pages/LoginPage'
import AppBrand from './components/AppBrand'
import BootScreen, { useBackendBoot } from './components/BootScreen'
import SidebarWorkspace from './components/SidebarWorkspace'
import SidebarSplit from './components/SidebarSplit'
import SidebarUserFoot from './components/SidebarUserFoot'
import { useAuthStore } from './stores/auth'

type LinkItem = { to: string; label: string; icon: ReactNode; matchPrefix?: boolean }

const mainLinks: LinkItem[] = [
  {
    to: '/market',
    label: '插件市场',
    matchPrefix: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />
      </svg>
    ),
  },
  {
    to: '/knowledge',
    label: '资料库',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 5h7a3 3 0 013 3v11H7a3 3 0 01-3-3V5zM20 5h-7a3 3 0 00-3 3v11h7a3 3 0 003-3V5z" />
      </svg>
    ),
  },
  {
    to: '/automation',
    label: '自动化',
    matchPrefix: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    to: '/audit',
    label: '审计舱',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M9 5h11v14H9zM4 8h3M4 12h3M4 16h3" />
      </svg>
    ),
  },
  {
    to: '/checklists',
    label: '清单',
    matchPrefix: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M9 6h11M9 12h11M9 18h11M5 6l.8.8L7.5 5M5 12l.8.8L7.5 11M5 18l.8.8L7.5 17" />
      </svg>
    ),
  },
  {
    to: '/settings',
    label: '设置',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
      </svg>
    ),
  },
]

function ProjectsNavLink() {
  const location = useLocation()
  const active = location.pathname === '/projects' || location.pathname.startsWith('/projects/')
  return (
    <NavLink to="/projects" className={active ? 'nav active' : 'nav'}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 7h16v12H4zM8 7V5h8v2" />
        <path d="M9 12h6M9 16h4" />
      </svg>
      <span>项目</span>
    </NavLink>
  )
}

function NavGroup({ title, items }: { title?: string; items: LinkItem[] }) {
  const location = useLocation()
  return (
    <div className="nav-section">
      {title ? <div className="nav-label">{title}</div> : null}
      {items.map((l) => {
        const active = l.matchPrefix
          ? location.pathname === l.to || location.pathname.startsWith(`${l.to}/`)
          : undefined
        return (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) => {
              const on = active ?? isActive
              return on ? 'nav active' : 'nav'
            }}
          >
            {l.icon}
            <span>{l.label}</span>
          </NavLink>
        )
      })}
    </div>
  )
}

function TaskEntry() {
  const [params] = useSearchParams()
  const session = params.get('session')
  const compose = params.get('compose')
  const { sessionId, setSessionId, setMessages, setWorkspaceId } = useAppStore()
  useEffect(() => {
    if (session) {
      if (session !== sessionId) setSessionId(session)
      return
    }
    if (compose === 'schedule') {
      setSessionId(null)
      setMessages([])
      setWorkspaceId(null)
    }
  }, [session, compose, sessionId, setSessionId, setMessages, setWorkspaceId])
  return <ChatPage />
}

export default function App() {
  const { token, hydrated, hydrate, logout, username } = useAuthStore()
  const boot = useBackendBoot()

  useEffect(() => {
    hydrate()
  }, [hydrate])

  if (!boot.ready) {
    return (
      <BootScreen
        progress={boot.progress}
        elapsedMs={boot.elapsedMs}
        error={boot.error}
        failed={boot.failed}
        retrying={boot.retrying}
        onRetry={boot.retry}
      />
    )
  }

  if (!hydrated) {
    return (
      <div className="login-page">
        <p className="muted">加载中…</p>
      </div>
    )
  }

  if (!token) {
    return <LoginPage />
  }

  return <AppShell username={username} onLogout={() => void logout()} />
}

function AppShell({ username, onLogout }: { username: string | null; onLogout: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const isChatRoute = location.pathname === '/tasks'
  const { backendHealthy, setBackendHealthy, setSessionId, setMessages, setWorkspaceId } = useAppStore()

  useEffect(() => {
    const ping = async () => {
      try {
        if (window.api?.backendStatus) {
          const s = await window.api.backendStatus()
          setBackendHealthy(s.healthy)
        } else {
          const r = await fetch('http://127.0.0.1:18765/api/v1/health')
          setBackendHealthy(r.ok)
        }
      } catch {
        setBackendHealthy(false)
      }
    }
    ping()
    const t = setInterval(ping, 5000)
    return () => clearInterval(t)
  }, [setBackendHealthy])

  const restartBackend = async () => {
    try {
      if (window.api?.backendRestart) {
        await window.api.backendRestart()
        const s = await window.api.backendStatus()
        setBackendHealthy(s.healthy)
      } else {
        const r = await fetch('http://127.0.0.1:18765/api/v1/health')
        setBackendHealthy(r.ok)
      }
    } catch {
      setBackendHealthy(false)
    }
  }

  const goNewTask = () => {
    setSessionId(null)
    setMessages([])
    setWorkspaceId(null)
    useAppStore.getState().setSidebarViewMode('group')
    navigate('/tasks')
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-top">
          <AppBrand healthy={backendHealthy} />
          <div className="sidebar-top-actions">
            <button
              type="button"
              className="sidebar-icon-btn"
              title="筛选任务"
              aria-label="筛选任务"
              onClick={() => window.dispatchEvent(new CustomEvent('psa-sidebar-filter'))}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>

        <div className="sidebar-cta-row">
          <button type="button" className="btn-new" onClick={goNewTask}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path
                d="M7 6.5h7.5a3 3 0 013 3V14a3 3 0 01-3 3H11l-4 3v-3H7a3 3 0 01-3-3V9.5a3 3 0 013-3z"
                strokeLinejoin="round"
              />
              <path d="M12 9.5v5M9.5 12h5" strokeLinecap="round" />
            </svg>
            新建任务
          </button>
        </div>

        <SidebarSplit
          nav={
            <>
              <ProjectsNavLink />
              <NavGroup items={mainLinks} />
            </>
          }
          workspace={<SidebarWorkspace />}
        />
        {username ? <SidebarUserFoot username={username} onLogout={onLogout} /> : null}
      </aside>

      <main className={`main${isChatRoute ? ' main--chat' : ''}`}>
        {!backendHealthy && (
          <div className="banner warn">
            <span>本地后端未就绪（127.0.0.1:18765），页面操作会失败。请确认已安装 server/.venv 依赖。</span>
            <button type="button" onClick={() => void restartBackend()}>
              重试连接 / 重启后端
            </button>
          </div>
        )}
        <Routes>
          <Route path="/" element={<Navigate to="/tasks" replace />} />
          <Route path="/tasks" element={<TaskEntry />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:workspaceId" element={<WorkspacePage />} />
          <Route path="/workspaces" element={<Navigate to="/projects" replace />} />
          <Route path="/market/*" element={<PluginMarketPage />} />
          <Route path="/experts" element={<Navigate to="/market/experts" replace />} />
          <Route path="/skills" element={<Navigate to="/market/skills" replace />} />
          <Route path="/mcp" element={<Navigate to="/market/mcp" replace />} />
          <Route path="/memory" element={<Navigate to="/tasks" replace />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/automation" element={<ScheduledTasksPage />} />
          <Route path="/automation/new" element={<ScheduledTaskEditorPage />} />
          <Route path="/automation/:jobId/edit" element={<ScheduledTaskEditorPage />} />
          <Route path="/scheduled-tasks" element={<Navigate to="/automation" replace />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/checklists" element={<ChecklistPage />} />
          <Route path="/checklists/:id" element={<ChecklistDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
