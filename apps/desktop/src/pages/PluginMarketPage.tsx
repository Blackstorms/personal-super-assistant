/**
 * 插件市场：专家 / 技能 / 连接器统一入口。
 */
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import ExpertsPage from './ExpertsPage'
import SkillsPage from './SkillsPage'
import McpPage from './McpPage'

const TABS = [
  { to: '/market/experts', label: '专家' },
  { to: '/market/skills', label: '技能' },
  { to: '/market/mcp', label: '连接器' },
] as const

export default function PluginMarketPage() {
  const location = useLocation()
  const showTabs = TABS.some((t) => location.pathname === t.to || location.pathname.startsWith(`${t.to}/`))

  return (
    <div className="plugin-market">
      {showTabs ? (
        <div className="plugin-market-tabs" role="tablist" aria-label="插件市场分类">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              role="tab"
              className={({ isActive }) => `plugin-market-tab ${isActive ? 'active' : ''}`}
            >
              {t.label}
            </NavLink>
          ))}
        </div>
      ) : null}
      <div className="plugin-market-body">
        <Routes>
          <Route index element={<Navigate to="experts" replace />} />
          <Route path="experts" element={<ExpertsPage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="mcp" element={<McpPage />} />
          <Route path="*" element={<Navigate to="experts" replace />} />
        </Routes>
      </div>
    </div>
  )
}
