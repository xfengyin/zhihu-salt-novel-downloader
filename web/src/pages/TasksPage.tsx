/**
 * 任务中心页面
 *
 * - 显示所有下载任务
 * - 实时刷新、自动轮询
 * - 取消、重试操作
 */

import { useTranslation } from 'react-i18next'
import { Clock, Loader2, CheckCircle2, AlertCircle, XCircle, Square, RotateCw, RefreshCw, Copy } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useCancelDownload, useDownloads } from '@/hooks/queries'
import { extractErrorMessage } from '@/api/client'
import { toast } from '@/components/ui/toaster'
import { formatDate, formatRelativeTime } from '@/lib/utils'
import type { TaskStatus, DownloadTask } from '@/api/download'

function StatusBadge({ status }: { status: TaskStatus }) {
  const config: Record<TaskStatus, { icon: React.ReactNode; className: string; label: string }> = {
    pending: {
      icon: <Clock className="h-3 w-3" />,
      className: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
      label: 'tasks.status.pending',
    },
    running: {
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
      label: 'tasks.status.running',
    },
    completed: {
      icon: <CheckCircle2 className="h-3 w-3" />,
      className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
      label: 'tasks.status.completed',
    },
    failed: {
      icon: <AlertCircle className="h-3 w-3" />,
      className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
      label: 'tasks.status.failed',
    },
    cancelled: {
      icon: <XCircle className="h-3 w-3" />,
      className: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
      label: 'tasks.status.cancelled',
    },
  }
  const item = config[status]
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full ${item.className}`}>
      {item.icon}
      {item.label}
    </span>
  )
}

export function TasksPage() {
  const { t } = useTranslation()
  const { data: tasks = [], isLoading, refetch, isRefetching } = useDownloads()
  const cancelMutation = useCancelDownload()

  const handleCancel = async (task: DownloadTask) => {
    try {
      await cancelMutation.mutateAsync(task.task_id)
      toast.info(t('common.success'), { description: '任务已取消' })
    } catch (error) {
      toast.error(t('common.error'), { description: extractErrorMessage(error) })
    }
  }

  const handleCopyId = async (taskId: string) => {
    await navigator.clipboard.writeText(taskId)
    toast.success(t('common.copied'))
  }

  const stats = {
    total: tasks.length,
    running: tasks.filter((t) => t.status === 'running').length,
    completed: tasks.filter((t) => t.status === 'completed').length,
    failed: tasks.filter((t) => t.status === 'failed').length,
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('tasks.title')}</h1>
          <p className="text-muted-foreground mt-1">
            {t('tasks.total')}: {stats.total}
          </p>
        </div>
        <Button variant="outline" onClick={() => refetch()} disabled={isRefetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isRefetching ? 'animate-spin' : ''}`} />
          {t('tasks.refresh')}
        </Button>
      </div>

      {/* 统计 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('tasks.total')}</CardDescription>
            <CardTitle className="text-2xl">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('tasks.status.running')}</CardDescription>
            <CardTitle className="text-2xl text-blue-600">{stats.running}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('tasks.status.completed')}</CardDescription>
            <CardTitle className="text-2xl text-green-600">{stats.completed}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('tasks.status.failed')}</CardDescription>
            <CardTitle className="text-2xl text-red-600">{stats.failed}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* 任务列表 */}
      {isLoading ? (
        <div className="text-center py-12 text-muted-foreground">{t('common.loading')}</div>
      ) : tasks.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <div className="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mx-auto mb-4">
              <Clock className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-xl font-semibold mb-2">{t('tasks.empty')}</h3>
            <p className="text-muted-foreground">前往下载页面创建任务</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <Card key={task.task_id}>
              <CardContent className="p-4">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <StatusBadge status={task.status} />
                      <code className="text-xs text-muted-foreground font-mono truncate">
                        {task.task_id}
                      </code>
                    </div>
                    <div className="text-sm text-muted-foreground flex items-center gap-3 flex-wrap">
                      <span>{t('tasks.startTime')}: {formatRelativeTime(task.created_at)}</span>
                      <span className="text-xs">·</span>
                      <span title={formatDate(task.created_at)}>{formatDate(task.created_at, 'en-US')}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => void handleCopyId(task.task_id)}
                      title="复制任务ID"
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                    {task.status === 'running' || task.status === 'pending' ? (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => void handleCancel(task)}
                        disabled={cancelMutation.isPending}
                      >
                        <Square className="mr-1 h-3 w-3" />
                        {t('tasks.cancel')}
                      </Button>
                    ) : task.status === 'failed' ? (
                      <Button variant="outline" size="sm">
                        <RotateCw className="mr-1 h-3 w-3" />
                        {t('tasks.retry')}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
