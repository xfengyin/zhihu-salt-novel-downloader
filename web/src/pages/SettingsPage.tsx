/**
 * 设置页面
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Settings as SettingsIcon, FolderOpen, RotateCcw, Save, Info } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { useAppStore } from '@/store/appStore'
import { useTauriApi } from '@/lib/tauri'
import { toast } from '@/components/ui/toaster'

import type { ExportFormat } from '@/types'

export function SettingsPage() {
  const { t, i18n } = useTranslation()
  const settings = useAppStore((s) => s.settings)
  const updateSettings = useAppStore((s) => s.updateSettings)
  const resetSettings = useAppStore((s) => s.resetSettings)
  const tauriApi = useTauriApi()

  const [localSettings, setLocalSettings] = useState(settings)

  const handleSave = () => {
    updateSettings(localSettings)
    void i18n.changeLanguage(localSettings.language)
    toast.success(t('settings.saved'))
  }

  const handleReset = () => {
    resetSettings()
    setLocalSettings({
      theme: 'system',
      language: 'zh-CN',
      downloadDir: '',
      maxConcurrent: 3,
      rateLimit: 5,
      exportFormat: 'epub',
      enableTelemetry: true,
      enableNotifications: true,
      autoStartDownload: false,
      proxyEnabled: false,
      proxyUrl: '',
      apiBaseUrl: '',
    })
    void i18n.changeLanguage('zh-CN')
    toast.info(t('settings.reset'))
  }

  const handleSelectDir = async () => {
    const dir = await tauriApi.selectDirectory()
    if (dir) {
      setLocalSettings((s) => ({ ...s, downloadDir: dir }))
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{t('settings.title')}</h1>
        <p className="text-muted-foreground mt-1">个性化你的下载体验</p>
      </div>

      {/* 外观 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SettingsIcon className="h-5 w-5" />
            {t('settings.appearance')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>{t('settings.theme')}</Label>
              <Select
                value={localSettings.theme}
                onValueChange={(v) =>
                  setLocalSettings((s) => ({ ...s, theme: v as 'light' | 'dark' | 'system' }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="light">{t('settings.light')}</SelectItem>
                  <SelectItem value="dark">{t('settings.dark')}</SelectItem>
                  <SelectItem value="system">{t('settings.system')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>{t('settings.language')}</Label>
              <Select
                value={localSettings.language}
                onValueChange={(v) =>
                  setLocalSettings((s) => ({ ...s, language: v as 'zh-CN' | 'en-US' }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zh-CN">中文</SelectItem>
                  <SelectItem value="en-US">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 下载设置 */}
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.downloads')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>{t('settings.defaultOutputDir')}</Label>
            <div className="flex gap-2">
              <Input
                value={localSettings.downloadDir}
                onChange={(e) => setLocalSettings((s) => ({ ...s, downloadDir: e.target.value }))}
                placeholder="./output"
              />
              {tauriApi.isTauri && (
                <Button variant="outline" size="icon" onClick={handleSelectDir}>
                  <FolderOpen className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>{t('settings.defaultFormat')}</Label>
              <Select
                value={localSettings.exportFormat}
                onValueChange={(v) =>
                  setLocalSettings((s) => ({ ...s, exportFormat: v as ExportFormat }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="epub">EPUB</SelectItem>
                  <SelectItem value="mobi">MOBI</SelectItem>
                  <SelectItem value="md">Markdown</SelectItem>
                  <SelectItem value="txt">Text</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>{t('settings.maxConcurrent')}</Label>
              <Input
                type="number"
                min={1}
                max={20}
                value={localSettings.maxConcurrent}
                onChange={(e) =>
                  setLocalSettings((s) => ({ ...s, maxConcurrent: parseInt(e.target.value, 10) || 1 }))
                }
              />
            </div>

            <div className="space-y-2">
              <Label>{t('settings.rateLimit')}</Label>
              <Input
                type="number"
                min={0}
                step={0.5}
                value={localSettings.rateLimit}
                onChange={(e) =>
                  setLocalSettings((s) => ({ ...s, rateLimit: parseFloat(e.target.value) || 0 }))
                }
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 高级 */}
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.advanced')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>{t('settings.apiBaseUrl')}</Label>
            <Input
              value={localSettings.apiBaseUrl}
              onChange={(e) => setLocalSettings((s) => ({ ...s, apiBaseUrl: e.target.value }))}
              placeholder="http://localhost:3000/api"
            />
          </div>

          <Separator />

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>{t('settings.proxyEnabled')}</Label>
              <p className="text-xs text-muted-foreground">通过 HTTP 代理访问知乎</p>
            </div>
            <Switch
              checked={localSettings.proxyEnabled}
              onCheckedChange={(v) => setLocalSettings((s) => ({ ...s, proxyEnabled: v }))}
            />
          </div>

          {localSettings.proxyEnabled && (
            <div className="space-y-2">
              <Label>{t('settings.proxyUrl')}</Label>
              <Input
                value={localSettings.proxyUrl}
                onChange={(e) => setLocalSettings((s) => ({ ...s, proxyUrl: e.target.value }))}
                placeholder="http://127.0.0.1:7890"
              />
            </div>
          )}

          <Separator />

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>{t('settings.enableTelemetry')}</Label>
              <p className="text-xs text-muted-foreground">匿名使用数据帮助改进产品</p>
            </div>
            <Switch
              checked={localSettings.enableTelemetry}
              onCheckedChange={(v) => setLocalSettings((s) => ({ ...s, enableTelemetry: v }))}
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>{t('settings.enableNotifications')}</Label>
              <p className="text-xs text-muted-foreground">任务完成时显示桌面通知</p>
            </div>
            <Switch
              checked={localSettings.enableNotifications}
              onCheckedChange={(v) => setLocalSettings((s) => ({ ...s, enableNotifications: v }))}
            />
          </div>
        </CardContent>
      </Card>

      {/* 操作按钮 */}
      <div className="flex gap-2 justify-end">
        <Button variant="outline" onClick={handleReset}>
          <RotateCcw className="mr-2 h-4 w-4" />
          {t('settings.reset')}
        </Button>
        <Button onClick={handleSave}>
          <Save className="mr-2 h-4 w-4" />
          {t('settings.save')}
        </Button>
      </div>

      {/* 关于 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Info className="h-5 w-5" />
            {t('settings.about')}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-1">
          <p>{t('app.title')} v3.0.0</p>
          <p>{t('app.subtitle')}</p>
          <p className="text-xs">© 2025 Zhihu Downloader. MIT License.</p>
        </CardContent>
      </Card>
    </div>
  )
}
