import type { ProfileWithRecommendations, Recommendation } from '@/types/api'
export function getSelectableDirections(data:ProfileWithRecommendations):Recommendation[]{return data.profile.education_only?[]:data.recommendations.filter(item=>item.actionable)}
const dimensionNames:Record<string,string>={risk_tolerance:'风险承受意愿',liquidity_need:'流动性需求',investment_goal:'投资目标',loss_behavior:'亏损应对',investment_knowledge:'投资认知',income_stability:'收入稳定性'}
const archetypeNames:Record<string,string>={STEADY_GUARDIAN:'稳健守望者',BALANCED_NAVIGATOR:'均衡领航者',LONG_HORIZON_BUILDER:'长期筑梦者'}
const phraseNames:Record<string,string>={risk_aware:'重视风险边界',long_term:'着眼长期',liquidity_focused:'关注资金流动性',experienced:'具备投资经验',disciplined:'坚持投资纪律',steady_income:'收入节奏稳定',cautious:'决策审慎',balanced:'追求均衡'}
export function localizeDimension(value:string):string{return dimensionNames[value]||'尚待补充的信息'}
export function localizeArchetype(title:string,code:string):string{if(title&&/[\u4e00-\u9fff]/.test(title))return title;return archetypeNames[code]||'审慎探索者'}
export function localizeProfileText(value:string):string{if(/[\u4e00-\u9fff]/.test(value))return value;return phraseNames[value]||'仍在形成中的投资倾向'}
export function directionScore(score:number):{label:string;percent:number}{const value=Math.max(0,Math.min(100,Math.round(score)));return{label:String(value),percent:value}}
export const masterPortraits:Record<string,string>={market_growth:'/masters/bogle.jpg',value_return:'/masters/buffett.jpg',growth_discovery:'/masters/lynch.jpg',multi_asset:'/masters/dalio.jpg',trend_discipline:'/masters/seykota.jpg'}
export function masterInitial(name:string):string{return (name||'').replace(/[·・.\s]/g,'').slice(0,1)||'投'}
