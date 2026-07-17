/**
 * 全局类型定义
 */

export type ExportFormat = 'epub' | 'mobi' | 'md' | 'txt'

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type Plan = 'free' | 'pro' | 'enterprise'

export interface BaseResponse<T = unknown> {
  success: boolean
  message?: string
  data?: T
  trace_id?: string
}

/** 应用全局设置（持久化到 localStorage） */
export interface AppSettings {
  theme: 'light' | 'dark' | 'system'
  language: 'zh-CN' | 'en-US'
  downloadDir: string
  maxConcurrent: number
  rateLimit: number
  exportFormat: ExportFormat
  enableTelemetry: boolean
  enableNotifications: boolean
  autoStartDownload: boolean
  proxyEnabled: boolean
  proxyUrl: string
  apiBaseUrl: string
}

/** 默认设置 */
export const DEFAULT_SETTINGS: AppSettings = {
  theme: 'system',
  language: 'zh-CN',
  downloadDir: '',
  maxConcurrent: 3,
  rateLimit: 5,
  exportFormat: 'epub',
  enableTelemetry: true,
  enableNotifications: true,
  autoStartDownload: false,
  proxyEnabled: false,
  proxyUrl: '',
  apiBaseUrl: '',
}
