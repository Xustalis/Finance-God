import client from './client';
import type { ApiResponse, AgentStatus, DashboardData, RiskEvent, PageResponse } from '../types';

export interface RiskEventParams {
  severity?: string;
  category?: string;
  disposition?: string;
  page?: number;
  page_size?: number;
}

/** 获取仪表盘聚合数据 */
export async function getDashboard(): Promise<DashboardData> {
  const res = await client.get<ApiResponse<DashboardData>>('/dashboard');
  return res.data.data;
}

/** 获取 Agent 列表状态 */
export async function getAgents(): Promise<AgentStatus[]> {
  const res = await client.get<ApiResponse<AgentStatus[]>>('/agents');
  return res.data.data;
}

/** 查询风险事件列表 */
export async function getRiskEvents(params: RiskEventParams = {}): Promise<PageResponse<RiskEvent>> {
  const res = await client.get<ApiResponse<RiskEvent[]>>('/risk-events', {
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
