import { create } from 'zustand'
import {
  type AccentColor,
  type EffectiveTheme,
  type ThemeMode,
  applyThemeToDocument,
  getStoredAccent,
  getStoredThemeMode,
  isDarkTheme,
  nativeThemeSource,
  resolveEffectiveTheme,
  THEME_LIGHT_DARK_PAIRS,
  THEME_ACCENT_KEY,
  THEME_MODE_KEY,
} from '../lib/theme'

type ThemeState = {
  themeMode: ThemeMode
  accent: AccentColor
  effectiveTheme: EffectiveTheme
  hydrated: boolean
  hydrate: () => void
  setThemeMode: (mode: ThemeMode) => void
  setAccent: (accent: AccentColor) => void
  toggleLightDark: () => void
}

function persistAndApply(mode: ThemeMode, accent: AccentColor) {
  localStorage.setItem(THEME_MODE_KEY, mode)
  localStorage.setItem(THEME_ACCENT_KEY, accent)
  const effective = applyThemeToDocument(mode, accent)
  if (window.api?.setThemeSource) {
    void window.api.setThemeSource(nativeThemeSource(mode))
  }
  return effective
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  themeMode: 'light',
  accent: 'ink',
  effectiveTheme: 'light',
  hydrated: false,
  hydrate: () => {
    const themeMode = getStoredThemeMode()
    const accent = getStoredAccent()
    const effective = persistAndApply(themeMode, accent)
    set({ themeMode, accent, effectiveTheme: effective, hydrated: true })
  },
  setThemeMode: (mode) => {
    const accent = get().accent
    const effective = persistAndApply(mode, accent)
    set({ themeMode: mode, effectiveTheme: effective })
  },
  setAccent: (accent) => {
    const mode = get().themeMode
    const effective = persistAndApply(mode, accent)
    set({ accent, effectiveTheme: effective })
  },
  toggleLightDark: () => {
    const { themeMode } = get()
    const paired = THEME_LIGHT_DARK_PAIRS[themeMode]
    if (paired) {
      get().setThemeMode(paired)
      return
    }
    if (themeMode === 'system') {
      const effective = resolveEffectiveTheme('system')
      get().setThemeMode(effective === 'dark' ? 'light' : 'dark')
      return
    }
    const effective = resolveEffectiveTheme(themeMode)
    const next: ThemeMode = isDarkTheme(effective) ? 'light' : 'dark'
    get().setThemeMode(next)
  },
}))
