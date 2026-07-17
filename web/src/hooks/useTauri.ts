/**
 * Tauri 环境检测
 *
 * 用于判断当前是否在 Tauri 桌面应用中运行，
 * 以便选择不同的 API 路径策略
 */

import { useEffect, useState } from 'react'

interface TauriInfo {
  isTauri: boolean
  version: string | null
  platform: string | null
}

export function useTauri(): TauriInfo {
  const [info, setInfo] = useState<TauriInfo>({
    isTauri: false,
    version: null,
    platform: null,
  })

  useEffect(() => {
    // 检查 Tauri 全局对象
    const w = window as unknown as { __TAURI__?: { version?: string; os?: { platform?: string } } }
    if (w.__TAURI__) {
      setInfo({
        isTauri: true,
        version: w.__TAURI__.version ?? null,
        platform: w.__TAURI__.os?.platform ?? null,
      })
    }
  }, [])

  return info
}
