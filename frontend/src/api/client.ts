import axios, { AxiosError, type AxiosInstance } from 'axios'
import type { ApiEnvelope } from '@/types/api'

export class ApiClientError extends Error {
  constructor(message: string, public status?: number, public code?: string) { super(message) }
}

function detailText(details: unknown): string | null {
  if (typeof details === 'string') return details
  if (details && typeof details === 'object' && 'reason' in details && typeof details.reason === 'string') return details.reason
  return null
}

export function errorMessageFromEnvelope(body: ApiEnvelope<unknown> | undefined): string {
  const base = body?.error?.message || '请求失败'
  const detail = detailText(body?.error?.details)
  return detail ? `${base}：${detail}` : base
}

interface ClientOptions { tokenKey: string; userKey: string; loginPath: string }

export function createHttpClient({ tokenKey, userKey, loginPath }: ClientOptions): AxiosInstance {
  const client = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1', timeout: 30000 })
  client.interceptors.request.use((config) => {
    const token = localStorage.getItem(tokenKey)
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  })
  client.interceptors.response.use(undefined, (error: AxiosError<ApiEnvelope<unknown>>) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(tokenKey)
      localStorage.removeItem(userKey)
      if (location.pathname !== loginPath) location.assign(loginPath)
    }
    const body = error.response?.data
    const message = body ? errorMessageFromEnvelope(body) : error.message || '请求失败'
    return Promise.reject(new ApiClientError(message, error.response?.status, body?.error?.code))
  })
  return client
}

export function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (!envelope.success || envelope.data === null) throw new ApiClientError(errorMessageFromEnvelope(envelope), undefined, envelope.error?.code)
  return envelope.data
}

function clientApi(client: AxiosInstance) {
  const unwrap = async <T>(request: Promise<{ data: ApiEnvelope<T> }>): Promise<T> => unwrapEnvelope((await request).data)
  return {
    get: <T>(url: string) => unwrap(client.get<ApiEnvelope<T>>(url)),
    post: <T>(url: string, body?: unknown) => unwrap(client.post<ApiEnvelope<T>>(url, body)),
    put: <T>(url: string, body?: unknown) => unwrap(client.put<ApiEnvelope<T>>(url, body)),
    patch: <T>(url: string, body?: unknown) => unwrap(client.patch<ApiEnvelope<T>>(url, body)),
  }
}

export const http = createHttpClient({ tokenKey: 'finance-god-token', userKey: 'finance-god-user', loginPath: '/login' })
export const adminHttp = createHttpClient({ tokenKey: 'finance-god-admin-token', userKey: 'finance-god-admin-user', loginPath: '/admin/login' })
export const api = clientApi(http)
export const adminHttpApi = clientApi(adminHttp)
