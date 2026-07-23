import client from './client';
import type { ApiResponse, UserProfile } from '../types';

/** 获取当前用户画像 */
export async function getProfile(): Promise<UserProfile | null> {
  const res = await client.get<ApiResponse<UserProfile | null>>('/profiles/me');
  return res.data.data;
}

/** 保存用户画像（创建新版本草稿） */
export async function saveProfile(data: Partial<UserProfile>): Promise<UserProfile> {
  const res = await client.post<ApiResponse<UserProfile>>('/profiles', data);
  return res.data.data;
}

/** 确认画像版本 */
export async function confirmProfile(version: number): Promise<UserProfile> {
  const res = await client.post<ApiResponse<UserProfile>>(`/profiles/${version}/confirm`);
  return res.data.data;
}
