import { isDarkTheme } from '../lib/theme'
import { useThemeStore } from '../stores/theme'

/** 侧栏底部：浅色/深色一键切换。 */
export default function ThemeToggle() {
  const effectiveTheme = useThemeStore((s) => s.effectiveTheme)
  const toggleLightDark = useThemeStore((s) => s.toggleLightDark)
  const isDark = isDarkTheme(effectiveTheme)

  return (
    <button
      type="button"
      className="sidebar-foot-theme"
      onClick={toggleLightDark}
      title={isDark ? '切换为浅色' : '切换为深色'}
      aria-label={isDark ? '切换为浅色主题' : '切换为深色主题'}
    >
      {isDark ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5z" />
        </svg>
      )}
    </button>
  )
}
