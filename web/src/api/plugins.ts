/**
 * 插件 API
 */

import { apiDelete, apiGet, apiPost } from './client'

export type PluginKind = 'source' | 'exporter' | 'hook'

export interface Plugin {
  id: number
  name: string
  version: string
  kind: PluginKind
  entry: string
  enabled: boolean
  created_at: string
}

export function listPlugins(): Promise<Plugin[]> {
  return apiGet<Plugin[]>('/plugins')
}

export function installPlugin(data: {
  name: string
  version: string
  kind: PluginKind
  entry: string
  config?: Record<string, unknown>
}): Promise<Plugin> {
  return apiPost<Plugin, typeof data>('/plugins', data)
}

export function uninstallPlugin(pluginId: number): Promise<{ message: string; plugin_id: number }> {
  return apiDelete<{ message: string; plugin_id: number }>(`/plugins/${pluginId}`)
}
