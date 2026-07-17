import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useAppStore } from '@/store/appStore'
import { startDownload, subscribeDownloadProgress } from '@/lib/api'
import type { ProgressEvent } from '@/types'

export function DownloadPage() {
  const { t } = useTranslation()
  const { config, updateConfig, progress, setProgress, addTask } = useAppStore()
  const unsubscribeRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    return () => {
      unsubscribeRef.current?.()
      unsubscribeRef.current = null
    }
  }, [])

  const handleConfigChange = (key: keyof typeof config, value: unknown) => {
    updateConfig({ [key]: value })
  }

  const handleProgressEvent = (event: ProgressEvent): void => {
    switch (event.type) {
      case 'info':
        setProgress({ current: event.message })
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
        setProgress({ status: 'exporting', current: event.message })
        break
      case 'complete':
        setProgress({
          status: 'completed',
          downloaded: event.total || progress.downloaded,
          total: event.total || progress.total,
          current: event.message || progress.current,
          outputFiles: event.output_files,
        })
        addTask({
          id: Date.now().toString(),
          url: config.url,
          title: event.book_title || '未知书籍',
          status: 'completed',
          progress: 100,
          total: event.total,
          downloaded: event.total,
          outputFiles: event.output_files,
          createdAt: new Date().toISOString(),
        })
        unsubscribeRef.current?.()
        unsubscribeRef.current = null
        break
      case 'error':
        setProgress({ status: 'error', error: event.message })
        addTask({
          id: Date.now().toString(),
          url: config.url,
          title: event.book_title || '未知书籍',
          status: 'error',
          progress: 0,
          total: 0,
          downloaded: 0,
          error: event.message,
          createdAt: new Date().toISOString(),
        })
        unsubscribeRef.current?.()
        unsubscribeRef.current = null
        break
      default:
        break
    }
  }

  const handleStartDownload = async (): Promise<void> => {
    if (!config.url) return

    unsubscribeRef.current?.()
    unsubscribeRef.current = null

    setProgress({
      total: 0,
      downloaded: 0,
      status: 'downloading',
    })

    try {
      const { task_id } = await startDownload(config)
      unsubscribeRef.current = subscribeDownloadProgress(
        task_id,
        handleProgressEvent,
        (err: Error) => {
          setProgress({ status: 'error', error: err.message })
        },
      )
    } catch (err) {
      setProgress({ status: 'error', error: err instanceof Error ? err.message : '启动下载失败' })
    }
  }

  const percentage = progress.total > 0 ? Math.round((progress.downloaded / progress.total) * 100) : 0

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold">{t('nav.download')}</h1>
        <p className="text-muted-foreground mt-1">{t('download.urlPlaceholder')}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="w-5 h-5 text-primary" />
            {t('download.downloadProgress')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="url">{t('download.url')}</Label>
            <Input
              id="url"
              value={config.url}
              onChange={(e) => handleConfigChange('url', e.target.value)}
              placeholder={t('download.urlPlaceholder')}
              className="text-lg"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="outputDir">{t('download.outputDir')}</Label>
              <Input
                id="outputDir"
                value={config.outputDir}
                onChange={(e) => handleConfigChange('outputDir', e.target.value)}
                placeholder="./output"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="format">{t('download.format')}</Label>
              <Select
                value={config.format}
                onValueChange={(value) => handleConfigChange('format', value)}
              >
                <SelectTrigger id="format">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="md">Markdown (.md)</SelectItem>
                  <SelectItem value="txt">文本 (.txt)</SelectItem>
                  <SelectItem value="epub">EPUB (.epub)</SelectItem>
                  <SelectItem value="mobi">MOBI (.mobi)</SelectItem>
                  <SelectItem value="all">全部格式</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="maxConcurrent">{t('download.maxConcurrent')}</Label>
              <Input
                id="maxConcurrent"
                type="number"
                value={config.maxConcurrent}
                onChange={(e) => handleConfigChange('maxConcurrent', parseInt(e.target.value) || 3)}
                min={1}
                max={10}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rateLimit">{t('download.rateLimit')}</Label>
              <Input
                id="rateLimit"
                type="number"
                value={config.rateLimit}
                onChange={(e) => handleConfigChange('rateLimit', parseFloat(e.target.value) || 2)}
                min={0}
                step={0.5}
              />
            </div>
          </div>

          <div className="flex items-center justify-between py-2">
            <Label htmlFor="cleanContent">{t('download.cleanContent')}</Label>
            <Switch
              id="cleanContent"
              checked={config.cleanContent}
              onCheckedChange={(checked) => handleConfigChange('cleanContent', checked)}
            />
          </div>

          <div className="flex items-center justify-between py-2">
            <Label htmlFor="resume">{t('download.resume')}</Label>
            <Switch
              id="resume"
              checked={config.resume}
              onCheckedChange={(checked) => handleConfigChange('resume', checked)}
            />
          </div>

          <Button
            onClick={handleStartDownload}
            disabled={!config.url || progress.status === 'downloading' || progress.status === 'exporting'}
            className="w-full"
            size="lg"
          >
            {progress.status === 'downloading' || progress.status === 'exporting' ? (
              <>
                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                {t('common.loading')}
              </>
            ) : (
              <>
                <Download className="w-5 h-5 mr-2" />
                {t('download.startDownload')}
              </>
            )}
          </Button>

          {progress.status !== 'idle' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{progress.current || t('common.status')}</span>
                <span>{percentage}%</span>
              </div>
              <Progress value={percentage} className="h-2" />
              {progress.status === 'error' && (
                <p className="text-sm text-destructive">{progress.error}</p>
              )}
              {progress.status === 'completed' && progress.outputFiles && (
                <div className="mt-4 p-4 bg-success/10 rounded-lg">
                  <p className="text-sm font-medium text-success-foreground mb-2">{t('common.success')}</p>
                  <ul className="text-xs text-muted-foreground space-y-1">
                    {progress.outputFiles.map((file, i) => (
                      <li key={i}>{file}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}