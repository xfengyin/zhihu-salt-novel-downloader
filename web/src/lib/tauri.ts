/**
 * Tauri 桌面端 API 封装
 *
 * 仅在 Tauri 环境下生效；浏览器环境下所有方法为 no-op
 */

import { useTauri } from '@/hooks/useTauri'

// 动态导入 Tauri API 以避免在浏览器环境下报错
async function getInvoke(): Promise<((cmd: string, args?: unknown) => Promise<unknown>) | null> {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    return (cmd: string, args?: unknown) => invoke(cmd, args as Record<string, unknown> | undefined)
  } catch {
    return null
  }
}

async function getDialog(): Promise<{ open: (options: { directory?: boolean; multiple?: boolean; filters?: { name: string; extensions: string[] }[] }) => Promise<string | string[] | null>; save: (options: { defaultPath?: string }) => Promise<string | null> } | null> {
  try {
    const { open, save } = await import('@tauri-apps/plugin-dialog')
    return { open, save }
  } catch {
    return null
  }
}

async function getFs(): Promise<{ readTextFile: (path: string) => Promise<string>; writeTextFile: (path: string, content: string) => Promise<void>; exists: (path: string) => Promise<boolean>; mkdir: (path: string) => Promise<void> } | null> {
  try {
    const { readTextFile, writeTextFile, exists, mkdir } = await import('@tauri-apps/plugin-fs')
    return { readTextFile, writeTextFile, exists, mkdir }
  } catch {
    return null
  }
}

async function getNotification(): Promise<{ sendNotification: (options: { title: string; body: string }) => Promise<void>; isPermissionGranted: () => Promise<boolean>; requestPermission: () => Promise<string> } | null> {
  try {
    const { sendNotification, isPermissionGranted, requestPermission } = await import(
      '@tauri-apps/plugin-notification'
    )
    return {
      sendNotification: (options: { title: string; body: string }) => Promise.resolve(sendNotification(options)),
      isPermissionGranted,
      requestPermission,
    }
  } catch {
    return null
  }
}

async function getShell(): Promise<{ openExternal: (url: string) => Promise<void> } | null> {
  try {
    const { open: openExternal } = await import('@tauri-apps/plugin-shell')
    return { openExternal }
  } catch {
    return null
  }
}

async function getStore(): Promise<{ loadStore: (path: string, options?: { autoSave?: boolean; defaults?: Record<string, unknown> }) => Promise<{ get: (key: string) => Promise<unknown>; set: (key: string, value: unknown) => Promise<void> }> } | null> {
  try {
    const { load: loadStore } = await import('@tauri-apps/plugin-store')
    return {
      loadStore: (path, options) => loadStore(path, { defaults: options?.defaults ?? {} }),
    }
  } catch {
    return null
  }
}

interface BackendStatus {
  running: boolean
  pid?: number
  port?: number
}

/** Tauri 命令调用封装 */
export const tauriApi = {
  /**
   * 选择目录
   * @returns 选中的目录路径，取消返回 null
   */
  async selectDirectory(): Promise<string | null> {
    const dialog = await getDialog()
    if (!dialog) return null
    const result = await dialog.open({ directory: true, multiple: false })
    return typeof result === 'string' ? result : null
  },

  /**
   * 选择文件
   */
  async selectFile(filters?: { name: string; extensions: string[] }[]): Promise<string | null> {
    const dialog = await getDialog()
    if (!dialog) return null
    const result = await dialog.open({ multiple: false, filters })
    return typeof result === 'string' ? result : null
  },

  /**
   * 保存文件
   */
  async saveFile(defaultPath?: string): Promise<string | null> {
    const dialog = await getDialog()
    if (!dialog) return null
    return dialog.save({ defaultPath })
  },

  /**
   * 启动后端服务
   */
  async startBackend(): Promise<BackendStatus> {
    const invoke = await getInvoke()
    if (!invoke) return { running: false }
    return (await invoke('start_backend')) as BackendStatus
  },

  /**
   * 停止后端服务
   */
  async stopBackend(): Promise<void> {
    const invoke = await getInvoke()
    if (!invoke) return
    await invoke('stop_backend')
  },

  /**
   * 查询后端状态
   */
  async getBackendStatus(): Promise<BackendStatus> {
    const invoke = await getInvoke()
    if (!invoke) return { running: false }
    return (await invoke('get_backend_status')) as BackendStatus
  },

  /**
   * 读取文件
   */
  async readFile(path: string): Promise<string> {
    const fs = await getFs()
    if (!fs) throw new Error('Tauri FS 不可用')
    return fs.readTextFile(path)
  },

  /**
   * 写入文件
   */
  async writeFile(path: string, content: string): Promise<void> {
    const fs = await getFs()
    if (!fs) throw new Error('Tauri FS 不可用')
    await fs.writeTextFile(path, content)
  },

  /**
   * 发送桌面通知
   */
  async notify(title: string, body: string): Promise<void> {
    const notification = await getNotification()
    if (!notification) {
      // 浏览器通知 fallback
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(title, { body })
      }
      return
    }
    const granted = await notification.isPermissionGranted()
    if (!granted) {
      const permission = await notification.requestPermission()
      if (permission !== 'granted') return
    }
    await notification.sendNotification({ title, body })
  },

  /**
   * 外部打开链接
   */
  async openExternal(url: string): Promise<void> {
    const shell = await getShell()
    if (!shell) {
      window.open(url, '_blank')
      return
    }
    await shell.openExternal(url)
  },

  /**
   * 持久化存储
   */
  async getStore(key: string): Promise<unknown> {
    const store = await getStore()
    if (!store) {
      const raw = localStorage.getItem(`tauri-store:${key}`)
      return raw ? JSON.parse(raw) : null
    }
    const s = await store.loadStore('settings.json', { autoSave: true })
    return s.get(key)
  },

  async setStore(key: string, value: unknown): Promise<void> {
    const store = await getStore()
    if (!store) {
      localStorage.setItem(`tauri-store:${key}`, JSON.stringify(value))
      return
    }
    const s = await store.loadStore('settings.json', { autoSave: true })
    await s.set(key, value)
  },
}

/** React Hook 形式 */
export function useTauriApi() {
  const tauri = useTauri()
  return {
    ...tauriApi,
    isTauri: tauri.isTauri,
  }
}
