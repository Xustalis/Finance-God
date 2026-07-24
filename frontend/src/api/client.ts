import axios, { AxiosError } from 'axios'
import type { ApiEnvelope } from '@/types/api'

const TOKEN_KEY = 'finance-god-token'
export class ApiClientError extends Error { constructor(message:string, public status?:number, public code?:string){ super(message) } }
function detailText(details:unknown):string|null{if(typeof details==='string')return details;if(details&&typeof details==='object'&&'reason'in details&&typeof details.reason==='string')return details.reason;return null}
export function errorMessageFromEnvelope(body:ApiEnvelope<unknown>|undefined):string{const base=body?.error?.message||'请求失败';const detail=detailText(body?.error?.details);return detail?`${base}：${detail}`:base}

export const http = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1', timeout: 30000 })
http.interceptors.request.use((config) => { const token=localStorage.getItem(TOKEN_KEY); if(token) config.headers.Authorization=`Bearer ${token}`; return config })
http.interceptors.response.use(undefined, (error:AxiosError<ApiEnvelope<unknown>>) => {
  if(error.response?.status===401){ localStorage.removeItem(TOKEN_KEY); localStorage.removeItem('finance-god-user'); if(location.pathname!='/login') location.assign('/login') }
  const body=error.response?.data; const message=body ? errorMessageFromEnvelope(body) : error.message || '请求失败'
  return Promise.reject(new ApiClientError(message,error.response?.status,body?.error?.code))
})
export function unwrapEnvelope<T>(envelope:ApiEnvelope<T>):T{if(!envelope.success||envelope.data===null)throw new ApiClientError(errorMessageFromEnvelope(envelope),undefined,envelope.error?.code);return envelope.data}
async function unwrap<T>(request:Promise<{data:ApiEnvelope<T>}>):Promise<T>{const {data}=await request;return unwrapEnvelope(data)}
export const api = {
  get:<T>(url:string)=>unwrap(http.get<ApiEnvelope<T>>(url)),
  post:<T>(url:string,body?:unknown)=>unwrap(http.post<ApiEnvelope<T>>(url,body)),
  put:<T>(url:string,body?:unknown)=>unwrap(http.put<ApiEnvelope<T>>(url,body)),
}
