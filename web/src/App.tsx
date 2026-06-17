import { useEffect, useRef, useState } from 'react'
import { Download, Settings, FileText, BookOpen } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { DownloadPanel } from './components/DownloadPanel'
import { ConfigPanel } from './components/ConfigPanel'
import { StatusBar } from './components/StatusBar'
import type { DownloadConfig, DownloadProgress, ProgressEvent } from '@/types'
import { startDownload, subscribeDownloadProgress } from '@/lib/api'

function App() {
  const [activeTab, setActiveTab] = useState<'download' | 'config'>('download')
  const [config, setConfig] = useState<DownloadConfig>({
    url: '',
    outputDir: './output',
    format: 'md',
    maxConcurrent: 3,
    rateLimit: 2,
    cleanContent: true,
    resume: false,
  })
  const [progress, setProgress] = useState<DownloadProgress>({
    total: 0,
    downloaded: 0,
    status: 'idle',
  })

  // 保存当前 SSE 订阅的取消函数，便于重新开始或卸载时释放连接
  const unsubscribeRef = useRef<(() => void) | null>(null)

  // 组件卸载时取消订阅，避免内存泄漏与僵尸连接
  useEffect(() => {
    return () => {
      unsubscribeRef.current?.()
      unsubscribeRef.current = null
    }
  }, [])

  const handleConfigChange = (newConfig: Partial<DownloadConfig>) => {
    setConfig(prev => ({ ...prev, ...newConfig }))
  }

  /**
   * 处理 SSE 进度事件，按事件类型更新本地进度状态
   * 使用函数式 setState 保证多次连续事件的状态一致性
   */
  const handleProgressEvent = (event: ProgressEvent): void => {
    switch (event.type) {
      case 'info':
        // info 事件主要用于提示性消息，更新 current 展示当前阶段
        if (event.message) {
          setProgress(prev => ({ ...prev, current: event.message }))
        }
        break
      case 'progress':
        setProgress({
          total: event.total,
          downloaded: event.downloaded,
          current: event.current,
          status: 'downloading',
        })
        break
      case 'export':
        setProgress(prev => ({
          ...prev,
          status: 'exporting',
          current: event.message,
        }))
        break
      case 'complete':
        setProgress(prev => ({
          ...prev,
          status: 'completed',
          downloaded: event.total || prev.downloaded,
          total: event.total || prev.total,
          current: event.message || prev.current,
          outputFiles: event.output_files,
        }))
        // 任务完成，主动取消订阅释放连接
        unsubscribeRef.current?.()
        unsubscribeRef.current = null
        break
      case 'error':
        setProgress(prev => ({
          ...prev,
          status: 'error',
          error: event.message,
        }))
        unsubscribeRef.current?.()
        unsubscribeRef.current = null
        break
      default:
        break
    }
  }

  const handleStartDownload = async (): Promise<void> => {
    if (!config.url) return

    // 重新开始前取消已有订阅，避免多个流并发写入状态
    unsubscribeRef.current?.()
    unsubscribeRef.current = null

    setProgress({
      total: 0,
      downloaded: 0,
      status: 'downloading',
    })

    try {
      const { task_id } = await startDownload(config)
      // 订阅 SSE 流，保存取消函数以便后续中断
      unsubscribeRef.current = subscribeDownloadProgress(
        task_id,
        handleProgressEvent,
        (err: Error) => {
          setProgress(prev => ({
            ...prev,
            status: 'error',
            error: err.message,
          }))
        },
      )
    } catch (err) {
      setProgress(prev => ({
        ...prev,
        status: 'error',
        error: err instanceof Error ? err.message : '启动下载失败',
      }))
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50 dark:from-slate-900 dark:via-slate-900 dark:to-indigo-950">
      <header className="glass sticky top-0 z-50 border-b border-border/50">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-primary/25">
                <BookOpen className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight">
                  <span className="gradient-text">知乎盐选小说下载器</span>
                </h1>
                <p className="text-xs text-muted-foreground">
                  异步并发下载 · 多格式导出 · 断点续传
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant={activeTab === 'download' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setActiveTab('download')}
              >
                <Download className="w-4 h-4 mr-2" />
                下载
              </Button>
              <Button
                variant={activeTab === 'config' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setActiveTab('config')}
              >
                <Settings className="w-4 h-4 mr-2" />
                设置
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            {activeTab === 'download' ? (
              <DownloadPanel
                config={config}
                progress={progress}
                onConfigChange={handleConfigChange}
                onStart={handleStartDownload}
              />
            ) : (
              <ConfigPanel
                config={config}
                onConfigChange={handleConfigChange}
              />
            )}
          </div>

          <div className="space-y-6">
            <Card className="gradient-border">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-primary" />
                  快速上手
                </CardTitle>
                <CardDescription>三步完成小说下载</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-sm font-bold text-primary">1</span>
                  </div>
                  <div>
                    <h4 className="font-medium">获取Cookie</h4>
                    <p className="text-sm text-muted-foreground">
                      使用浏览器插件导出知乎Cookie
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-sm font-bold text-primary">2</span>
                  </div>
                  <div>
                    <h4 className="font-medium">粘贴链接</h4>
                    <p className="text-sm text-muted-foreground">
                      复制盐选小说页面URL
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-sm font-bold text-primary">3</span>
                  </div>
                  <div>
                    <h4 className="font-medium">开始下载</h4>
                    <p className="text-sm text-muted-foreground">
                      选择格式后一键下载
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">支持格式</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { name: 'Markdown', ext: '.md', icon: '📝' },
                    { name: 'EPUB', ext: '.epub', icon: '📖' },
                    { name: '文本', ext: '.txt', icon: '📄' },
                  ].map(format => (
                    <div
                      key={format.ext}
                      className="flex flex-col items-center p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <span className="text-2xl mb-1">{format.icon}</span>
                      <span className="text-sm font-medium">{format.name}</span>
                      <span className="text-xs text-muted-foreground">{format.ext}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>

      <StatusBar progress={progress} />
    </div>
  )
}

export default App
