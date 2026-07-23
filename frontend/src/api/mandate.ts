import client from './client';
import type { ApiResponse, InvestmentMandate } from '../types';

/** 获取当前有效授权书 */
export async function getActiveMandate(): Promise<InvestmentMandate | null> {
  const res = await client.get<ApiResponse<InvestmentMandate | null>>('/mandates/active');
  return res.data.data;
}

/** 创建授权书 */
export async function createMandate(data: Partial<InvestmentMandate> & { action?: string }): Promise<InvestmentMandate> {
  const res = await client.post<ApiResponse<InvestmentMandate>>('/mandates', data);
  return res.data.data;
}

/** 暂停授权书 */
export async function pauseMandate(id: string): Promise<{ id: string; status: string }> {
  const res = await client.post<ApiResponse<{ id: string; status: string }>>(`/mandates/${id}/pause`);
  return res.data.data;
}

/** 撤销授权书 */
export async function revokeMandate(id: string, reason = ''): Promise<{ id: string; status: string }> {
  const res = await client.post<ApiResponse<{ id: string; status: string }>>(`/mandates/${id}/revoke`, {
    reason,
  });
  return res.data.data;
}
