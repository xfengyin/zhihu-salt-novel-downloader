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

/**
 * 导出格式枚举，与后端 DownloadRequest.export_format 对齐
 * 包含 mobi 以支持 Kindle 转换输出
 */
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
  /** 完成事件携带的输出文件列表，用于在 UI 展示导出产物 */
  outputFiles?: string[]
}

/**
 * SSE 进度事件，与后端 ProgressEventSchema 完全对齐
 * 用于流式订阅下载进度
 */
export interface ProgressEvent {
  type: 'info' | 'progress' | 'export' | 'complete' | 'error'
  message: string
  total: number
  downloaded: number
  current: string
  book_title: string
  output_files: string[]
}

/**
 * 书架单本书籍元数据，与后端 BookSchema 对齐
 */
export interface Book {
  url: string
  title: string
  author: string
  chapter_count: number
  completed: boolean
  added_at: string
  last_update: string
}

/**
 * 书架统计信息
 */
export interface ShelfStats {
  total: number
  completed: number
  in_progress: number
}
