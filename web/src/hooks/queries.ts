/**
 * TanStack Query Hooks
 *
 * 集中封装业务查询/变更，自动处理缓存、失效、错误
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  addToShelf,
  cancelDownload,
  cleanShelf,
  getCurrentUser,
  getDownloadStatus,
  getShelfBook,
  getShelfStats,
  installPlugin,
  listDownloads,
  listPlugins,
  listShelf,
  login,
  register,
  removeFromShelf,
  startDownload,
  uninstallPlugin,
  updateShelfBook,
} from '@/api'

import { useAuthStore } from '@/store/authStore'

import type { DownloadRequest } from '@/api/download'

// === 查询 Key 工厂 ===
export const queryKeys = {
  user: ['user'] as const,
  shelf: ['shelf'] as const,
  shelfBook: (url: string) => ['shelf', 'book', url] as const,
  shelfStats: ['shelf', 'stats'] as const,
  downloads: ['downloads'] as const,
  download: (taskId: string) => ['downloads', taskId] as const,
  plugins: ['plugins'] as const,
}

// === 认证 ===

export function useLogin() {
  const setTokens = useAuthStore((s) => s.setTokens)
  return useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token)
    },
  })
}

export function useRegister() {
  const setTokens = useAuthStore((s) => s.setTokens)
  return useMutation({
    mutationFn: register,
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token)
    },
  })
}

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.user,
    queryFn: getCurrentUser,
    enabled: useAuthStore.getState().isAuthenticated,
    staleTime: 5 * 60 * 1000,
  })
}

// === 书架 ===

export function useShelf() {
  return useQuery({
    queryKey: queryKeys.shelf,
    queryFn: listShelf,
    staleTime: 30 * 1000,
  })
}

export function useShelfBook(url: string) {
  return useQuery({
    queryKey: queryKeys.shelfBook(url),
    queryFn: () => getShelfBook(url),
    enabled: !!url,
  })
}

export function useShelfStats() {
  return useQuery({
    queryKey: queryKeys.shelfStats,
    queryFn: getShelfStats,
    staleTime: 30 * 1000,
  })
}

export function useAddToShelf() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: addToShelf,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.shelf })
      void qc.invalidateQueries({ queryKey: queryKeys.shelfStats })
    },
  })
}

export function useUpdateShelfBook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ url, data }: { url: string; data: Parameters<typeof updateShelfBook>[1] }) =>
      updateShelfBook(url, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.shelf })
    },
  })
}

export function useRemoveFromShelf() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: removeFromShelf,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.shelf })
      void qc.invalidateQueries({ queryKey: queryKeys.shelfStats })
    },
  })
}

export function useCleanShelf() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: cleanShelf,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.shelf })
      void qc.invalidateQueries({ queryKey: queryKeys.shelfStats })
    },
  })
}

// === 下载 ===

export function useDownloads() {
  return useQuery({
    queryKey: queryKeys.downloads,
    queryFn: listDownloads,
    refetchInterval: 5000,
  })
}

export function useDownloadStatus(taskId: string | null) {
  return useQuery({
    queryKey: taskId ? queryKeys.download(taskId) : ['downloads', 'none'],
    queryFn: () => getDownloadStatus(taskId as string),
    enabled: !!taskId,
    refetchInterval: 3000,
  })
}

export function useStartDownload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: DownloadRequest) => startDownload(data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.downloads })
    },
  })
}

export function useCancelDownload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: cancelDownload,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.downloads })
    },
  })
}

// === 插件 ===

export function usePlugins() {
  return useQuery({
    queryKey: queryKeys.plugins,
    queryFn: listPlugins,
    staleTime: 60 * 1000,
  })
}

export function useInstallPlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: installPlugin,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.plugins })
    },
  })
}

export function useUninstallPlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: uninstallPlugin,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.plugins })
    },
  })
}
