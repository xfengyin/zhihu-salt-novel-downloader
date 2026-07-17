/**
 * 应用入口
 *
 * 集成：
 * - ErrorBoundary 全局错误捕获
 * - QueryClientProvider 服务端状态管理
 * - BrowserRouter 路由
 * - Toaster 消息通知
 * - Suspense 异步加载
 */

import { Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'

import { queryClient } from '@/lib/queryClient'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Layout } from '@/components/Layout'
import { Toaster } from '@/components/ui/toaster'
import { HomePage } from '@/pages/HomePage'
import { DownloadPage } from '@/pages/DownloadPage'
import { LibraryPage } from '@/pages/LibraryPage'
import { TasksPage } from '@/pages/TasksPage'
import { SettingsPage } from '@/pages/SettingsPage'

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Layout>
            <Suspense fallback={<div className="p-8 text-center text-muted-foreground">Loading…</div>}>
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/download" element={<DownloadPage />} />
                <Route path="/library" element={<LibraryPage />} />
                <Route path="/tasks" element={<TasksPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<HomePage />} />
              </Routes>
            </Suspense>
          </Layout>
          <Toaster />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
