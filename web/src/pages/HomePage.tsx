/**
 * 首页
 *
 * - 统计数据（已下载、书架、活跃任务）
 * - 快速上手指引
 * - 支持格式展示
 * - 快捷导航
 */

import { useTranslation } from 'react-i18next'
import { BookOpen, Download, BookMarked, Clock, FileText, Settings, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useShelf, useDownloads, useShelfStats } from '@/hooks/queries'
import { useTauri } from '@/hooks/useTauri'

export function HomePage() {
  const { t } = useTranslation()
  const { data: books = [] } = useShelf()
  const { data: stats } = useShelfStats()
  const { data: tasks = [] } = useDownloads()
  const tauri = useTauri()

  const activeTasks = tasks.filter((task) => task.status === 'running' || task.status === 'pending').length
  const recentTasks = tasks.slice(0, 3)

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('home.welcome')}</h1>
          <p className="text-muted-foreground mt-1">{t('app.subtitle')}</p>
          {tauri.isTauri && (
            <p className="text-xs text-muted-foreground mt-1">
              🖥️ 桌面端模式 v{tauri.version} · {tauri.platform}
            </p>
          )}
        </div>
        <Link to="/download">
          <Button size="lg">
            <Download className="w-5 h-5 mr-2" />
            {t('download.startDownload')}
          </Button>
        </Link>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">{t('home.totalDownloaded')}</p>
                <p className="text-3xl font-bold mt-1">{stats?.completed ?? 0}</p>
              </div>
              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                <Download className="w-6 h-6 text-primary" />
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">{t('home.booksInLibrary')}</p>
                <p className="text-3xl font-bold mt-1">{books.length}</p>
              </div>
              <div className="w-12 h-12 rounded-full bg-secondary/10 flex items-center justify-center">
                <BookMarked className="w-6 h-6 text-secondary-foreground" />
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">{t('home.activeTasks')}</p>
                <p className="text-3xl font-bold mt-1">{activeTasks}</p>
              </div>
              <div className="w-12 h-12 rounded-full bg-accent/10 flex items-center justify-center">
                <Clock className="w-6 h-6 text-accent-foreground" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* 快速上手 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="w-5 h-5 text-primary" />
                {t('home.quickStart')}
              </CardTitle>
              <CardDescription>三步完成小说下载</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {[
                { num: 1, title: t('home.step1'), desc: t('home.step1Desc') },
                { num: 2, title: t('home.step2'), desc: t('home.step2Desc') },
                { num: 3, title: t('home.step3'), desc: t('home.step3Desc') },
              ].map((step) => (
                <div key={step.num} className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-sm font-bold text-primary">{step.num}</span>
                  </div>
                  <div>
                    <h4 className="font-medium">{step.title}</h4>
                    <p className="text-sm text-muted-foreground">{step.desc}</p>
                  </div>
                </div>
              ))}
              <Link to="/download">
                <Button className="w-full mt-4">
                  {t('download.startDownload')}
                  <ChevronRight className="w-4 h-4 ml-2" />
                </Button>
              </Link>
            </CardContent>
          </Card>

          {/* 最近任务 */}
          {recentTasks.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Clock className="w-5 h-5 text-primary" />
                  {t('home.recentActivity')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {recentTasks.map((task) => (
                    <div
                      key={task.task_id}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <BookOpen className="w-5 h-5 text-primary" />
                        <div>
                          <p className="font-medium text-sm font-mono">{task.task_id}</p>
                          <p className="text-xs text-muted-foreground">{t(`tasks.status.${task.status}`)}</p>
                        </div>
                      </div>
                      <Link to="/tasks" className="text-sm text-primary hover:underline">
                        {t('tasks.viewDetails')}
                      </Link>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* 右侧栏 */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">{t('home.supportedFormats')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { name: 'Markdown', ext: '.md', icon: '📝' },
                  { name: 'EPUB', ext: '.epub', icon: '📖' },
                  { name: 'MOBI', ext: '.mobi', icon: '📕' },
                  { name: 'TXT', ext: '.txt', icon: '📄' },
                ].map((format) => (
                  <div
                    key={format.ext}
                    className="flex flex-col items-center p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                  >
                    <span className="text-2xl mb-1">{format.icon}</span>
                    <span className="text-sm font-medium">{format.name}</span>
                    <span className="text-xs text-muted-foreground font-mono">{format.ext}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <h4 className="font-medium mb-4">快捷导航</h4>
              <div className="space-y-2">
                {[
                  { to: '/download', icon: Download, label: t('nav.download') },
                  { to: '/library', icon: BookMarked, label: t('nav.library') },
                  { to: '/tasks', icon: Clock, label: t('nav.tasks') },
                  { to: '/settings', icon: Settings, label: t('nav.settings') },
                ].map((item) => {
                  const Icon = item.icon
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors"
                    >
                      <Icon className="w-5 h-5 text-primary" />
                      <span>{item.label}</span>
                    </Link>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
