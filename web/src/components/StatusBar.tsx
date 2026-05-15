import { Wifi, WifiOff, HardDrive, Clock } from 'lucide-react'
import type { DownloadProgress } from '@/types'

interface StatusBarProps {
  progress: DownloadProgress
}

export function StatusBar({ progress }: StatusBarProps) {
  const getStatusColor = () => {
    switch (progress.status) {
      case 'downloading':
        return 'text-blue-500'
      case 'exporting':
        return 'text-purple-500'
      case 'completed':
        return 'text-green-500'
      case 'error':
        return 'text-red-500'
      default:
        return 'text-muted-foreground'
    }
  }

  return (
    <footer className="fixed bottom-0 left-0 right-0 glass border-t border-border/50">
      <div className="container mx-auto px-4 py-2">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              {progress.status === 'idle' || progress.status === 'completed' ? (
                <>
                  <Wifi className="w-3.5 h-3.5 text-green-500" />
                  <span className="text-green-500">就绪</span>
                </>
              ) : progress.status === 'error' ? (
                <>
                  <WifiOff className="w-3.5 h-3.5 text-red-500" />
                  <span className="text-red-500">错误</span>
                </>
              ) : (
                <>
                  <Wifi className="w-3.5 h-3.5 text-blue-500 animate-pulse" />
                  <span className={getStatusColor()}>
                    {progress.status === 'downloading' && '下载中'}
                    {progress.status === 'exporting' && '导出中'}
                  </span>
                </>
              )}
            </div>

            {progress.total > 0 && (
              <div className="flex items-center gap-1.5">
                <HardDrive className="w-3.5 h-3.5" />
                <span>
                  {progress.downloaded} / {progress.total} 章节
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-4">
            <span className="text-muted-foreground">
              v2.0.0
            </span>
            <div className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              <span className="text-muted-foreground">
                {new Date().toLocaleTimeString('zh-CN')}
              </span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  )
}
