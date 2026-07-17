/**
 * 下载 API
 */

import { apiGet, apiPost } from './client'
import type { ProgressEvent } from './client'

export type ExportFormat = 'epub' | 'mobi' | 'md' | 'txt'

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface DownloadRequest {
  url?: string
  batch_urls?: string[]
  max_concurrent?: number
  rate_limit?: number
  output_dir?: string
  export_format?: ExportFormat
  list_only?: boolean
  clean_content?: boolean
  resume?: boolean
  update_check?: boolean
  cookie_file?: string
}

export interface DownloadTask {
  task_id: string
  status: TaskStatus
  created_at: string
  trace_id: string
}

export interface DownloadResponse {
  task_id: string
  trace_id: string
}

export function startDownload(data: DownloadRequest): Promise<DownloadResponse> {
  return apiPost<DownloadResponse, DownloadRequest>('/downloads', data)
}

export function listDownloads(): Promise<DownloadTask[]> {
  return apiGet<DownloadTask[]>('/downloads')
}

export function getDownloadStatus(taskId: string): Promise<DownloadTask> {
  return apiGet<DownloadTask>(`/downloads/${taskId}`)
}

export function cancelDownload(taskId: string): Promise<{ message: string; task_id: string }> {
  return apiPost<{ message: string; task_id: string }, unknown>(`/downloads/${taskId}/cancel`, {})
}

/**
 * 订阅 SSE 进度事件
 *
 * @param taskId 任务 ID
 * @param onEvent 事件回调
 * @returns 取消订阅函数
 */
export function subscribeProgress(taskId: string, onEvent: (event: ProgressEvent) => void): () => void {
  const url = `/api/downloads/${taskId}/events`
  const eventSource = new EventSource(url, { withCredentials: true })

  eventSource.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data) as ProgressEvent
      onEvent(event)
    } catch (err) {
      console.error('解析进度事件失败:', err)
    }
  }

  eventSource.onerror = (err) => {
    console.error('SSE 连接错误:', err)
    eventSource.close()
  }

  return () => {
    eventSource.close()
  }
}
