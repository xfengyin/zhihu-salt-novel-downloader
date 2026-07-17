import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, Palette, Download, Zap, Save, Check } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useAppStore } from '@/store/appStore'
import i18n from '@/i18n'
import type { ExportFormat } from '@/types'

export function SettingsPage() {
  const { t } = useTranslation()
  const { theme, setTheme, language, setLanguage, config, updateConfig } = useAppStore()
  const [saved, setSaved] = useState(false)

  const handleThemeChange = (value: string) => {
    setTheme(value as 'system' | 'light' | 'dark')
    if (value === 'system') {
      document.documentElement.classList.remove('dark')
    } else if (value === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  const handleLanguageChange = (value: string) => {
    setLanguage(value as 'zh' | 'en')
    i18n.changeLanguage(value)
  }

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('settings.title')}</h1>
          <p className="text-muted-foreground mt-1">{t('common.save')}</p>
        </div>
        <Button onClick={handleSave} className="flex items-center gap-2">
          {saved ? (
            <>
              <Check className="w-4 h-4" />
              {t('settings.saved')}
            </>
          ) : (
            <>
              <Save className="w-4 h-4" />
              {t('settings.save')}
            </>
          )}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="w-5 h-5 text-primary" />
            {t('settings.language')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>{t('settings.language')}</Label>
            <Select value={language} onValueChange={handleLanguageChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="zh">中文</SelectItem>
                <SelectItem value="en">English</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Palette className="w-5 h-5 text-primary" />
            {t('settings.appearance')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>{t('settings.theme')}</Label>
            <Select value={theme} onValueChange={handleThemeChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="system">{t('settings.system')}</SelectItem>
                <SelectItem value="light">{t('settings.light')}</SelectItem>
                <SelectItem value="dark">{t('settings.dark')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="w-5 h-5 text-primary" />
            {t('settings.downloads')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="defaultOutputDir">{t('settings.defaultOutputDir')}</Label>
            <Input
              id="defaultOutputDir"
              value={config.outputDir}
              onChange={(e) => updateConfig({ outputDir: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label>{t('settings.defaultFormat')}</Label>
            <Select
              value={config.format}
              onValueChange={(value) => updateConfig({ format: value as ExportFormat })}
            >
              <SelectTrigger>
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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="maxConcurrent">{t('settings.maxConcurrent')}</Label>
              <Input
                id="maxConcurrent"
                type="number"
                value={config.maxConcurrent}
                onChange={(e) => updateConfig({ maxConcurrent: parseInt(e.target.value) || 3 })}
                min={1}
                max={10}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rateLimit">{t('settings.rateLimit')}</Label>
              <Input
                id="rateLimit"
                type="number"
                value={config.rateLimit}
                onChange={(e) => updateConfig({ rateLimit: parseFloat(e.target.value) || 2 })}
                min={0}
                step={0.5}
              />
            </div>
          </div>

          <div className="flex items-center justify-between py-2">
            <Label htmlFor="cleanContent">{t('settings.cleanContent')}</Label>
            <Switch
              id="cleanContent"
              checked={config.cleanContent}
              onCheckedChange={(checked) => updateConfig({ cleanContent: checked })}
            />
          </div>

          <div className="flex items-center justify-between py-2">
            <Label htmlFor="resume">{t('settings.resume')}</Label>
            <Switch
              id="resume"
              checked={config.resume}
              onCheckedChange={(checked) => updateConfig({ resume: checked })}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-primary" />
            {t('settings.advanced')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="apiBaseUrl">{t('settings.apiBaseUrl')}</Label>
            <Input
              id="apiBaseUrl"
              value={import.meta.env.VITE_API_BASE || 'http://localhost:8000'}
              disabled
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="timeout">{t('settings.timeout')}</Label>
            <Input
              id="timeout"
              type="number"
              value={30}
              min={5}
              max={300}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}