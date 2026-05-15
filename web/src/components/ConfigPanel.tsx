import { Settings2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import type { DownloadConfig } from '@/types'

interface ConfigPanelProps {
  config: DownloadConfig
  onConfigChange: (config: Partial<DownloadConfig>) => void
}

export function ConfigPanel({ config, onConfigChange }: ConfigPanelProps) {
  return (
    <Card className="shadow-lg">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings2 className="w-5 h-5 text-primary" />
          下载设置
        </CardTitle>
        <CardDescription>
          调整下载参数以优化性能和稳定性
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-2">
            <Label htmlFor="concurrent">最大并发数</Label>
            <Input
              id="concurrent"
              type="number"
              min={1}
              max={10}
              value={config.maxConcurrent}
              onChange={(e) => onConfigChange({ maxConcurrent: parseInt(e.target.value) || 3 })}
            />
            <p className="text-xs text-muted-foreground">
              同时下载的章节数量，建议不超过5
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="rate">速率限制 (请求/秒)</Label>
            <Input
              id="rate"
              type="number"
              min={0.5}
              max={10}
              step={0.5}
              value={config.rateLimit}
              onChange={(e) => onConfigChange({ rateLimit: parseFloat(e.target.value) || 2 })}
            />
            <p className="text-xs text-muted-foreground">
              每秒请求数，数值越小越稳定
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <h3 className="text-sm font-medium">高级配置</h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="timeout">请求超时 (秒)</Label>
              <Input
                id="timeout"
                type="number"
                min={10}
                max={120}
                defaultValue={30}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="retry">最大重试次数</Label>
              <Input
                id="retry"
                type="number"
                min={1}
                max={10}
                defaultValue={3}
              />
            </div>
          </div>
        </div>

        <div className="p-4 rounded-lg bg-muted/50 border border-border/50">
          <h4 className="font-medium mb-2">配置说明</h4>
          <ul className="text-sm text-muted-foreground space-y-1">
            <li>• <strong>最大并发数</strong>：同时下载的章节数量，增加可提高速度但可能触发反爬</li>
            <li>• <strong>速率限制</strong>：控制请求频率，数值越小被封禁概率越低</li>
            <li>• <strong>断点续传</strong>：中断后可从上次位置继续，无需重新下载</li>
            <li>• <strong>内容清洗</strong>：移除页面广告、水印和推广信息</li>
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}
