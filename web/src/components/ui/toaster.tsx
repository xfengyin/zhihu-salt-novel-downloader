/**
 * Toast 通知组件
 *
 * 基于 Sonner 库，提供统一的成功/错误/信息提示
 */

import { Toaster as Sonner } from 'sonner'
import { useTheme } from '@/hooks/useTheme'

interface ToasterProps {
  position?: 'top-left' | 'top-right' | 'top-center' | 'bottom-left' | 'bottom-right' | 'bottom-center'
  richColors?: boolean
  closeButton?: boolean
}

export function Toaster({
  position = 'top-right',
  richColors = true,
  closeButton = true,
}: ToasterProps) {
  const { resolvedTheme } = useTheme()
  return (
    <Sonner
      theme={resolvedTheme}
      position={position}
      richColors={richColors}
      closeButton={closeButton}
      toastOptions={{
        classNames: {
          toast: 'group toast group',
          title: 'text-sm font-semibold',
          description: 'text-xs opacity-90',
        },
      }}
    />
  )
}

// 重新导出 sonner 的 toast 函数
export { toast } from 'sonner'
