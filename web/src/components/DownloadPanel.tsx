import { useState } from 'react'
import { Link, Upload, Play, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { DownloadConfig, DownloadProgress } from '@/types'

interface DownloadPanelProps {
  config: DownloadConfig
  progress: DownloadProgress
  onConfigChange: (config: Partial<DownloadConfig>) => void
  onStart: () => void
}

export function DownloadPanel({ config, progress, onConfigChange, onStart }: DownloadPanelProps) {
  const [cookieInput, setCookieInput] = useState('')

  const handleCookieUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onload = (event) => {
        try {
          const content = event.target?.result as string
          onConfigChange({ cookieFile: content })
        } catch {
          console.error('Failed to read cookie file')
        }
      }
      reader.readAsText(file)
    }
  }

  const progressPercent = progress.total > 0 
    ? Math.round((progress.downloaded / progress.total) * 100) 
    : 0

  const isDownloading = progress.status === 'downloading' || progress.status === 'exporting'

  return (
    <Card className="shadow-lg">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Link className="w-5 h-5 text-primary" />
          输入小说链接
        </CardTitle>
        <CardDescription>
          粘贴知乎盐选小说页面的完整URL
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="url">小说URL</Label>
          <div className="flex gap-2">
            <Input
              id="url"
              placeholder="https://www.zhihu.com/market/..."
              value={config.url}
              onChange={(e) => onConfigChange({ url: e.target.value })}
              className="flex-1"
            />
            <Button onClick={onStart} disabled={!config.url || isDownloading}>
              {isDownloading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <Play className="w-4 h-4 mr-2" />
                  开始
                </>
              )}
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="cookie">Cookie认证（可选）</Label>
          <div className="flex gap-2">
            <Input
              id="cookie"
              type="file"
              accept=".json"
              onChange={handleCookieUpload}
              className="flex-1"
            />
            <Button variant="outline" asChild>
              <label>
                <Upload className="w-4 h-4 mr-2" />
                上传
                <input
                  type="file"
                  accept=".json"
                  onChange={handleCookieUpload}
                  className="hidden"
                />
              </label>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            上传包含z_c0的Cookie JSON文件，用于访问付费内容
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>导出格式</Label>
            <Select
              value={config.format}
              onValueChange={(value) => onConfigChange({ format: value as DownloadConfig['format'] })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="md">Markdown (.md)</SelectItem>
                <SelectItem value="epub">EPUB (.epub)</SelectItem>
                <SelectItem value="txt">文本 (.txt)</SelectItem>
                <SelectItem value="all">全部格式</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>输出目录</Label>
            <Input
              value={config.outputDir}
              onChange={(e) => onConfigChange({ outputDir: e.target.value })}
              placeholder="./output"
            />
          </div>
        </div>

        {progress.status !== 'idle' && (
          <div className="space-y-3 p-4 rounded-lg bg-muted/50">
            <div className="flex justify-between text-sm">
              <span className="font-medium">
                {progress.status === 'downloading' && '正在下载...'}
                {progress.status === 'exporting' && '正在导出...'}
                {progress.status === 'completed' && '下载完成'}
                {progress.status === 'error' && '下载失败'}
              </span>
              <span className="text-muted-foreground">
                {progress.downloaded} / {progress.total}
              </span>
            </div>
            <Progress value={progressPercent} className="h-2" />
            {progress.current && (
              <p className="text-xs text-muted-foreground truncate">
                当前: {progress.current}
              </p>
            )}
            {progress.error && (
              <p className="text-xs text-destructive">{progress.error}</p>
            )}
          </div>
        )}

        <div className="flex items-center justify-between p-4 rounded-lg border">
          <div className="space-y-0.5">
            <Label htmlFor="clean">内容清洗</Label>
            <p className="text-sm text-muted-foreground">
              移除广告、水印和推广语
            </p>
          </div>
          <Switch
            id="clean"
            checked={config.cleanContent}
            onCheckedChange={(checked) => onConfigChange({ cleanContent: checked })}
          />
        </div>

        <div className="flex items-center justify-between p-4 rounded-lg border">
          <div className="space-y-0.5">
            <Label htmlFor="resume">断点续传</Label>
            <p className="text-sm text-muted-foreground">
              中断后可继续下载
            </p>
          </div>
          <Switch
            id="resume"
            checked={config.resume}
            onCheckedChange={(checked) => onConfigChange({ resume: checked })}
          />
        </div>
      </CardContent>
    </Card>
  )
}
