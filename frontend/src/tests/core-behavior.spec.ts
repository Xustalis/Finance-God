import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import { objectiveSteps, useOnboardingStore } from '@/stores/onboarding'
import { createSpeechController } from '@/composables/useSpeech'
import { emitProfileCompleted, saveAndEmitProfileCompleted } from '@/services/workbench'
import { ApiClientError, errorMessageFromEnvelope, unwrapEnvelope } from '@/api/client'
import { adminUpdatePayload } from '@/services/admin'
import { bootstrapApplication } from '@/bootstrap'
import { directionScore } from '@/services/profile'
import { resolveWorkbenchOrigin } from '../../config/env'
import { readFileSync } from 'node:fs'
import type { ProfileWithRecommendations, Session } from '@/types/api'

const baseSession = (): Session => ({
  id: 'session-1', user_id: 'user-1', step: 'conversation', status: 'active', round_count: 0,
  turn_count: 0, row_version: 1, min_rounds: 6, max_rounds: 12, completeness: 0.4,
  provider_name: 'mock', model_name: 'mock', prompt_version: 'v1', prompt_id: null,
  prompt_hash: 'a'.repeat(64), objective_profile: null, dimension_scores: {}, profile_evidence: {},
  pending_profile_evidence: null, skipped_dimensions: [], followup_counts: {}, current_dimension: 'risk_tolerance', current_question: '服务端固定问题',
})

describe('route permissions', () => {
  it('redirects unauthenticated users to login', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/app/exe')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('rejects a regular user from admin settings', async () => {
    localStorage.setItem('finance-god-token', 'token')
    localStorage.setItem('finance-god-user', JSON.stringify({ id: 'u', email: 'u@test.cn', role: 'user', status: 'active' }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/admin/ai-settings')
    await router.isReady()
    expect(router.currentRoute.value.fullPath).toContain('/app/exe')
    expect(router.currentRoute.value.query.notice).toBe('admin_required')
  })
})

describe('objective profile state', () => {
  it('moves through fixed choice steps and supports going back', () => {
    setActivePinia(createPinia())
    const store = useOnboardingStore()
    expect(objectiveSteps).toHaveLength(10)
    store.selectObjective('prefer_not_to_say')
    expect(store.objectiveIndex).toBe(1)
    store.previousObjective()
    expect(store.objectiveIndex).toBe(0)
    expect(store.objective.gender).toBe('prefer_not_to_say')
  })

  it('restores a per-session draft and only creates after a 404', async () => {
    setActivePinia(createPinia())
    const current = vi.fn().mockRejectedValue(new ApiClientError('missing', 404))
    const create = vi.fn().mockResolvedValue({ ...baseSession(), step: 'objective_profile', user_id: 'u7', id: 's7' })
    const store = useOnboardingStore(); store.configureApi({ current, create } as never)
    await store.restore(); store.selectObjective('prefer_not_to_say')
    setActivePinia(createPinia())
    const restored = useOnboardingStore(); restored.configureApi({ current: vi.fn().mockResolvedValue({ ...baseSession(), step: 'objective_profile', user_id: 'u7', id: 's7' }) } as never)
    await restored.restore()
    expect(restored.objective.gender).toBe('prefer_not_to_say'); expect(restored.objectiveIndex).toBe(1); expect(create).toHaveBeenCalledOnce()
  })

  it('does not create a session after non-404 restore failures', async () => {
    setActivePinia(createPinia()); const create=vi.fn();const store=useOnboardingStore();store.configureApi({current:vi.fn().mockRejectedValue(new ApiClientError('offline',503)),create} as never)
    await expect(store.restore()).rejects.toThrow('offline');expect(create).not.toHaveBeenCalled()
  })
  it('isolates drafts and messages when restoring another user session',async()=>{setActivePinia(createPinia());const first={...baseSession(),id:'s-a',user_id:'user-a',step:'objective_profile' as const};const second={...baseSession(),id:'s-b',user_id:'user-b',step:'objective_profile' as const};const current=vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second);const store=useOnboardingStore();store.configureApi({current} as never);await store.restore();store.selectObjective('prefer_not_to_say');store.messages.push({role:'user',content:'private-a'});store.persistMessages();await store.restore();expect(store.objective).toEqual({});expect(store.objectiveIndex).toBe(0);expect(store.messages).toEqual([]);store.reset();expect(store.session).toBeNull()})
})

