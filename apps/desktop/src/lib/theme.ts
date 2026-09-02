/** 外观主题：模式 + 强调色，通过 html data-* 驱动 CSS 变量。 */

export type ThemeMode =
  | 'light'
  | 'dark'
  | 'deepsea-dark'
  | 'deepsea-light'
  | 'scroll-light'
  | 'scroll-dark'
  | 'glass-light'
  | 'glass-dark'
  | 'system'

export type AccentColor = 'ink' | 'sage' | 'sky' | 'coral' | 'violet'

export type EffectiveTheme = Exclude<ThemeMode, 'system'>

export const THEME_MODE_KEY = 'psa_theme_mode'
export const THEME_ACCENT_KEY = 'psa_theme_accent'

const DARK_THEMES = new Set<EffectiveTheme>(['dark', 'deepsea-dark', 'scroll-dark', 'glass-dark'])

/** 旧版主题 ID 迁移。 */
const LEGACY_THEME_MODE_MAP: Record<string, ThemeMode> = {
  'ocean-dark': 'deepsea-dark',
  'ocean-light': 'deepsea-light',
  'scholar-dark': 'scroll-dark',
  'scholar-light': 'scroll-light',
  paper: 'light',
  frost: 'light',
  'velvet-dark': 'dark',
  'velvet-light': 'light',
  'aurora-dark': 'dark',
  'aurora-light': 'light',
  'softneu-dark': 'dark',
  'softneu-light': 'light',
  'noir-dark': 'dark',
  'noir-light': 'light',
}

/** 同族主题浅深切换映射。 */
export const THEME_LIGHT_DARK_PAIRS: Partial<Record<ThemeMode, ThemeMode>> = {
  'deepsea-dark': 'deepsea-light',
  'deepsea-light': 'deepsea-dark',
  'scroll-dark': 'scroll-light',
  'scroll-light': 'scroll-dark',
  'glass-dark': 'glass-light',
  'glass-light': 'glass-dark',
}

export const THEME_MODE_OPTIONS: { id: ThemeMode; label: string; desc: string }[] = [
  { id: 'light', label: '浅色', desc: '默认 WorkBuddy 风格' },
  { id: 'dark', label: '深色', desc: '适合夜间与长时间使用' },
  { id: 'system', label: '跟随系统', desc: '自动匹配操作系统深浅色' },
  { id: 'deepsea-dark', label: '深海静谧 · 深', desc: '青蓝冷调，夜间写代码查资料' },
  { id: 'deepsea-light', label: '深海静谧 · 浅', desc: '护眼冷调浅色配套' },
  { id: 'scroll-light', label: '暖调书卷 · 浅', desc: '米棕纸感，适合长文阅读写作' },
  { id: 'scroll-dark', label: '暖调书卷 · 深', desc: '暖棕深色，人文阅读风' },
  { id: 'glass-light', label: '玻璃拟态 · 浅', desc: '毛玻璃半透明，现代悬浮感' },
  { id: 'glass-dark', label: '玻璃拟态 · 深', desc: '深色毛玻璃，适合透明窗口' },
]

export const ACCENT_OPTIONS: { id: AccentColor; label: string; swatch: string }[] = [
  { id: 'ink', label: '墨黑', swatch: '#1c1f24' },
  { id: 'sage', label: '鼠尾草', swatch: '#3d6b4f' },
  { id: 'sky', label: '天蓝', swatch: '#2563eb' },
  { id: 'coral', label: '珊瑚', swatch: '#c45c4a' },
  { id: 'violet', label: '紫罗兰', swatch: '#6d5cff' },
]

const VALID_MODES = new Set<string>(THEME_MODE_OPTIONS.map((o) => o.id))

export function getStoredThemeMode(): ThemeMode {
  const v = localStorage.getItem(THEME_MODE_KEY)
  if (!v) return 'light'
  const migrated = LEGACY_THEME_MODE_MAP[v] ?? v
  if (VALID_MODES.has(migrated)) {
    if (migrated !== v) localStorage.setItem(THEME_MODE_KEY, migrated)
    return migrated as ThemeMode
  }
  return 'light'
}

export function getStoredAccent(): AccentColor {
  const v = localStorage.getItem(THEME_ACCENT_KEY)
  if (v === 'ink' || v === 'sage' || v === 'sky' || v === 'coral' || v === 'violet') return v
  return 'ink'
}

export function isDarkTheme(theme: EffectiveTheme): boolean {
  return DARK_THEMES.has(theme)
}

/** 解析 system 为实际主题。 */
export function resolveEffectiveTheme(mode: ThemeMode): EffectiveTheme {
  if (mode === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return mode
}

/** 将主题写入 DOM（供首屏脚本与 React 共用）。 */
export function applyThemeToDocument(mode: ThemeMode, accent: AccentColor): EffectiveTheme {
  const effective = resolveEffectiveTheme(mode)
  const root = document.documentElement
  root.dataset.theme = effective
  root.dataset.accent = accent
  root.style.colorScheme = isDarkTheme(effective) ? 'dark' : 'light'
  return effective
}

/** Electron 标题栏/滚动条：深色主题映射 dark，其余 light。 */
export function nativeThemeSource(mode: ThemeMode): 'system' | 'light' | 'dark' {
  if (mode === 'system') return 'system'
  return isDarkTheme(mode as EffectiveTheme) ? 'dark' : 'light'
}
