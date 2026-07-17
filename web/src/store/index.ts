import { create } from 'zustand'
import { Book, DownloadConfig } from '../types'

export interface User {
  id: string
  name: string
  email: string
  avatar?: string
  token?: string
}

export interface Task {
  id: string
  bookUrl: string
  bookTitle: string
  status: 'pending' | 'downloading' | 'exporting' | 'completed' | 'error'
  progress: number
  message?: string
  createdAt: string
}

export interface Config {
  download: DownloadConfig
  autoStart: boolean
  notifications: boolean
  language: 'zh-CN' | 'en-US'
}

export interface Theme {
  mode: 'light' | 'dark' | 'system'
  accentColor: string
}

interface Store {
  user: User | null
  shelves: string[]
  books: Book[]
  tasks: Task[]
  config: Config
  theme: Theme

  login: (user: User) => void
  logout: () => void

  addBook: (book: Book) => void
  removeBook: (url: string) => void

  addTask: (task: Task) => void
  removeTask: (id: string) => void
  updateTask: (id: string, updates: Partial<Task>) => void

  updateConfig: (updates: Partial<Config>) => void
  setTheme: (theme: Theme) => void
}

const defaultConfig: Config = {
  download: {
    url: '',
    outputDir: './output',
    format: 'epub',
    maxConcurrent: 5,
    rateLimit: 1000,
    cleanContent: true,
    resume: true,
  },
  autoStart: false,
  notifications: true,
  language: 'zh-CN',
}

const defaultTheme: Theme = {
  mode: 'system',
  accentColor: '#4F46E5',
}

export const useStore = create<Store>((set) => ({
  user: null,
  shelves: [],
  books: [],
  tasks: [],
  config: defaultConfig,
  theme: defaultTheme,

  login: (user) => set({ user }),
  logout: () => set({ user: null }),

  addBook: (book) =>
    set((state) => ({
      books: state.books.find((b) => b.url === book.url)
        ? state.books
        : [...state.books, book],
    })),

  removeBook: (url) =>
    set((state) => ({
      books: state.books.filter((b) => b.url !== url),
    })),

  addTask: (task) =>
    set((state) => ({
      tasks: [...state.tasks, task],
    })),

  removeTask: (id) =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.id !== id),
    })),

  updateTask: (id, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.id === id ? { ...t, ...updates } : t
      ),
    })),

  updateConfig: (updates) =>
    set((state) => ({
      config: { ...state.config, ...updates },
    })),

  setTheme: (theme) => set({ theme }),
}))