describe('conversation evidence', () => {
  it('sends confirmation separately and blocks new content while evidence is pending', async () => {
    setActivePinia(createPinia())
    const sendMessage = vi.fn().mockResolvedValue({ session: { ...baseSession(), pending_profile_evidence: null }, accepted: true, confirmed_evidence: {} })
    const store = useOnboardingStore()
    store.session = { ...baseSession(), pending_profile_evidence: { dimension: 'risk_tolerance', value: 0.3, confidence: 0.8, proposed_followup_count: 1, proposed_round_count: 1, should_continue: true, end_reason: null } }
    store.configureApi({ sendMessage } as never)
    await expect(store.sendContent('下一条')).rejects.toThrow('请先确认')
    await store.confirmEvidence(true)
    expect(sendMessage).toHaveBeenCalledWith('session-1', expect.objectContaining({ confirm_pending: true, request_id: expect.any(String) }))
    expect(sendMessage.mock.calls[0][1]).not.toHaveProperty('content')
  })

  it('reuses the same confirmation request id after a failed attempt', async () => {
    setActivePinia(createPinia());const sendMessage=vi.fn().mockRejectedValueOnce(new Error('lost')).mockResolvedValueOnce({session:{...baseSession(),pending_profile_evidence:null},accepted:true,confirmed_evidence:{}});const store=useOnboardingStore();store.session={...baseSession(),pending_profile_evidence:{dimension:'risk_tolerance',value:.2,confidence:.8,proposed_followup_count:1,proposed_round_count:1,should_continue:true,end_reason:null}};store.configureApi({sendMessage} as never)
    await expect(store.confirmEvidence(true)).rejects.toThrow('lost');await store.confirmEvidence(true)
    expect(sendMessage.mock.calls[0][1].request_id).toBe(sendMessage.mock.calls[1][1].request_id)
  })

  it('reuses a content request id after a lost response', async () => {
    setActivePinia(createPinia());const result={session:{...baseSession(),pending_profile_evidence:{dimension:'risk_tolerance',value:.2,confidence:.8,proposed_followup_count:1,proposed_round_count:1,should_continue:true,end_reason:null}},user_message:{id:'u',content:'我能承受一些波动',input_mode:'text'},assistant_message:{id:'a',content:'收到'},turn:{reply:'收到'}};const sendMessage=vi.fn().mockRejectedValueOnce(new Error('lost')).mockResolvedValueOnce(result);const store=useOnboardingStore();store.session=baseSession();store.configureApi({sendMessage} as never)
    await expect(store.sendContent('我能承受一些波动')).rejects.toThrow('lost');await store.sendContent('我能承受一些波动');expect(sendMessage.mock.calls[0][1].request_id).toBe(sendMessage.mock.calls[1][1].request_id)
  })
})

describe('speech fallback', () => {
  it('falls back to text when browser recognition is unavailable', () => {
    const controller = createSpeechController({})
    expect(controller.recognitionAvailable).toBe(false)
    expect(controller.mode.value).toBe('text')
    expect(controller.startListening()).toBe(false)
  })
})

describe('workbench handoff', () => {
  it('posts once to a valid configured origin', () => {
    const postMessage = vi.fn()
    const parent={postMessage};const host={parent,opener:null} as never;const result = emitProfileCompleted(host, 'https://workbench.example.com/path', {
      profileId: 'p', sessionId: 's', selectedDirection: 'public_funds', archetypeCode: 'STEADY_GUARDIAN', riskLevel: 'moderate', completeness: 0.86,
    }, new Set())
    expect(result).toBe('sent')
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'FINANCE_GOD_PROFILE_COMPLETED' }), 'https://workbench.example.com')
  })

  it('does not post for invalid origins or duplicate saved selections', () => {
    const postMessage = vi.fn();const parent={postMessage};const host={parent,opener:null} as never
    const sent = new Set<string>()
    const payload = { profileId: 'p', sessionId: 's', selectedDirection: 'equities', archetypeCode: 'X', riskLevel: 'growth', completeness: 1 }
    expect(emitProfileCompleted(host, '*', payload, sent)).toBe('invalid_origin')
    expect(emitProfileCompleted(host, 'https://workbench.example', payload, sent)).toBe('sent')
    expect(emitProfileCompleted(host, 'https://workbench.example', payload, sent)).toBe('already_sent')
    expect(postMessage).toHaveBeenCalledTimes(1)
  })

  it('does not post to the current window when no parent or opener exists',()=>{const self={postMessage:vi.fn()} as any;self.parent=self;self.opener=null;expect(emitProfileCompleted(self,'https://workbench.example',{profileId:'p',sessionId:'s',selectedDirection:'equities',archetypeCode:'X',riskLevel:'growth',completeness:1},new Set())).toBe('no_target');expect(self.postMessage).not.toHaveBeenCalled()})
  it('suppresses only consecutive duplicates and emits A to B to A',()=>{const postMessage=vi.fn(),host={parent:{postMessage},opener:null} as never,sent=new Set<string>(),base={profileId:'p',sessionId:'s',archetypeCode:'X',riskLevel:'growth',completeness:1};expect(emitProfileCompleted(host,'https://workbench.example',{...base,selectedDirection:'equities'},sent)).toBe('sent');expect(emitProfileCompleted(host,'https://workbench.example',{...base,selectedDirection:'equities'},sent)).toBe('already_sent');expect(emitProfileCompleted(host,'https://workbench.example',{...base,selectedDirection:'public_funds'},sent)).toBe('sent');expect(emitProfileCompleted(host,'https://workbench.example',{...base,selectedDirection:'equities'},sent)).toBe('sent');expect(postMessage.mock.calls.map(call=>call[0].payload.selectedDirection)).toEqual(['equities','public_funds','equities'])})
  it('does not post when saving the selection fails',async()=>{const postMessage=vi.fn(),parent={postMessage},host={parent,opener:null} as never,payload={profileId:'p',sessionId:'s',selectedDirection:'equities',archetypeCode:'X',riskLevel:'growth',completeness:1};await expect(saveAndEmitProfileCompleted(()=>Promise.reject(new Error('save failed')),host,'https://workbench.example',payload,new Set())).rejects.toThrow('save failed');expect(postMessage).not.toHaveBeenCalled()})
})

