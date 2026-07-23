import client from './client';
import type { ApiResponse, StrategyProposal, TargetPortfolio } from '../types';

/** 生成策略方案 */
export async function getStrategy(mandateId: string): Promise<StrategyProposal> {
  const res = await client.post<ApiResponse<StrategyProposal>>('/strategies', {
    mandate_id: mandateId,
  });
  return res.data.data;
}

/** 生成目标组合 */
export async function getTargetPortfolio(strategyId: string): Promise<TargetPortfolio> {
  const res = await client.post<ApiResponse<TargetPortfolio>>('/target-portfolios', {
    strategy_proposal_id: strategyId,
  });
  return res.data.data;
}
