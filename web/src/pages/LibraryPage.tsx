/**
 * 书架页面
 *
 * - 显示已下载/已加入书架的书籍
 * - 搜索、筛选、批量操作
 * - 统计卡片
 */

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BookOpen, Search, Trash2, Calendar, FileText, Plus, AlertTriangle } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  useAddToShelf,
  useCleanShelf,
  useRemoveFromShelf,
  useShelf,
  useShelfStats,
} from '@/hooks/queries'
import { extractErrorMessage } from '@/api/client'
import { toast } from '@/components/ui/toaster'
import { formatDate } from '@/lib/utils'
import type { Book } from '@/api/shelf'

export function LibraryPage() {
  const { t } = useTranslation()
  const { data: books = [], isLoading } = useShelf()
  const { data: stats } = useShelfStats()
  const addMutation = useAddToShelf()
  const removeMutation = useRemoveFromShelf()
  const cleanMutation = useCleanShelf()

  const [searchQuery, setSearchQuery] = useState('')
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [addUrl, setAddUrl] = useState('')
  const [cleanDialogOpen, setCleanDialogOpen] = useState(false)

  const filteredBooks = useMemo(() => {
    if (!searchQuery) return books
    const query = searchQuery.toLowerCase()
    return books.filter(
      (book) =>
        book.title.toLowerCase().includes(query) ||
        book.author.toLowerCase().includes(query),
    )
  }, [books, searchQuery])

  const handleAdd = async () => {
    if (!addUrl.trim()) return
    try {
      await addMutation.mutateAsync(addUrl)
      toast.success(t('common.success'), { description: '已加入书架' })
      setAddUrl('')
      setAddDialogOpen(false)
    } catch (error) {
      toast.error(t('common.error'), { description: extractErrorMessage(error) })
    }
  }

  const handleRemove = async (book: Book) => {
    try {
      await removeMutation.mutateAsync(book.url)
      toast.success(t('common.success'), { description: '已移除' })
    } catch (error) {
      toast.error(t('common.error'), { description: extractErrorMessage(error) })
    }
  }

  const handleClean = async () => {
    try {
      await cleanMutation.mutateAsync()
      toast.success(t('common.success'), { description: '已清空书架' })
      setCleanDialogOpen(false)
    } catch (error) {
      toast.error(t('common.error'), { description: extractErrorMessage(error) })
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('library.title')}</h1>
          <p className="text-muted-foreground mt-1">
            {t('library.total')}: {books.length}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setAddDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t('library.addBook')}
          </Button>
          {books.length > 0 && (
            <Button variant="outline" onClick={() => setCleanDialogOpen(true)}>
              <Trash2 className="mr-2 h-4 w-4" />
              {t('library.clean')}
            </Button>
          )}
        </div>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>{t('library.total')}</CardDescription>
              <CardTitle className="text-3xl">{stats.total}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>{t('library.completed')}</CardDescription>
              <CardTitle className="text-3xl text-green-600">{stats.completed}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>{t('library.inProgress')}</CardDescription>
              <CardTitle className="text-3xl text-blue-600">{stats.in_progress}</CardTitle>
            </CardHeader>
          </Card>
        </div>
      )}

      {/* 搜索框 */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('library.search')}
          className="pl-10"
        />
      </div>

      {/* 书架列表 */}
      {isLoading ? (
        <div className="text-center py-12 text-muted-foreground">{t('common.loading')}</div>
      ) : filteredBooks.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <div className="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mx-auto mb-4">
              <BookOpen className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-xl font-semibold mb-2">
              {searchQuery ? t('library.noResults') : t('library.empty')}
            </h3>
            <p className="text-muted-foreground">{t('library.emptyDesc')}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredBooks.map((book) => (
            <Card key={book.id ?? book.url} className="group hover:shadow-lg transition-all">
              <CardContent className="p-4">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h4 className="font-semibold truncate">{book.title}</h4>
                    <p className="text-sm text-muted-foreground truncate">{book.author}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                    onClick={() => void handleRemove(book)}
                    disabled={removeMutation.isPending}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <FileText className="w-3 h-3" />
                    {book.chapter_count} 章节
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {formatDate(book.created_at)}
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span
                    className={`text-xs px-2 py-1 rounded-full ${
                      book.completed
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                        : 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300'
                    }`}
                  >
                    {book.completed ? t('library.completed') : t('library.inProgress')}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* 添加书籍对话框 */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('library.addBook')}</DialogTitle>
            <DialogDescription>{t('library.addBookDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Input
              value={addUrl}
              onChange={(e) => setAddUrl(e.target.value)}
              placeholder="https://www.zhihu.com/..."
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleAdd()
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAddDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleAdd} disabled={!addUrl.trim() || addMutation.isPending}>
              {addMutation.isPending ? t('common.loading') : t('library.add')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 清空确认对话框 */}
      <Dialog open={cleanDialogOpen} onOpenChange={setCleanDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-yellow-500" />
              {t('library.cleanConfirm')}
            </DialogTitle>
            <DialogDescription>{t('library.cleanConfirmDesc')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCleanDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleClean}
              disabled={cleanMutation.isPending}
            >
              {cleanMutation.isPending ? t('common.loading') : t('common.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
