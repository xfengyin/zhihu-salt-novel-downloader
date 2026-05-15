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

export interface DownloadConfig {
  url: string
  cookieFile?: string
  token?: string
  outputDir: string
  format: 'txt' | 'md' | 'epub' | 'all'
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
}
