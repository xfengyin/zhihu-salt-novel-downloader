import { create } from 'zustand'
import type { DownloadConfig, DownloadProgress, Book, Task } from '@/types'

interface AppState {
  theme: 'system' | 'light' | 'dark'
  language: 'zh' | 'en'
  config: DownloadConfig
  progress: DownloadProgress
  library: Book[]
  tasks: Task[]
  sidebarCollapsed: boolean

  setTheme: (theme: 'system' | 'light' | 'dark') => void
  setLanguage: (language: 'zh' | 'en') => void
  updateConfig: (config: Partial<DownloadConfig>) => void
  setProgress: (progress: Partial<DownloadProgress>) => void
  addBook: (book: Book) => void
  removeBook: (bookId: string) => void
  updateBook: (bookId: string, updates: Partial<Book>) => void
  addTask: (task: Task) => void
  updateTask: (taskId: string, updates: Partial<Task>) => void
  removeTask: (taskId: string) => void
  toggleSidebar: () => void
}

const defaultConfig: DownloadConfig = {
  url: '',
  outputDir: './output',
  format: 'md',
  maxConcurrent: 3,
  rateLimit: 2,
  cleanContent: true,
  resume: false,
}

const defaultProgress: DownloadProgress = {
  total: 0,
  downloaded: 0,
  status: 'idle',
}

export const useAppStore = create<AppState>((set) => ({
  theme: 'system',
  language: 'zh',
  config: defaultConfig,
  progress: defaultProgress,
  library: [],
  tasks: [],
  sidebarCollapsed: false,

  setTheme: (theme) => set({ theme }),
  setLanguage: (language) => set({ language }),
  updateConfig: (config) => set((state) => ({ config: { ...state.config, ...config } })),
  setProgress: (progress) => set((state) => ({ progress: { ...state.progress, ...progress } })),
  addBook: (book) => set((state) => ({ library: [...state.library, book] })),
  removeBook: (bookUrl) => set((state) => ({ library: state.library.filter((b) => b.url !== bookUrl) })),
  updateBook: (bookUrl, updates) =>
    set((state) => ({
      library: state.library.map((b) => (b.url === bookUrl ? { ...b, ...updates } : b)),
    })),
  addTask: (task) => set((state) => ({ tasks: [...state.tasks, task] })),
  updateTask: (taskId, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) => (t.id === taskId ? { ...t, ...updates } : t)),
    })),
  removeTask: (taskId) => set((state) => ({ tasks: state.tasks.filter((t) => t.id !== taskId) })),
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}))