/**
 * 下载页面
 *
 * - 输入 URL（支持批量）
 * - 配置下载参数（并发、限速、格式）
 * - 实时显示进度（SSE）
 * - 任务管理（取消、查看 traceId）
 */

import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Download,
  FolderOpen,
  Loader2,
  Play,
  Square,
  Upload,
  X,
  CheckCircle2,
  AlertCircle,
  Clock,
  Hash,
  Copy,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import { useAppStore } from '@/store/appStore'
import { useTauriApi } from '@/lib/tauri'
import { useDownloadProgress } from '@/hooks/useDownloadProgress'
import { useCancelDownload, useStartDownload } from '@/hooks/queries'
import { extractErrorMessage } from '@/api/client'
import { toast } from '@/components/ui/toaster'

import type { ExportFormat } from '@/types'

const EXPORT_FORMATS: { value: ExportFormat; label: string }[] = [
  { value: 'epub', label: 'EPUB (.epub)' },
  { value: 'mobi', label: 'MOBI (.mobi)' },
  { value: 'md', label: 'Markdown (.md)' },
  { value: 'txt', label: 'Text (.txt)' },
]

export function DownloadPage() {
  const { t } = useTranslation()
  const settings = useAppStore((s) => s.settings)
  const updateSettings = useAppStore((s) => s.updateSettings)
  const activeTaskId = useAppStore((s) => s.activeTaskId)
  const setActiveTask = useAppStore((s) => s.setActiveTask)
  const tauriApi = useTauriApi()

  const [urlsText, setUrlsText] = useState('')
  const [cookieFile, setCookieFile] = useState<string | null>(null)
  const [localMaxConcurrent, setLocalMaxConcurrent] = useState(settings.maxConcurrent)
  const [localRateLimit, setLocalRateLimit] = useState(settings.rateLimit)
  const [format, setFormat] = useState<ExportFormat>(settings.exportFormat)
  const [cleanContent, setCleanContent] = useState(true)
  const [resume, setResume] = useState(false)
  const [updateCheck, setUpdateCheck] = useState(false)
  const [listOnly, setListOnly] = useState(false)

  const startMutation = useStartDownload()
  const cancelMutation = useCancelDownload()
  const { lastEvent, events } = useDownloadProgress(activeTaskId)

  // 派生状态
  const urls = useMemo(
    () => urlsText.split('\n').map((u) => u.trim()).filter((u) => u.length > 0),
    [urlsText],
  )

  const status = useMemo(() => {
    if (!activeTaskId) return 'idle'
    if (lastEvent?.type === 'complete') return 'completed'
    if (lastEvent?.type === 'error') return 'failed'
    if (lastEvent?.type === 'progress' || lastEvent?.type === 'export') return 'running'
    return 'pending'
  }, [activeTaskId, lastEvent])

  const progress = useMemo(() => {
    if (lastEvent?.type === 'progress' && lastEvent.total && lastEvent.total > 0) {
      return Math.round(((lastEvent.current ?? 0) / lastEvent.total) * 100)
    }
    if (lastEvent?.type === 'complete') return 100
    return 0
  }, [lastEvent])

  useEffect(() => {
    // 任务完成时清空 active task
    if (status === 'completed' || status === 'failed') {
      const timer = setTimeout(() => {
        setActiveTask(null)
      }, 5000)
      return () => clearTimeout(timer)
    }
  }, [status, setActiveTask])

  const handleSelectCookie = async () => {
    const path = await tauriApi.selectFile([
      { name: 'Cookie 文件', extensions: ['txt', 'json'] },
    ])
    if (path) {
      setCookieFile(path)
      toast.success(t('common.success'), { description: path })
    }
  }

  const handleSelectOutputDir = async () => {
    const dir = await tauriApi.selectDirectory()
    if (dir) {
      updateSettings({ downloadDir: dir })
    }
  }

  const handleStart = async () => {
    if (urls.length === 0) {
      toast.error(t('common.error'), { description: '请输入至少一个 URL' })
      return
    }

    try {
      const result = await startMutation.mutateAsync({
        batch_urls: urls.length > 1 ? urls : undefined,
        url: urls.length === 1 ? urls[0] : undefined,
        max_concurrent: localMaxConcurrent,
        rate_limit: localRateLimit,
        output_dir: settings.downloadDir || undefined,
        export_format: format,
        list_only: listOnly,
        clean_content: cleanContent,
        resume,
        update_check: updateCheck,
        cookie_file: cookieFile ?? undefined,
      })
      setActiveTask(result.task_id)
      toast.success(t('common.success'), {
        description: `任务已创建: ${result.task_id}`,
      })
      await tauriApi.notify('下载任务已创建', `追踪 ID: ${result.trace_id}`)
    } catch (error) {
      toast.error(t('common.error'), { description: extractErrorMessage(error) })
    }
  }

  const handleCancel = async () => {
    if (!activeTaskId) return
    try {
      await cancelMutation.mutateAsync(activeTaskId)
      toast.info(t('common.success'), { description: '任务已取消' })
      setActiveTask(null)
    } catch (error) {
      toast.error(t('common.error'), { description: extractErrorMessage(error) })
    }
  }

  const handleCopyTraceId = async () => {
    if (lastEvent?.data?.trace_id) {
      const id = String(lastEvent.data.trace_id)
      await navigator.clipboard.writeText(id)
      toast.success(t('common.copied'))
    }
  }

  const isRunning = status === 'running' || status === 'pending'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{t('download.title')}</h1>
        <p className="text-muted-foreground mt-1">{t('download.urlPlaceholder')}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-5 w-5 text-primary" />
            {t('download.title')}
          </CardTitle>
          <CardDescription>{t('download.urlPlaceholder')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="urls">{t('download.url')}</Label>
            <Textarea
              id="urls"
              value={urlsText}
              onChange={(e) => setUrlsText(e.target.value)}
              placeholder={t('download.urlPlaceholder')}
              rows={4}
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              已输入 {urls.length} 个 URL
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="outputDir">{t('download.outputDir')}</Label>
              <div className="flex gap-2">
                <Input
                  id="outputDir"
                  value={settings.downloadDir}
                  onChange={(e) => updateSettings({ downloadDir: e.target.value })}
                  placeholder="留空使用默认目录"
                />
                {tauriApi.isTauri && (
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={handleSelectOutputDir}
                    title="选择目录"
                  >
                    <FolderOpen className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="format">{t('download.format')}</Label>
              <Select value={format} onValueChange={(v) => setFormat(v as ExportFormat)}>
                <SelectTrigger id="format">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPORT_FORMATS.map((f) => (
                    <SelectItem key={f.value} value={f.value}>
                      {f.label}
                    </SelectItem>
                  ))}
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
                value={localMaxConcurrent}
                onChange={(e) => setLocalMaxConcurrent(parseInt(e.target.value, 10) || 1)}
                min={1}
                max={20}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rateLimit">{t('download.rateLimit')}</Label>
              <Input
                id="rateLimit"
                type="number"
                value={localRateLimit}
                onChange={(e) => setLocalRateLimit(parseFloat(e.target.value) || 0)}
                min={0}
                step={0.5}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="cookieFile">{t('download.cookieFile')}</Label>
            <div className="flex gap-2">
              <Input
                id="cookieFile"
                value={cookieFile ?? ''}
                readOnly
                placeholder="未选择（可选）"
                className="font-mono text-xs"
              />
              {tauriApi.isTauri && (
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={handleSelectCookie}
                  title={t('download.uploadCookie')}
                >
                  <Upload className="h-4 w-4" />
                </Button>
              )}
              {cookieFile && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setCookieFile(null)}
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="cleanContent" className="cursor-pointer">
                {t('download.cleanContent')}
              </Label>
              <Switch id="cleanContent" checked={cleanContent} onCheckedChange={setCleanContent} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="resume" className="cursor-pointer">
                {t('download.resume')}
              </Label>
              <Switch id="resume" checked={resume} onCheckedChange={setResume} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="updateCheck" className="cursor-pointer">
                {t('download.updateCheck')}
              </Label>
              <Switch id="updateCheck" checked={updateCheck} onCheckedChange={setUpdateCheck} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="listOnly" className="cursor-pointer">
                {t('download.listOnly')}
              </Label>
              <Switch id="listOnly" checked={listOnly} onCheckedChange={setListOnly} />
            </div>
          </div>

          <div className="flex gap-3">
            <Button
              onClick={handleStart}
              disabled={urls.length === 0 || isRunning || startMutation.isPending}
              className="flex-1"
              size="lg"
            >
              {startMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t('common.loading')}
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  {t('download.startDownload')}
                </>
              )}
            </Button>

            {activeTaskId && isRunning && (
              <Button onClick={handleCancel} variant="destructive" size="lg">
                <Square className="mr-2 h-4 w-4" />
                {t('download.cancel')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* 实时进度 */}
      {activeTaskId && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                {status === 'completed' && <CheckCircle2 className="h-5 w-5 text-green-500" />}
                {status === 'failed' && <AlertCircle className="h-5 w-5 text-red-500" />}
                {status === 'running' && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
                {status === 'pending' && <Clock className="h-5 w-5 text-muted-foreground" />}
                {t('download.downloadProgress')}
              </span>
              <span className="text-sm font-normal text-muted-foreground">
                {t(`download.${status}`)}
              </span>
            </CardTitle>
            <CardDescription className="flex items-center gap-2 font-mono text-xs">
              <Hash className="h-3 w-3" />
              {activeTaskId}
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={handleCopyTraceId}
                title={t('download.copyTraceId')}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-muted-foreground">
                  {lastEvent?.message ?? t('common.loading')}
                </span>
                <span className="font-medium">{progress}%</span>
              </div>
              <Progress value={progress} className="h-2" />
            </div>

            {/* 事件日志 */}
            {events.length > 0 && (
              <div className="mt-4 max-h-60 overflow-y-auto rounded-lg bg-muted/50 p-3 text-xs font-mono space-y-1">
                {events.slice(-20).map((evt, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="text-muted-foreground shrink-0">
                      {new Date(evt.timestamp ?? Date.now()).toLocaleTimeString()}
                    </span>
                    <span
                      className={
                        evt.type === 'error'
                          ? 'text-red-500'
                          : evt.type === 'complete'
                            ? 'text-green-500'
                            : 'text-foreground'
                      }
                    >
                      [{evt.type}] {evt.message ?? ''}
                      {evt.current !== undefined && evt.total !== undefined
                        ? ` (${evt.current}/${evt.total})`
                        : ''}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
