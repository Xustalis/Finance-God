export type UserRole = 'user' | 'admin'
export type Capability = 'text' | 'stt' | 'tts'
export type ProfileDimension = 'risk_tolerance' | 'liquidity_need' | 'investment_goal' | 'loss_behavior' | 'investment_knowledge' | 'income_stability'
export type InvestmentDirection = 'cash_fixed_income' | 'public_funds' | 'equities' | 'alternatives' | 'long_term_insurance'
export type InputMode = 'text' | 'voice'

export interface ApiEnvelope<T> { success: boolean; data: T | null; error: { code:string; message:string; details?:unknown } | null; meta: { request_id:string|null } }
export interface User { id: string; email: string; display_name?: string | null; base_currency?: string; region?: string; role: UserRole; status: string; created_at?: string; last_login_at?: string | null }
export interface AuthData { access_token: string; token_type: string; user: User }

export interface ObjectiveProfile {
  gender: 'male' | 'female' | 'nonbinary' | 'prefer_not_to_say'
  age_range: 'minor' | '18-25' | '26-35' | '36-45' | '46-55' | '56-65' | '65+'
  asset_level: `A${1|2|3|4|5|6|7|8|9|10}`
  employment_status: 'employed' | 'self_employed' | 'unemployed' | 'student' | 'retired' | 'other'
  income_range: `I${1|2|3|4|5|6|7|8|9|10}`
  debt_pressure: 'none' | 'low' | 'moderate' | 'high'
  emergency_fund_months: number
  investment_experience: 'none' | 'beginner' | 'intermediate' | 'advanced'
  fund_horizon: 'under_1_year' | '1_3_years' | '3_5_years' | '5_plus_years'
  loss_reaction: 'sell_all' | 'reduce' | 'hold' | 'buy_more'
}
export interface PendingEvidence { dimension: ProfileDimension; value: number | null; confidence: number; proposed_followup_count: number; proposed_round_count: number; should_continue: boolean; end_reason: string | null }
export interface Session {
  id: string; user_id: string; step: 'objective_profile'|'conversation'|'ready'|'report'; status: 'active'|'ready'|'completed'
  round_count: number; turn_count: number; row_version: number; min_rounds: number; max_rounds: number; completeness: number
  provider_name: string; model_name: string; prompt_version: string; prompt_id: string|null; prompt_hash: string
  objective_profile: ObjectiveProfile|null; dimension_scores: Partial<Record<ProfileDimension, number>>; profile_evidence: Partial<Record<ProfileDimension, number>>
  pending_profile_evidence: PendingEvidence|null; skipped_dimensions: ProfileDimension[]; followup_counts: Partial<Record<ProfileDimension, number>>; current_dimension: ProfileDimension|null
  current_question: string|null
}
export interface MessageTurn { session: Session; user_message: {id:string;content:string;input_mode:InputMode}; assistant_message:{id:string;content:string}; turn:{reply:string;target_dimension:ProfileDimension;sensitive:boolean;confidence:number;should_continue:boolean;end_reason:string|null} }
export interface EvidenceConfirmation { session: Session; accepted: boolean; confirmed_evidence: Partial<Record<ProfileDimension, number>> }
export interface Recommendation { id:string; direction:InvestmentDirection; score:number; rank:number; reason:string; actionable:boolean; selected:boolean }
export interface Profile { id:string; user_id:string; session_id:string; version:number; objective_profile:ObjectiveProfile; archetype_code:string; archetype_title:string; risk_level:'conservative'|'moderate'|'growth'; loss_tolerance_percent:number; confidence:number; completeness:number; education_only:boolean; dimension_scores:Record<string,number|null>; profile_evidence:Partial<Record<ProfileDimension,number>>; report_summary:{traits:string[];risk_notice:string;reasoning:string[];low_confidence:ProfileDimension[]} }
export interface ProfileWithRecommendations { profile: Profile; recommendations: Recommendation[] }
export interface AISetting { id:string|null; capability:Capability; provider:string; model_name:string; api_key_configured:boolean; prompt_version:string; min_rounds:number; max_rounds:number; enabled:boolean; version:number }
export interface EditableAISetting extends Omit<AISetting,'api_key_configured'> { api_key_ref:string; clear_api_key_ref:boolean; prompt_content:string; api_key_configured:boolean }
export interface AISettingsUpdateRequest { capability:Capability;provider:string;model_name:string;api_key_ref?:string|null;prompt_version:string;prompt_content:string|null;min_rounds:number;max_rounds:number;enabled:boolean }
