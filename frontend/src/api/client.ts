import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios'
import type { ApiEnvelope } from '@/types/api'
import { v1ApiBase } from '@/services/apiBase'
import { expireBrowserSession, USER_SESSION } from '@/services/authSession'

export class ApiClientError extends Error {
  constructor(message: string, public status?: number, public code?: string) { super(message) }
}

const DEFAULT_REQUEST_TIMEOUT_MS = 30_000

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

export function apiClientErrorFromAxios(error: AxiosError<ApiEnvelope<unknown>>): ApiClientError {
  const body = error.response?.data
  if (body) return new ApiClientError(errorMessageFromEnvelope(body), error.response?.status, body.error?.code)
  if (error.code === AxiosError.ETIMEDOUT || error.code === AxiosError.ECONNABORTED) {
    return new ApiClientError('服务响应超时，请重试；已提交的访谈回答不会重复记录')
  }
  return new ApiClientError(error.message || '请求失败')
}

interface ClientOptions { tokenKey: string; userKey: string; loginPath: string }

export function createHttpClient({ tokenKey, userKey, loginPath }: ClientOptions): AxiosInstance {
  const client = axios.create({ baseURL: v1ApiBase(), timeout: DEFAULT_REQUEST_TIMEOUT_MS })
  client.interceptors.request.use((config) => {
    const token = localStorage.getItem(tokenKey)
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  })
  client.interceptors.response.use(undefined, (error: AxiosError<ApiEnvelope<unknown>>) => {
    if (error.response?.status === 401) expireBrowserSession({ tokenKey, userKey, loginPath })
    return Promise.reject(apiClientErrorFromAxios(error))
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
    get: <T>(url: string, config?: AxiosRequestConfig) => unwrap(client.get<ApiEnvelope<T>>(url, config)),
    post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) => unwrap(client.post<ApiEnvelope<T>>(url, body, config)),
    put: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) => unwrap(client.put<ApiEnvelope<T>>(url, body, config)),
    patch: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) => unwrap(client.patch<ApiEnvelope<T>>(url, body, config)),
  }
}

export const http = createHttpClient(USER_SESSION)
export const adminHttp = createHttpClient({ tokenKey: 'finance-god-admin-token', userKey: 'finance-god-admin-user', loginPath: '/admin/login' })
export const api = clientApi(http)
export const adminHttpApi = clientApi(adminHttp)
