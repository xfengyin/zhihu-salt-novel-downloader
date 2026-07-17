export interface Chapter {
  id: string
  title: string
  url: string
  order: number
  content?: string
  type?: 'normal' | 'extra' | 'author_note' | 'unknown'
}

export interface ArticleInfo {
  title: string
  author: string
  chapters: Chapter[]
  chapter_count: number
  description?: string
  cover_url?: string
}

export type ExportFormat = 'txt' | 'md' | 'epub' | 'mobi' | 'all'

export interface DownloadConfig {
  url: string
  cookieFile?: string
  token?: string
  outputDir: string
  format: ExportFormat
  maxConcurrent: number
  rateLimit: number
  cleanContent: boolean
  resume: boolean
}

export interface DownloadProgress {
  total: number
  downloaded: number
  current?: string
  status: 'idle' | 'downloading' | 'exporting' | 'completed' | 'error'
  error?: string
  outputFiles?: string[]
}

export interface ProgressEvent {
  type: 'info' | 'progress' | 'export' | 'complete' | 'error'
  message: string
  total: number
  downloaded: number
  current: string
  book_title: string
  output_files: string[]
}

export interface Book {
  url: string
  title: string
  author: string
  chapter_count: number
  completed: boolean
  added_at: string
  last_update: string
}

export interface ShelfStats {
  total: number
  completed: number
  in_progress: number
}

export interface Task {
  id: string
  url: string
  title: string
  status: 'pending' | 'downloading' | 'exporting' | 'completed' | 'error'
  progress: number
  total: number
  downloaded: number
  error?: string
  outputFiles?: string[]
  createdAt: string
}