/**
 * 通用工具函数
 */

import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** 合并 className（Tailwind 友好） */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** 格式化时间戳 */
export function formatDate(timestamp: string | number | Date, locale = 'zh-CN'): string {
  const date = timestamp instanceof Date ? timestamp : new Date(timestamp)
  return date.toLocaleString(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** 格式化相对时间（如 "5 分钟前"） */
export function formatRelativeTime(timestamp: string | number | Date, locale = 'zh-CN'): string {
  const date = timestamp instanceof Date ? timestamp : new Date(timestamp)
  const now = Date.now()
  const diff = now - date.getTime()
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  if (seconds < 60) return rtf.format(-seconds, 'second')
  if (minutes < 60) return rtf.format(-minutes, 'minute')
  if (hours < 24) return rtf.format(-hours, 'hour')
  return rtf.format(-days, 'day')
}

/** 字节数格式化（B/KB/MB/GB） */
export function formatBytes(bytes: number, decimals = 2): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(decimals))} ${sizes[i]}`
}

/** 截断字符串 */
export function truncate(str: string, maxLen = 50): string {
  if (str.length <= maxLen) return str
  return `${str.slice(0, maxLen)}…`
}

/** 安全的 JSON.parse */
export function safeJsonParse<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T
  } catch {
    return fallback
  }
}

/** 异步 sleep */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 限流（简单节流） */
export function throttle<T extends (...args: never[]) => void>(fn: T, delay: number): T {
  let last = 0
  return ((...args: Parameters<T>) => {
    const now = Date.now()
    if (now - last >= delay) {
      last = now
      fn(...args)
    }
  }) as T
}
