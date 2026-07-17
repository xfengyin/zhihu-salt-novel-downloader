import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { BookMarked, Search, Trash2, Calendar, FileText } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAppStore } from '@/store/appStore'

export function LibraryPage() {
  const { t } = useTranslation()
  const { library, removeBook } = useAppStore()
  const [searchQuery, setSearchQuery] = useState('')

  const filteredBooks = useMemo(() => {
    if (!searchQuery) return library
    const query = searchQuery.toLowerCase()
    return library.filter(
      book =>
        book.title.toLowerCase().includes(query) ||
        book.author.toLowerCase().includes(query),
    )
  }, [library, searchQuery])

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString()
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('library.title')}</h1>
          <p className="text-muted-foreground mt-1">
            {t('common.name')}: {filteredBooks.length}
          </p>
        </div>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('library.search')}
          className="pl-10"
        />
      </div>

      {filteredBooks.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <div className="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mx-auto mb-4">
              <BookMarked className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-xl font-semibold mb-2">
              {searchQuery ? t('library.noResults') : t('library.empty')}
            </h3>
            <p className="text-muted-foreground">{t('library.emptyDesc')}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredBooks.map(book => (
            <Card
              key={book.url}
              className="group hover:shadow-lg transition-all duration-200"
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h4 className="font-semibold truncate">{book.title}</h4>
                    <p className="text-sm text-muted-foreground truncate">{book.author}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                    onClick={() => removeBook(book.url)}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <FileText className="w-3 h-3" />
                    {book.chapter_count} {t('common.name')}
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {formatDate(book.added_at)}
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span
                    className={`text-xs px-2 py-1 rounded-full ${
                      book.completed
                        ? 'bg-green-100 text-green-700'
                        : 'bg-yellow-100 text-yellow-700'
                    }`}
                  >
                    {book.completed ? t('common.success') : t('tasks.status.pending')}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}