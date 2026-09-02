import { useEffect } from 'react'
import { applyThemeToDocument } from '../lib/theme'
import { useThemeStore } from '../stores/theme'

/** 挂载主题 store，监听系统深浅色变化（system 模式）。 */
export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const hydrate = useThemeStore((s) => s.hydrate)
  const themeMode = useThemeStore((s) => s.themeMode)
  const accent = useThemeStore((s) => s.accent)

  useEffect(() => {
    hydrate()
  }, [hydrate])

  useEffect(() => {
    if (themeMode !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      const effective = applyThemeToDocument('system', accent)
      useThemeStore.setState({ effectiveTheme: effective })
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [themeMode, accent])

  return <>{children}</>
}
