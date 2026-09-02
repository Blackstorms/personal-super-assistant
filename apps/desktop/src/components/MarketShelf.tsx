/**
 * 插件市场风格：公开/个人切换 + 分类卡片栅格。
 */
import type { ReactNode } from 'react'

export type MarketScope = 'public' | 'personal'

export type MarketCardItem = {
  id: string
  name: string
  description?: string | null
  category?: string | null
  badge?: string | null
  icon?: string | null
  installed?: boolean
}

type ScopeTabsProps = {
  scope: MarketScope
  onChange: (s: MarketScope) => void
  publicLabel?: string
  personalLabel?: string
  trailing?: ReactNode
}

export function MarketScopeTabs({
  scope,
  onChange,
  publicLabel = '公开',
  personalLabel = '个人',
  trailing,
}: ScopeTabsProps) {
  return (
    <div className="market-top">
      <div className="market-scope" role="tablist">
        <button
          type="button"
          role="tab"
          className={`market-scope-btn ${scope === 'public' ? 'active' : ''}`}
          aria-selected={scope === 'public'}
          onClick={() => onChange('public')}
        >
          {publicLabel}
        </button>
        <button
          type="button"
          role="tab"
          className={`market-scope-btn ${scope === 'personal' ? 'active' : ''}`}
          aria-selected={scope === 'personal'}
          onClick={() => onChange('personal')}
        >
          {personalLabel}
        </button>
      </div>
      {trailing ? <div className="market-top-actions">{trailing}</div> : null}
    </div>
  )
}

const ICON_COLORS: Record<string, string> = {
  wecom: '#2B7DE9',
  feishu: '#3370FF',
  mail: '#F59E0B',
  slack: '#E01E5A',
  notion: '#1A1A1A',
  fs: '#0EA5E9',
  github: '#24292F',
  git: '#F97316',
  db: '#6366F1',
  browser: '#8B5CF6',
  think: '#14B8A6',
  memory: '#EC4899',
  fetch: '#06B6D4',
  search: '#3B82F6',
  time: '#84CC16',
  maps: '#22C55E',
  demo: '#94A3B8',
  docs: '#0EA5E9',
  product: '#F59E0B',
  ops: '#F97316',
  ux: '#A855F7',
  frontend: '#38BDF8',
  backend: '#64748B',
  fullstack: '#0EA5E9',
  devops: '#EF4444',
  qa: '#22C55E',
  security: '#DC2626',
  data: '#6366F1',
  research: '#0D9488',
  write: '#8B5CF6',
  copy: '#EC4899',
  translate: '#3B82F6',
  meeting: '#F59E0B',
  assistant: '#64748B',
  teach: '#14B8A6',
  career: '#F97316',
  legal: '#475569',
  prompt: '#8B5CF6',
  skill: '#EAB308',
  default: '#6B7280',
}

function MarketIcon({ icon, name }: { icon?: string | null; name: string }) {
  const key = icon || 'default'
  const bg = ICON_COLORS[key] || ICON_COLORS.default
  const letter = (name || '?').trim().charAt(0).toUpperCase() || '?'
  return (
    <div className="market-icon" style={{ background: bg }} aria-hidden>
      {letter}
    </div>
  )
}

type CardProps = {
  item: MarketCardItem
  onInstall?: () => void
  installLabel?: string
  installing?: boolean
  menu?: ReactNode
  onClick?: () => void
}

export function MarketCard({ item, onInstall, installLabel = '安装', installing, menu, onClick }: CardProps) {
  return (
    <div className="market-card" onClick={onClick} role={onClick ? 'button' : undefined}>
      <MarketIcon icon={item.icon} name={item.name} />
      <div className="market-card-body">
        <div className="market-card-title-row">
          <span className="market-card-title">{item.name}</span>
          {item.badge ? <span className="market-badge">{item.badge}</span> : null}
        </div>
        <p className="market-card-desc">{item.description || '暂无描述'}</p>
      </div>
      <div className="market-card-action" onClick={(e) => e.stopPropagation()}>
        {item.installed ? (
          menu ?? <span className="market-more" title="已安装">···</span>
        ) : (
          <button
            type="button"
            className="market-install"
            disabled={installing}
            onClick={() => onInstall?.()}
          >
            {installing ? '…' : installLabel}
          </button>
        )}
      </div>
    </div>
  )
}

type SectionProps = {
  title: string
  children: ReactNode
}

export function MarketSection({ title, children }: SectionProps) {
  return (
    <section className="market-section">
      <h3 className="market-section-title">{title}</h3>
      <div className="market-grid">{children}</div>
    </section>
  )
}

export function groupByCategory<T extends { category?: string | null }>(
  items: T[],
  fallback = '其他',
): Array<{ category: string; items: T[] }> {
  const map = new Map<string, T[]>()
  for (const it of items) {
    const cat = (it.category || fallback).trim() || fallback
    if (!map.has(cat)) map.set(cat, [])
    map.get(cat)!.push(it)
  }
  return Array.from(map.entries()).map(([category, list]) => ({ category, items: list }))
}

/** 技能 ID → 市场分类 / 图标 */
export const SKILL_MARKET_META: Record<string, { category: string; icon: string; badge?: string }> = {
  'file-summarize': { category: '生产力', icon: 'docs' },
  'text-organize': { category: '生产力', icon: 'write' },
  'todo-draft': { category: '生产力', icon: 'ops' },
  'meeting-notes': { category: '生产力', icon: 'meeting' },
  'email-draft': { category: '生产力', icon: 'mail' },
  translate: { category: '生产力', icon: 'translate' },
  'daily-plan': { category: '生产力', icon: 'time' },
  copywriting: { category: '生产力', icon: 'copy' },
  'rewrite-tone': { category: '生产力', icon: 'write' },
  'research-brief': { category: '生产力', icon: 'research' },
  brainstorm: { category: '生产力', icon: 'think' },
  'compare-options': { category: '生产力', icon: 'product' },
  'explain-simple': { category: '生产力', icon: 'teach' },
  'frontend-design': { category: '开发者工具', icon: 'frontend', badge: '编程套餐' },
  'code-review': { category: '开发者工具', icon: 'github', badge: '编程套餐' },
  'git-commit': { category: '开发者工具', icon: 'git' },
  'pr-description': { category: '开发者工具', icon: 'github' },
  'diagnose-bug': { category: '开发者工具', icon: 'qa' },
  'skill-creator': { category: '开发者工具', icon: 'prompt' },
  'prompt-optimize': { category: '开发者工具', icon: 'prompt' },
}
