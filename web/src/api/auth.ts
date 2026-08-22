/**
 * 认证 API
 */

import { apiGet, apiPost } from './client'

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface RegisterRequest {
  email: string
  password: string
}

export interface UserInfo {
  id: number
  email: string
  username?: string
  plan: 'free' | 'pro' | 'enterprise'
  is_active: boolean
  created_at: string
}

export function login(data: LoginRequest): Promise<LoginResponse> {
  return apiPost<LoginResponse, LoginRequest>('/auth/login', data)
}

export function register(data: RegisterRequest): Promise<LoginResponse> {
  return apiPost<LoginResponse, RegisterRequest>('/auth/register', data)
}

export function refreshToken(refreshToken: string): Promise<{ access_token: string }> {
  return apiPost<{ access_token: string }, { refresh_token: string }>('/auth/refresh', {
    refresh_token: refreshToken,
  })
}

export function getCurrentUser(): Promise<UserInfo> {
  return apiGet<UserInfo>('/users/me')
}

// === 扫码登录 ===

/** 扫码登录轮询状态（与后端 /auth/qrcode/{token}/status 对齐） */
export type QrLoginPhase = 'waiting' | 'scanned' | 'confirmed' | 'error' | 'expired'

/** 创建扫码登录会话的响应 */
export interface QrCodeResponse {
  token: string
  image_url: string
  expire_seconds?: number
}

/** 扫码登录状态响应 */
export interface QrLoginStatusResponse {
  status: QrLoginPhase
  user_id?: string | null
  error?: string | null
}

/** 创建知乎扫码登录会话，返回二维码 token 与图片地址 */
export function createQrCode(): Promise<QrCodeResponse> {
  return apiPost<QrCodeResponse>('/auth/qrcode', {})
}

/** 二维码图片地址（后端返回 image_url 缺失时的兜底） */
export function getQrCodeImageUrl(token: string): string {
  return `/api/auth/qrcode/${encodeURIComponent(token)}/image`
}

/** 查询扫码登录状态 */
export function getQrLoginStatus(token: string): Promise<QrLoginStatusResponse> {
  return apiGet<QrLoginStatusResponse>(`/auth/qrcode/${encodeURIComponent(token)}/status`)
}
