import { useTranslation } from 'react-i18next'
import { Clock, RefreshCw, X, CheckCircle, AlertCircle, Loader2, FileText } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { useAppStore } from '@/store/appStore'

export function TasksPage() {
  const { t } = useTranslation()
  const { tasks, removeTask, addTask } = useAppStore()

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-500" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-destructive" />
      case 'downloading':
      case 'exporting':
        return <Loader2 className="w-5 h-5 text-primary animate-spin" />
      default:
        return <Clock className="w-5 h-5 text-muted-foreground" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-green-500'
      case 'error':
        return 'text-destructive'
      case 'downloading':
      case 'exporting':
        return 'text-primary'
      default:
        return 'text-muted-foreground'
    }
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString()
  }

  const handleRetry = (task: typeof tasks[0]) => {
    addTask({
      ...task,
      id: Date.now().toString(),
      status: 'pending',
      progress: 0,
      createdAt: new Date().toISOString(),
    })
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold">{t('tasks.title')}</h1>
        <p className="text-muted-foreground mt-1">{t('common.name')}: {tasks.length}</p>
      </div>

      {tasks.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <div className="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mx-auto mb-4">
              <Clock className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-xl font-semibold mb-2">{t('tasks.empty')}</h3>
            <p className="text-muted-foreground">{t('download.startDownload')}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {tasks.map(task => (
            <Card key={task.id} className="overflow-hidden">
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    {getStatusIcon(task.status)}
                    <div>
                      <CardTitle className="text-base">{task.title}</CardTitle>
                      <p className="text-sm text-muted-foreground">{task.url}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {task.status === 'error' && (
                      <Button variant="ghost" size="sm" onClick={() => handleRetry(task)}>
                        <RefreshCw className="w-4 h-4 mr-1" />
                        {t('tasks.retry')}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => removeTask(task.id)}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0 space-y-3">
                <div className="flex items-center justify-between text-sm">
                  <span className={`font-medium ${getStatusColor(task.status)}`}>
                    {t(`tasks.status.${task.status}`)}
                  </span>
                  <span className="text-muted-foreground">{formatDate(task.createdAt)}</span>
                </div>

                {(task.status === 'downloading' || task.status === 'exporting') && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">{t('tasks.progress')}</span>
                      <span>{task.progress}%</span>
                    </div>
                    <Progress value={task.progress} className="h-2" />
                  </div>
                )}

                {task.error && (
                  <p className="text-sm text-destructive">{task.error}</p>
                )}

                {task.outputFiles && task.outputFiles.length > 0 && (
                  <div className="pt-2 border-t border-border">
                    <p className="text-xs font-medium text-muted-foreground mb-2">
                      {t('download.downloadProgress')}
                    </p>
                    <div className="space-y-1">
                      {task.outputFiles.map((file: string, i: number) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                          <FileText className="w-3 h-3" />
                          {file}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}