/**
 * TanStack Query 全局客户端
 *
 * - 默认 5 分钟 staleTime（避免重复请求）
 * - 失败重试 1 次（提升 UX）
 * - 断网重连后自动重新请求
 */

import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // 401 不重试，由 axios 拦截器处理 token 刷新
        if (error && typeof error === 'object' && 'response' in error) {
          const status = (error as { response?: { status?: number } }).response?.status
          if (status === 401 || status === 403 || status === 404) return false
        }
        return failureCount < 1
      },
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      staleTime: 30 * 1000,
      gcTime: 10 * 60 * 1000,
    },
    mutations: {
      retry: 0,
    },
  },
})
