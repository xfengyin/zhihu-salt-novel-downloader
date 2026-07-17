import { useTranslation } from 'react-i18next'
import { BookOpen, Download, BookMarked, Clock, FileText, Settings, ChevronRight } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Link } from 'react-router-dom'
import { useAppStore } from '@/store/appStore'

export function HomePage() {
  const { t } = useTranslation()
  const { library, tasks } = useAppStore()

  const activeTasks = tasks.filter(t => t.status === 'downloading' || t.status === 'exporting').length

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('home.welcome')}</h1>
          <p className="text-muted-foreground mt-1">{t('app.subtitle')}</p>
        </div>
        <Link to="/download">
          <Button size="lg">
            <Download className="w-5 h-5 mr-2" />
            {t('download.startDownload')}
          </Button>
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">{t('home.totalDownloaded')}</p>
                <p className="text-3xl font-bold mt-1">{library.length}</p>
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
                <p className="text-3xl font-bold mt-1">{library.length}</p>
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
          <Card className="gradient-border">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="w-5 h-5 text-primary" />
                {t('home.quickStart')}
              </CardTitle>
              <CardDescription>{t('home.step1Desc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <span className="text-sm font-bold text-primary">1</span>
                </div>
                <div>
                  <h4 className="font-medium">{t('home.step1')}</h4>
                  <p className="text-sm text-muted-foreground">{t('home.step1Desc')}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <span className="text-sm font-bold text-primary">2</span>
                </div>
                <div>
                  <h4 className="font-medium">{t('home.step2')}</h4>
                  <p className="text-sm text-muted-foreground">{t('home.step2Desc')}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <span className="text-sm font-bold text-primary">3</span>
                </div>
                <div>
                  <h4 className="font-medium">{t('home.step3')}</h4>
                  <p className="text-sm text-muted-foreground">{t('home.step3Desc')}</p>
                </div>
              </div>
              <Link to="/download">
                <Button className="w-full mt-4">
                  {t('download.startDownload')}
                  <ChevronRight className="w-4 h-4 ml-2" />
                </Button>
              </Link>
            </CardContent>
          </Card>

          {tasks.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Clock className="w-5 h-5 text-primary" />
                  {t('home.recentActivity')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {tasks.slice(0, 3).map(task => (
                    <div
                      key={task.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <BookOpen className="w-5 h-5 text-primary" />
                        <div>
                          <p className="font-medium text-sm">{task.title}</p>
                          <p className="text-xs text-muted-foreground">{task.status}</p>
                        </div>
                      </div>
                      <Link to="/tasks" className="text-sm text-primary hover:underline">
                        {t('tasks.viewDetails')}
                      </Link>
                    </div>
                  ))}
                </div>
                {tasks.length > 3 && (
                  <Link to="/tasks" className="block text-center text-sm text-primary mt-4 hover:underline">
                    {t('common.viewAll')}
                  </Link>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">{t('home.supportedFormats')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { name: 'Markdown', ext: '.md', icon: '📝' },
                  { name: 'EPUB', ext: '.epub', icon: '📖' },
                  { name: '文本', ext: '.txt', icon: '📄' },
                ].map(format => (
                  <div
                    key={format.ext}
                    className="flex flex-col items-center p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                  >
                    <span className="text-2xl mb-1">{format.icon}</span>
                    <span className="text-sm font-medium">{format.name}</span>
                    <span className="text-xs text-muted-foreground">{format.ext}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <h4 className="font-medium mb-4">快捷导航</h4>
              <div className="space-y-2">
                <Link to="/download" className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors">
                  <Download className="w-5 h-5 text-primary" />
                  <span>{t('nav.download')}</span>
                </Link>
                <Link to="/library" className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors">
                  <BookMarked className="w-5 h-5 text-primary" />
                  <span>{t('nav.library')}</span>
                </Link>
                <Link to="/tasks" className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors">
                  <Clock className="w-5 h-5 text-primary" />
                  <span>{t('nav.tasks')}</span>
                </Link>
                <Link to="/settings" className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors">
                  <Settings className="w-5 h-5 text-primary" />
                  <span>{t('nav.settings')}</span>
                </Link>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}