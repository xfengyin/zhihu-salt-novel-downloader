/**
 * 主题管理 Hook
 *
 * 跟踪 system/light/dark 主题切换，
 * 监听系统主题变化，自动应用 CSS class
 */

import { useEffect, useState } from 'react'

import { useAppStore } from '@/store/appStore'

export type Theme = 'light' | 'dark' | 'system'

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme(): {
  theme: Theme
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
} {
  const theme = useAppStore((s) => s.settings.theme)
  const updateSettings = useAppStore((s) => s.updateSettings)
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(getSystemTheme)

  // 监听系统主题变化
  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setSystemTheme(e.matches ? 'dark' : 'light')
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // 应用主题到 <html> 元素
  const resolvedTheme: 'light' | 'dark' = theme === 'system' ? systemTheme : theme
  useEffect(() => {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(resolvedTheme)
  }, [resolvedTheme])

  return {
    theme,
    resolvedTheme,
    setTheme: (newTheme) => updateSettings({ theme: newTheme }),
  }
}
