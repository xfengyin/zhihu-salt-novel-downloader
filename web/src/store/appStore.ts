/**
 * 应用全局状态
 *
 * - 主题、语言、设置（持久化）
 * - 侧边栏折叠状态（会话级）
 */

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import { DEFAULT_SETTINGS, type AppSettings } from '@/types'

interface AppState {
  settings: AppSettings
  sidebarCollapsed: boolean
  activeTaskId: string | null

  // actions
  updateSettings: (updates: Partial<AppSettings>) => void
  resetSettings: () => void
  toggleSidebar: () => void
  setActiveTask: (taskId: string | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      settings: DEFAULT_SETTINGS,
      sidebarCollapsed: false,
      activeTaskId: null,

      updateSettings: (updates) =>
        set((state) => ({ settings: { ...state.settings, ...updates } })),

      resetSettings: () => set({ settings: DEFAULT_SETTINGS }),

      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      setActiveTask: (taskId) => set({ activeTaskId: taskId }),
    }),
    {
      name: 'zhihu-app',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ settings: state.settings }),
    },
  ),
)
