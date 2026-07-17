/**
 * 书架 API
 */

import { apiDelete, apiGet, apiPost, apiPut } from './client'

export interface Book {
  id: number
  url: string
  title: string
  author: string
  description?: string
  cover_url?: string
  chapter_count: number
  completed: boolean
  created_at: string
  updated_at?: string
}

export interface ShelfStats {
  total: number
  completed: number
  in_progress: number
}

export interface ShelfAddRequest {
  url: string
}

export function listShelf(): Promise<Book[]> {
  return apiGet<Book[]>('/shelves')
}

export function getShelfBook(url: string): Promise<Book> {
  return apiGet<Book>(`/shelves/${encodeURIComponent(url)}`)
}

export function addToShelf(url: string): Promise<{ success: boolean; message: string }> {
  return apiPost<{ success: boolean; message: string }, ShelfAddRequest>('/shelves', { url })
}

export function updateShelfBook(url: string, data: Partial<Book>): Promise<{ success: boolean; message: string }> {
  return apiPut<{ success: boolean; message: string }, Partial<Book>>(
    `/shelves/${encodeURIComponent(url)}`,
    data,
  )
}

export function removeFromShelf(url: string): Promise<{ success: boolean; message: string }> {
  return apiDelete<{ success: boolean; message: string }>(`/shelves/${encodeURIComponent(url)}`)
}

export function cleanShelf(): Promise<{ success: boolean; message: string }> {
  return apiDelete<{ success: boolean; message: string }>('/shelves')
}

export function getShelfStats(): Promise<ShelfStats> {
  return apiGet<ShelfStats>('/shelves/stats')
}
