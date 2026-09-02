import { ACCENT_OPTIONS, THEME_MODE_OPTIONS, type AccentColor, type ThemeMode } from '../lib/theme'
import { useThemeStore } from '../stores/theme'

type PreviewColors = { sidebar: string; surface: string; soft: string; userBubble?: string }

const PREVIEW_COLORS: Partial<Record<ThemeMode, PreviewColors>> = {
  light: { sidebar: '#ebecee', surface: '#ffffff', soft: '#f7f8fa' },
  dark: { sidebar: '#16181c', surface: '#25282e', soft: '#2c3036' },
  system: { sidebar: '#d8dce0', surface: '#f0f2f5', soft: '#e8eaed' },
  'deepsea-dark': { sidebar: '#0f1820', surface: '#1F2E3D', soft: '#121C26', userBubble: '#0891B2' },
  'deepsea-light': { sidebar: '#d9f0f2', surface: '#ffffff', soft: '#ECF8F9', userBubble: '#0E7490' },
  'scroll-light': { sidebar: '#ede8e0', surface: '#ffffff', soft: '#F7F4EF', userBubble: '#B45309' },
  'scroll-dark': { sidebar: '#14100e', surface: '#26211C', soft: '#1A1512', userBubble: '#C2410C' },
  'glass-light': { sidebar: 'rgba(255,255,255,0.15)', surface: 'rgba(255,255,255,0.65)', soft: 'rgba(255,255,255,0.45)', userBubble: 'rgba(22,93,255,0.75)' },
  'glass-dark': { sidebar: 'rgba(15,23,42,0.35)', surface: 'rgba(30,41,59,0.6)', soft: 'rgba(15,23,42,0.4)', userBubble: 'rgba(59,130,246,0.7)' },
}

function ThemePreview({ id }: { id: ThemeMode }) {
  const colors = PREVIEW_COLORS[id]
  if (!colors) return null

  if (id.startsWith('glass-')) {
    const isLight = id === 'glass-light'
    return (
      <div
        className={`theme-mode-preview theme-mode-preview-glass-bg${isLight ? ' theme-mode-preview-glass-light' : ' theme-mode-preview-glass-dark'}`}
      >
        <div className="theme-mode-preview-glass-panel" style={{ background: colors.surface }} aria-hidden />
        {colors.userBubble ? (
          <div className="theme-mode-preview-glass-user" style={{ background: colors.userBubble }} aria-hidden />
        ) : null}
      </div>
    )
  }

  return (
    <div className="theme-mode-preview" style={{ background: colors.soft }}>
      <div className="theme-mode-preview-sidebar" style={{ background: colors.sidebar }} />
      <div className="theme-mode-preview-main" style={{ background: colors.surface }}>
        <div className="theme-mode-preview-bar" style={{ background: colors.soft }} />
        {colors.userBubble ? (
          <div className="theme-mode-preview-user-bubble" style={{ background: colors.userBubble }} />
        ) : (
          <div className="theme-mode-preview-card" style={{ background: colors.soft }} />
        )}
      </div>
    </div>
  )
}

export default function AppearanceSettings() {
  const themeMode = useThemeStore((s) => s.themeMode)
  const accent = useThemeStore((s) => s.accent)
  const setThemeMode = useThemeStore((s) => s.setThemeMode)
  const setAccent = useThemeStore((s) => s.setAccent)

  return (
    <div className="panel appearance-section">
      <div className="appearance-group">
        <h4>基础</h4>
        <div className="theme-mode-grid">
          {THEME_MODE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={`theme-mode-card${themeMode === opt.id ? ' active' : ''}`}
              onClick={() => setThemeMode(opt.id)}
            >
              <ThemePreview id={opt.id} />
              <span className="theme-mode-card-label">{opt.label}</span>
              <span className="theme-mode-card-desc">{opt.desc}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="appearance-group">
        <h4>强调色</h4>
        <p className="muted text-secondary" style={{ fontSize: 12, margin: '0 0 10px' }}>
          影响主按钮、链接与选中态点缀色；预设主题自带强调色，切换后仍可微调。
        </p>
        <div className="accent-swatch-row">
          {ACCENT_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={`accent-swatch${accent === opt.id ? ' active' : ''}`}
              onClick={() => setAccent(opt.id as AccentColor)}
              title={opt.label}
            >
              <span className="accent-swatch-dot" style={{ background: opt.swatch }} />
              <span className="accent-swatch-label">{opt.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
