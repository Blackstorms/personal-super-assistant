import { describe, expect, it, vi } from 'vitest'
import { isDarkTheme, nativeThemeSource, resolveEffectiveTheme } from './theme'

describe('theme', () => {
  it('resolveEffectiveTheme follows system preference', () => {
    vi.stubGlobal('window', {
      matchMedia: () => ({ matches: true }) as MediaQueryList,
    })
    expect(resolveEffectiveTheme('system')).toBe('dark')
    vi.unstubAllGlobals()
  })

  it('resolveEffectiveTheme returns preset themes unchanged', () => {
    expect(resolveEffectiveTheme('deepsea-dark')).toBe('deepsea-dark')
    expect(resolveEffectiveTheme('scroll-light')).toBe('scroll-light')
    expect(resolveEffectiveTheme('glass-dark')).toBe('glass-dark')
  })

  it('isDarkTheme identifies dark variants', () => {
    expect(isDarkTheme('dark')).toBe(true)
    expect(isDarkTheme('deepsea-dark')).toBe(true)
    expect(isDarkTheme('scroll-dark')).toBe(true)
    expect(isDarkTheme('glass-dark')).toBe(true)
    expect(isDarkTheme('deepsea-light')).toBe(false)
    expect(isDarkTheme('light')).toBe(false)
  })

  it('nativeThemeSource maps preset themes correctly', () => {
    expect(nativeThemeSource('light')).toBe('light')
    expect(nativeThemeSource('dark')).toBe('dark')
    expect(nativeThemeSource('deepsea-dark')).toBe('dark')
    expect(nativeThemeSource('deepsea-light')).toBe('light')
    expect(nativeThemeSource('glass-dark')).toBe('dark')
    expect(nativeThemeSource('system')).toBe('system')
  })
})
