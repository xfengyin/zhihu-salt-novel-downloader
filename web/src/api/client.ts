/**
 * API 客户端核心
 *
 * 职责：
 * - 统一封装 axios 实例，处理 traceId 注入、错误处理、token 刷新
 * - 抽象出 REST 调用方法，对应后端 /api/* 路由
 * - 配合 Zustand 与 TanStack Query 使用
 */

import axios, { type AxiosError, type AxiosInstance, type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { useAuthStore } from '@/store/authStore'

/** 统一响应结构（与后端 {success, message, trace_id} 对齐） */
export interface ApiResponse<T = unknown> {
  success: boolean
  message?: string
  data?: T
  trace_id?: string
}

/** 错误响应（RFC 7807 Problem） */
export interface ProblemResponse {
  type?: string
  title?: string
  status?: number
  detail?: string
  instance?: string
  trace_id?: string
}

/** 进度事件（SSE） */
export interface ProgressEvent {
  type: 'info' | 'progress' | 'export' | 'complete' | 'error'
  message?: string
  current?: number
  total?: number
  data?: Record<string, unknown>
  timestamp?: number
}

/** TraceId 生成器 */
function generateTraceId(): string {
  // 16 字节随机 hex（32 字符），与后端 uuid4().hex 一致风格
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * 创建 axios 实例
 * - baseURL: 开发环境使用 Vite 代理（/api），Tauri 使用相对路径
 * - 自动注入 X-Trace-Id 请求头
 * - 401 自动尝试刷新 token
 */
function createAxiosInstance(): AxiosInstance {
  const instance = axios.create({
    baseURL: '/api',
    timeout: 30_000,
    headers: {
      'Content-Type': 'application/json',
    },
  })

  // 请求拦截：注入 traceId、token
  instance.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      // 已有 X-Trace-Id 则复用，否则生成新的
      if (!config.headers['X-Trace-Id']) {
        config.headers['X-Trace-Id'] = generateTraceId()
      }

      const token = useAuthStore.getState().accessToken
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }

      return config
    },
    (error: unknown) => Promise.reject(error),
  )

  // 响应拦截：统一错误处理
  instance.interceptors.response.use(
    (response: AxiosResponse) => response,
    async (error: AxiosError<ProblemResponse>) => {
      const originalRequest = error.config as (InternalAxiosRequestConfig & {
        _retry?: boolean
      }) | undefined

      // 401 尝试刷新 token
      if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
        originalRequest._retry = true
        const refreshToken = useAuthStore.getState().refreshToken
        if (refreshToken) {
          try {
            const resp = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
            const newToken = (resp.data as { access_token: string }).access_token
            useAuthStore.getState().setAccessToken(newToken)
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            return instance(originalRequest)
          } catch {
            // 刷新失败，清除登录状态
            useAuthStore.getState().logout()
          }
        }
      }

      return Promise.reject(error)
    },
  )

  return instance
}

export const http = createAxiosInstance()

/** 通用 API 调用 */
export async function apiGet<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const resp = await http.get<T>(url, config)
  return resp.data
}

export async function apiPost<T, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig): Promise<T> {
  const resp = await http.post<T>(url, data, config)
  return resp.data
}

export async function apiPut<T, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig): Promise<T> {
  const resp = await http.put<T>(url, data, config)
  return resp.data
}

export async function apiDelete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const resp = await http.delete<T>(url, config)
  return resp.data
}

/** 错误消息提取 */
export function extractErrorMessage(error: unknown, fallback = '操作失败'): string {
  if (axios.isAxiosError(error)) {
    const problem = error.response?.data as ProblemResponse | undefined
    if (problem?.detail) return problem.detail
    if (problem?.title) return problem.title
    if (error.message) return error.message
  }
  if (error instanceof Error) return error.message
  return fallback
}
