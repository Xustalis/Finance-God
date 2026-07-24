/* ═══════════════════════════════════════════════════
   交易台 API 客户端
   直接调用后端 /api/* 端点（无 envelope 包装）
   ═══════════════════════════════════════════════════ */

import axios, { AxiosError } from 'axios'
import type {
  BarsResponse,
  BackendError,
  CatalogResponse,
  HealthResponse,
  QuoteBatch,
} from '@/types/desk'

/** 独立 axios 实例：baseURL=/api，不带 auth 拦截器 */
const desk = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

/** 从后端 {error:{code,message}} 格式提取错误消息 */
function extractError(error: unknown): string {
  if (error instanceof AxiosError) {
    const body = error.response?.data as BackendError | undefined
    if (body?.error?.message) return body.error.message
    return error.message
  }
  return String(error)
}

// ─── 行情数据 ──────────────────────────────────────

/** 批量获取实时行情报价 */
export async function fetchQuotes(symbols: string[]): Promise<QuoteBatch> {
  try {
    const { data } = await desk.get<QuoteBatch>('/market/quotes', {
      params: { symbols: symbols.join(',') },
    })
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

/** 获取 K 线数据 */
export async function fetchBars(symbol: string, limit = 80): Promise<BarsResponse> {
  try {
    const { data } = await desk.get<BarsResponse>('/market/bars', {
      params: { symbol, limit },
    })
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

/** 获取数据目录 */
export async function fetchCatalog(): Promise<CatalogResponse> {
  try {
    const { data } = await desk.get<CatalogResponse>('/market/catalog')
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

// ─── 健康检查 ──────────────────────────────────────

/** 检查后端健康状态 */
export async function fetchHealth(): Promise<HealthResponse> {
  try {
    const { data } = await desk.get<HealthResponse>('/health')
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

// ─── 仿真交易（需要 owner header） ────────────────

const SIM_OWNER = 'desktop-user'

function simHeaders(extraIdempotency?: string) {
  return {
    'x-finance-god-owner-id': SIM_OWNER,
    ...(extraIdempotency ? { 'idempotency-key': extraIdempotency } : {}),
  }
}

export async function fetchCurrentAccount() {
  try {
    const { data } = await desk.get('/simulation/accounts/current', {
      headers: simHeaders(),
    })
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

export async function fetchOrders() {
  try {
    const { data } = await desk.get('/simulation/orders', {
      headers: simHeaders(),
    })
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

export async function fetchFills(orderId?: string) {
  try {
    const { data } = await desk.get('/simulation/fills', {
      headers: simHeaders(),
      params: orderId ? { order_id: orderId } : undefined,
    })
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}

// ─── 工作区（自选股等） ────────────────────────────

export async function fetchWatchlists() {
  try {
    const { data } = await desk.get('/workspace/watchlists')
    return data
  } catch (err) {
    throw new Error(extractError(err))
  }
}
