/**
 * 知乎扫码登录对话框
 *
 * 打开后调用后端创建二维码会话，展示二维码并每 2s 轮询状态：
 * - waiting：等待扫码
 * - scanned：已扫码，等待手机确认
 * - confirmed：登录成功，自动关闭
 * - error/expired：展示错误并提供重新获取
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  QrCode,
  RefreshCw,
  ScanLine,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  createQrCode,
  getQrCodeImageUrl,
  getQrLoginStatus,
  type QrLoginPhase,
} from '@/api/auth'
import { extractErrorMessage } from '@/api/client'
import { toast } from '@/components/ui/toaster'

/** 前端展示阶段：loading / waiting / scanned / confirmed / error / expired */
type Phase = 'loading' | QrLoginPhase

export function QrLoginDialog() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>('loading')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const fetchQrCode = useCallback(async () => {
    stopPolling()
    setPhase('loading')
    setErrorMsg(null)
    setImageUrl(null)
    setToken(null)
    try {
      const resp = await createQrCode()
      setToken(resp.token)
      setImageUrl(resp.image_url || getQrCodeImageUrl(resp.token))
      setPhase('waiting')
    } catch (err) {
      setPhase('error')
      setErrorMsg(extractErrorMessage(err, '获取二维码失败'))
    }
  }, [stopPolling])

  const pollStatus = useCallback(async () => {
    if (!token) return
    try {
      const status = await getQrLoginStatus(token)
      switch (status.status) {
        case 'waiting':
          setPhase('waiting')
          break
        case 'scanned':
          setPhase('scanned')
          break
        case 'confirmed':
          setPhase('confirmed')
          stopPolling()
          toast.success(t('auth.qrLoginSuccess'))
          break
        case 'error':
          setPhase('error')
          setErrorMsg(status.error ?? t('auth.qrLoginFailed'))
          stopPolling()
          break
        case 'expired':
          setPhase('expired')
          stopPolling()
          break
      }
    } catch {
      // 网络异常或 token 失效（如 404/410）视为二维码过期
      setPhase('expired')
      stopPolling()
    }
  }, [token, stopPolling, t])

  // 打开对话框时创建二维码，关闭时停止轮询
  useEffect(() => {
    if (open) {
      void fetchQrCode()
    } else {
      stopPolling()
    }
    return () => stopPolling()
  }, [open, fetchQrCode, stopPolling])

  // 每 2s 轮询一次登录状态
  useEffect(() => {
    if (open && token && (phase === 'waiting' || phase === 'scanned')) {
      timerRef.current = window.setInterval(() => {
        void pollStatus()
      }, 2000)
    }
    return () => stopPolling()
  }, [open, token, phase, pollStatus, stopPolling])

  // 登录成功后延迟关闭
  useEffect(() => {
    if (phase !== 'confirmed') return
    const timer = window.setTimeout(() => setOpen(false), 1500)
    return () => window.clearTimeout(timer)
  }, [phase])

  const isBusy = phase === 'loading' || phase === 'waiting' || phase === 'scanned'

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <QrCode className="mr-2 h-4 w-4" />
          {t('auth.qrLogin')}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <QrCode className="h-5 w-5 text-primary" />
            {t('auth.qrLogin')}
          </DialogTitle>
          <DialogDescription>{t('auth.qrLoginDesc')}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col items-center gap-4 py-4">
          {/* 二维码区域 */}
          <div className="relative flex h-52 w-52 items-center justify-center overflow-hidden rounded-xl border bg-white p-2">
            {isBusy && imageUrl ? (
              <img
                src={imageUrl}
                alt={t('auth.qrLogin')}
                className="h-full w-full object-contain"
                onError={() => {
                  setPhase('expired')
                  stopPolling()
                }}
              />
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                {phase === 'loading' ? (
                  <Loader2 className="h-8 w-8 animate-spin" />
                ) : phase === 'confirmed' ? (
                  <CheckCircle2 className="h-8 w-8 text-green-500" />
                ) : phase === 'expired' ? (
                  <RefreshCw className="h-8 w-8" />
                ) : phase === 'error' ? (
                  <AlertCircle className="h-8 w-8 text-destructive" />
                ) : (
                  <QrCode className="h-8 w-8" />
                )}
              </div>
            )}

            {/* 已扫码遮罩 */}
            {phase === 'scanned' && imageUrl && (
              <div className="absolute inset-0 flex items-center justify-center bg-background/90">
                <CheckCircle2 className="h-12 w-12 text-green-500" />
              </div>
            )}
          </div>

          {/* 状态文案 */}
          <div className="flex flex-col items-center gap-1 text-center">
            {phase === 'loading' && (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
              </>
            )}
            {phase === 'waiting' && (
              <>
                <ScanLine className="h-5 w-5 text-primary" />
                <p className="text-sm font-medium">{t('auth.qrWaiting')}</p>
                <p className="text-xs text-muted-foreground">{t('auth.qrWaitingDesc')}</p>
              </>
            )}
            {phase === 'scanned' && (
              <>
                <p className="text-sm font-medium text-green-600 dark:text-green-400">
                  {t('auth.qrScanned')}
                </p>
                <p className="text-xs text-muted-foreground">{t('auth.qrScannedDesc')}</p>
              </>
            )}
            {phase === 'confirmed' && (
              <p className="text-sm font-medium text-green-600 dark:text-green-400">
                {t('auth.qrConfirmed')}
              </p>
            )}
            {(phase === 'error' || phase === 'expired') && (
              <>
                <p className="text-sm font-medium text-destructive">
                  {phase === 'expired' ? t('auth.qrExpired') : t('auth.qrError')}
                </p>
                <p className="text-xs text-muted-foreground">
                  {phase === 'expired' ? t('auth.qrExpiredDesc') : (errorMsg ?? '')}
                </p>
              </>
            )}
          </div>
        </div>

        <div className="flex justify-center">
          {(phase === 'error' || phase === 'expired') && (
            <Button variant="outline" size="sm" onClick={() => void fetchQrCode()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('auth.qrRefresh')}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
