import client from './client';
import type { ApiResponse, HoldingSnapshot } from '../types';

/** 获取当前持仓快照 */
export async function getCurrentHoldings(): Promise<HoldingSnapshot | null> {
  const res = await client.get<ApiResponse<HoldingSnapshot | null>>('/holdings/current');
  return res.data.data;
}

/** 导入持仓 CSV */
export async function importHoldings(file: File): Promise<HoldingSnapshot> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await client.post<ApiResponse<HoldingSnapshot>>('/holdings/imports', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data.data;
}
