import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import {
  Home,
  Download,
  BookMarked,
  Clock,
  Settings,
  BookOpen,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/appStore'

const navItems = [
  { path: '/', icon: Home, label: 'nav.home' },
  { path: '/download', icon: Download, label: 'nav.download' },
  { path: '/library', icon: BookMarked, label: 'nav.library' },
  { path: '/tasks', icon: Clock, label: 'nav.tasks' },
  { path: '/settings', icon: Settings, label: 'nav.settings' },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const { sidebarCollapsed, toggleSidebar } = useAppStore()
  const location = useLocation()

  return (
    <div className="flex min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50 dark:from-slate-900 dark:via-slate-900 dark:to-indigo-950">
      <aside
        className={`fixed left-0 top-0 h-screen z-50 transition-all duration-300 ease-in-out ${
          sidebarCollapsed ? 'w-16' : 'w-64'
        } bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg border-r border-border/50`}
      >
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-between p-4 border-b border-border/50">
            {!sidebarCollapsed && (
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-primary/25">
                  <BookOpen className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h1 className="text-lg font-bold tracking-tight gradient-text">
                    {t('app.title')}
                  </h1>
                  <p className="text-xs text-muted-foreground">{t('app.subtitle')}</p>
                </div>
              </div>
            )}
            {sidebarCollapsed && (
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-primary/25 mx-auto">
                <BookOpen className="w-5 h-5 text-white" />
              </div>
            )}
          </div>

          <nav className="flex-1 p-4">
            <ul className="space-y-1">
              {navItems.map((item) => {
                const Icon = item.icon
                const isActive = location.pathname === item.path
                return (
                  <li key={item.path}>
                    <Link
                      to={item.path}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 ${
                        isActive
                          ? 'bg-primary text-primary-foreground shadow-md'
                          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                      }`}
                    >
                      <Icon className="w-5 h-5" />
                      {!sidebarCollapsed && <span className="font-medium">{t(item.label)}</span>}
                      {isActive && !sidebarCollapsed && (
                        <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-foreground" />
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </nav>

          <div className="p-4 border-t border-border/50">
            <Button
              variant="ghost"
              size="icon"
              className="w-full justify-center"
              onClick={toggleSidebar}
            >
              {sidebarCollapsed ? (
                <ChevronRight className="w-5 h-5" />
              ) : (
                <ChevronLeft className="w-5 h-5" />
              )}
            </Button>
          </div>
        </div>
      </aside>

      <main
        className={`flex-1 transition-all duration-300 ease-in-out ${
          sidebarCollapsed ? 'ml-16' : 'ml-64'
        }`}
      >
        <div className="p-4 md:p-8">{children}</div>
      </main>
    </div>
  )
}