describe('profile restrictions', () => {
  it('marks a minor report as education-only with no selectable directions', async () => {
    const { getSelectableDirections } = await import('@/services/profile')
    const result = { profile: { education_only: true }, recommendations: [{ direction: 'public_funds', actionable: false }] } as ProfileWithRecommendations
    expect(getSelectableDirections(result)).toEqual([])
  })
  it('localizes profile codes while preserving Chinese copy',async()=>{const {localizeArchetype,localizeDimension,localizeProfileText}=await import('@/services/profile');expect(localizeArchetype('STEADY_GUARDIAN','STEADY_GUARDIAN')).toBe('稳健守望者');expect(localizeDimension('income_stability')).toBe('收入稳定性');expect(localizeProfileText('risk_aware')).toBe('重视风险边界');expect(localizeProfileText('这笔钱五年内不会使用')).toBe('这笔钱五年内不会使用')})
  it('renders direction scores on the backend 0-100 scale',()=>{expect(directionScore(70)).toEqual({label:'70',percent:70});expect(directionScore(140).percent).toBe(100);expect(directionScore(-4).percent).toBe(0)})
})

describe('admin settings privacy', () => {
  it('never maps an API key value from the server response', async () => {
    const { editableSetting } = await import('@/services/admin')
    expect(editableSetting({ id: '1', capability: 'text', provider: 'mock', model_name: 'm', api_key_configured: true, prompt_version: 'v1', min_rounds: 6, max_rounds: 12, enabled: true, version: 1 })).toEqual(expect.objectContaining({ api_key_ref: '' }))
    expect(JSON.stringify(editableSetting({ id: null, capability: 'stt', provider: 'browser', model_name: 'speech', api_key_configured: false, prompt_version: 'v1', min_rounds: 6, max_rounds: 12, enabled: true, version: 0 }))).not.toContain('secret')
  })
  it('omits an unchanged configured key reference from updates',()=>{const payload=adminUpdatePayload({id:'1',capability:'text',provider:'mock',model_name:'m',api_key_configured:true,api_key_ref:'',clear_api_key_ref:false,prompt_version:'v2',prompt_content:'new prompt content here',min_rounds:6,max_rounds:12,enabled:true,version:2});expect(payload).not.toHaveProperty('api_key_ref')})
  it('omits an empty key reference even when no key is configured',()=>{const payload=adminUpdatePayload({id:null,capability:'stt',provider:'browser',model_name:'speech',api_key_configured:false,api_key_ref:'',clear_api_key_ref:false,prompt_version:'v1',prompt_content:'',min_rounds:6,max_rounds:12,enabled:true,version:0});expect(payload).not.toHaveProperty('api_key_ref')})
  it('supports preserve, replace, and explicit clear key states',()=>{const base={id:'1',capability:'text' as const,provider:'mock',model_name:'m',api_key_configured:true,api_key_ref:'',clear_api_key_ref:false,prompt_version:'v2',prompt_content:'new prompt content here',min_rounds:6,max_rounds:12,enabled:true,version:2};expect(adminUpdatePayload(base)).not.toHaveProperty('api_key_ref');expect(adminUpdatePayload({...base,api_key_ref:'NEW_KEY'}).api_key_ref).toBe('NEW_KEY');expect(adminUpdatePayload({...base,clear_api_key_ref:true}).api_key_ref).toBeNull()})
})

describe('application contract',()=>{
  it('provides the DOM mount target used by main',()=>{const html=readFileSync('index.html','utf8');expect(html).toContain('id="app"')})
  it('reads request ids from meta and error details',()=>{expect(errorMessageFromEnvelope({success:false,data:null,error:{code:'bad',message:'failed',details:{reason:'具体原因'}},meta:{request_id:'req-1'}})).toBe('failed：具体原因')})
  it('unwraps successful envelopes when request id is null',()=>{expect(unwrapEnvelope({success:true,data:{ok:true},error:null,meta:{request_id:null}})).toEqual({ok:true})})
  it('hydrates an existing token before mounting and contains hydrate failures',async()=>{const order:string[]=[];await bootstrapApplication({hasToken:true,hydrate:async()=>{order.push('hydrate');throw new Error('expired')},mount:()=>order.push('mount')});expect(order).toEqual(['hydrate','mount'])})
  it('resolves the workbench origin from either supported build variable',()=>{expect(resolveWorkbenchOrigin({VITE_WORKBENCH_ORIGIN:'https://vite.example',WORKBENCH_ORIGIN:'https://alias.example'})).toBe('https://vite.example');expect(resolveWorkbenchOrigin({WORKBENCH_ORIGIN:'https://alias.example'})).toBe('https://alias.example')})
})
