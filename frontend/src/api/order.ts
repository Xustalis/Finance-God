import client from './client';
import type { ApiResponse, OrderIntent, PageResponse } from '../types';

export interface OrderListParams {
  status?: string;
  page?: number;
  page_size?: number;
}

/** 查询订单列表 */
export async function getOrders(params: OrderListParams = {}): Promise<PageResponse<OrderIntent>> {
  const res = await client.get<ApiResponse<OrderIntent[]>>('/orders', {
    params: { page: 1, page_size: 20, ...params },
  });
  const meta = res.data.meta || {};
  return {
    items: res.data.data,
    total: Number(meta.total ?? res.data.data.length),
    page: Number(meta.page ?? params.page ?? 1),
    page_size: Number(meta.page_size ?? params.page_size ?? 20),
  };
}

/** 创建订单意图 */
export async function createOrderIntent(data: {
  portfolio_id: string;
  rebalance_plan_item_index?: number;
}): Promise<OrderIntent> {
  const res = await client.post<ApiResponse<OrderIntent>>('/orders', data);
  return res.data.data;
}

/** 提交仿真订单 */
export async function submitOrder(id: string): Promise<{
  execution_id: string;
  order_intent_id: string;
  status: string;
  fill_price: number;
  fee: number;
  slippage: number;
}> {
  const res = await client.post<ApiResponse<unknown>>(`/orders/${id}/submit`);
  return res.data.data as {
    execution_id: string;
    order_intent_id: string;
    status: string;
    fill_price: number;
    fee: number;
    slippage: number;
  };
}

/** 暂停所有策略 */
export async function pauseStrategies(reason = '用户主动暂停'): Promise<{ paused: boolean; reason: string }> {
  const res = await client.post<ApiResponse<{ paused: boolean; reason: string }>>('/strategies/pause', {
    reason,
  });
  return res.data.data;
}
