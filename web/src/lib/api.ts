/**
 * API 封装层 - 与后端 FastAPI 通信
 *
 * 用原生 fetch 实现，不引入 axios 等额外依赖。
 * SSE 流式订阅用 fetch + ReadableStream 手动解析 text/event-stream。
 */
import type {
  Book,
  DownloadConfig,
  ProgressEvent,
  ShelfStats,
} from '@/types'

/**
 * 后端 API 基础地址
 * 优先读环境变量 VITE_API_BASE，默认指向本地开发服务
 */
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// ---------------------------------------------------------------------------
// 通用请求工具
// ---------------------------------------------------------------------------

/**
 * 统一 fetch 封装，处理 JSON 与错误
 * @throws Error 当网络异常或响应非 2xx 时抛出
 */
async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!resp.ok) {
    // 尝试解析后端统一错误格式 {success, message, trace_id}
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      detail = body.detail || body.message || detail
    } catch {
      // 响应非 JSON，忽略
    }
    throw new Error(detail)
  }

  return resp.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// 下载相关
// ---------------------------------------------------------------------------

/**
 * 把前端 DownloadConfig 映射为后端 DownloadRequest（camelCase → snake_case）
 */
function buildDownloadPayload(config: DownloadConfig): Record<string, unknown> {
  return {
    url: config.url,
    cookie_file: config.cookieFile ?? null,
    token: config.token ?? null,
    output_dir: config.outputDir,
    export_format: config.format,
    max_concurrent: config.maxConcurrent,
    rate_limit: config.rateLimit,
    clean_content: config.cleanContent,
    resume: config.resume,
  }
}

/**
 * 启动下载任务
 * @returns 后端分配的 task_id，用于后续 SSE 订阅
 */
export async function startDownload(
  config: DownloadConfig,
): Promise<{ task_id: string }> {
  return request<{ task_id: string }>('/api/download', {
    method: 'POST',
    body: JSON.stringify(buildDownloadPayload(config)),
  })
}

/**
 * 订阅下载进度 SSE 流
 *
 * 用 fetch + ReadableStream 消费 text/event-stream，
 * 按 `\n\n` 分割事件块，提取 `data:` 行的 JSON 解析为 ProgressEvent。
 *
 * @param taskId 后端任务 ID
 * @param onEvent 每条进度事件的回调
 * @param onError 流异常时的回调
 * @returns 取消订阅函数，调用后中断流
 */
export function subscribeDownloadProgress(
  taskId: string,
  onEvent: (event: ProgressEvent) => void,
  onError?: (err: Error) => void,
): () => void {
  const controller = new AbortController()

  // SSE 流消费协程
  const consume = async (): Promise<void> => {
    try {
      const resp = await fetch(
        `${API_BASE}/api/download/stream/${taskId}`,
        { signal: controller.signal },
      )

      if (!resp.ok || !resp.body) {
        throw new Error(`SSE 连接失败: HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      // 持续读取并按事件块分割
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 事件以空行分隔，逐块解析
        const chunks = buffer.split('\n\n')
        // 最后一段可能不完整，保留到下次
        buffer = chunks.pop() ?? ''

        for (const chunk of chunks) {
          const dataLine = chunk
            .split('\n')
            .find(line => line.startsWith('data:'))

          if (!dataLine) continue

          const jsonStr = dataLine.slice(5).trim()
          if (!jsonStr) continue

          try {
            onEvent(JSON.parse(jsonStr) as ProgressEvent)
          } catch {
            // 单条解析失败不影响整体流
          }
        }
      }
    } catch (err) {
      // AbortError 是主动取消，不算错误
      if ((err as Error).name !== 'AbortError') {
        onError?.(err as Error)
      }
    }
  }

  consume()

  // 返回取消函数
  return () => controller.abort()
}

// ---------------------------------------------------------------------------
// 书架相关
// ---------------------------------------------------------------------------

/** 获取书架所有书籍 */
export async function getShelfBooks(): Promise<Book[]> {
  return request<Book[]>('/api/shelf/books')
}

/** 获取书架统计信息 */
export async function getShelfStats(): Promise<ShelfStats> {
  return request<ShelfStats>('/api/shelf/stats')
}

/** 添加书籍到书架 */
export async function addShelfBook(
  url: string,
): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>('/api/shelf/books', {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
}

/** 从书架移除书籍 */
export async function removeShelfBook(
  url: string,
): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>(
    `/api/shelf/books/${encodeURIComponent(url)}`,
    { method: 'DELETE' },
  )
}

/** 清空书架 */
export async function cleanShelf(): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>('/api/shelf/clean', {
    method: 'POST',
  })
}
