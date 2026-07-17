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
