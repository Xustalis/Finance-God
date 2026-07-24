import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { onboardingApi } from '@/api'
import { ApiClientError } from '@/api/client'
import type { InputMode, ObjectiveProfile, Session } from '@/types/api'

type StepKey=keyof ObjectiveProfile
export interface Choice{value:string|number;label:string;hint?:string}
export interface ObjectiveStep{key:StepKey;title:string;eyebrow:string;choices:Choice[]}
const range=(prefix:'A'|'I',labels:string[])=>labels.map((label,i)=>({value:`${prefix}${i+1}`,label}))
export const objectiveSteps:ObjectiveStep[]=[
  {key:'gender',eyebrow:'第一章 · 关于你',title:'你希望如何被称呼？',choices:[{value:'male',label:'男士'},{value:'female',label:'女士'},{value:'nonbinary',label:'其他'},{value:'prefer_not_to_say',label:'暂不回答'}]},
  {key:'age_range',eyebrow:'第二章 · 人生阶段',title:'你目前处于哪个年龄阶段？',choices:['未成年','18–25岁','26–35岁','36–45岁','46–55岁','56–65岁','65岁以上'].map((label,i)=>({label,value:['minor','18-25','26-35','36-45','46-55','56-65','65+'][i]}))},
  {key:'asset_level',eyebrow:'第三章 · 可用资源',title:'可用于投资的资金大致是？',choices:range('A',['1万元以内','1–5万元','5–10万元','10–30万元','30–50万元','50–100万元','100–300万元','300–500万元','500–1000万元','1000万元以上'])},
  {key:'employment_status',eyebrow:'第四章 · 收入节奏',title:'你目前的工作状态？',choices:[['employed','受雇工作'],['self_employed','自由职业 / 经营'],['unemployed','暂未工作'],['student','学生'],['retired','退休'],['other','其他']].map(([value,label])=>({value,label}))},
  {key:'income_range',eyebrow:'第五章 · 现金流',title:'个人年收入大致是？',choices:range('I',['5万元以内','5–10万元','10–20万元','20–30万元','30–50万元','50–80万元','80–120万元','120–200万元','200–500万元','500万元以上'])},
  {key:'debt_pressure',eyebrow:'第六章 · 负担',title:'债务对日常生活的压力？',choices:[['none','没有压力'],['low','较低'],['moderate','需要留意'],['high','压力较大']].map(([value,label])=>({value,label}))},
  {key:'emergency_fund_months',eyebrow:'第七章 · 安全垫',title:'应急资金能覆盖多久开支？',choices:[0,1,3,6,12,24].map(value=>({value,label:value===0?'尚未准备':`${value}个月${value===24?'以上':''}`}))},
  {key:'investment_experience',eyebrow:'第八章 · 过往经验',title:'你已有多少投资经历？',choices:[['none','尚未开始'],['beginner','少量尝试'],['intermediate','有系统经验'],['advanced','经验丰富']].map(([value,label])=>({value,label}))},
  {key:'fund_horizon',eyebrow:'第九章 · 时间',title:'这笔资金预计多久不会使用？',choices:[['under_1_year','1年以内'],['1_3_years','1–3年'],['3_5_years','3–5年'],['5_plus_years','5年以上']].map(([value,label])=>({value,label}))},
  {key:'loss_reaction',eyebrow:'第十章 · 波动',title:'如果短期亏损 15%，你更可能？',choices:[['sell_all','全部卖出'],['reduce','减少仓位'],['hold','保持不动'],['buy_more','分批增加']].map(([value,label])=>({value,label}))},
]
const makeId=()=>globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random()}`
export const useOnboardingStore=defineStore('onboarding',()=>{
  const session=ref<Session|null>(null), objectiveIndex=ref(0), objective=ref<Partial<ObjectiveProfile>>({}), messages=ref<{role:'user'|'assistant';content:string}[]>([]), busy=ref(false), error=ref('')
  let client=onboardingApi
  let pendingContent:{content:string;inputMode:InputMode;requestId:string}|null=null
  const currentObjective=computed(()=>objectiveSteps[objectiveIndex.value]); const objectiveComplete=computed(()=>objectiveSteps.every(s=>objective.value[s.key]!==undefined))
  function configureApi(api:typeof onboardingApi){client=api}
  const draftKey=()=>session.value?`finance-god-objective:${session.value.user_id}:${session.value.id}`:null
  const messagesKey=()=>session.value?`finance-god-messages:${session.value.user_id}:${session.value.id}`:null
  function persistDraft(){const key=draftKey();if(key)localStorage.setItem(key,JSON.stringify({objective:objective.value,index:objectiveIndex.value}))}
  function loadDraft(){const key=draftKey();if(!key)return;try{const saved=JSON.parse(localStorage.getItem(key)||'null') as {objective?:Partial<ObjectiveProfile>;index?:number}|null;if(saved){objective.value=saved.objective||{};objectiveIndex.value=Math.max(0,Math.min(9,saved.index||0))}}catch{localStorage.removeItem(key)}}
  function persistMessages(){const key=messagesKey();if(key)localStorage.setItem(key,JSON.stringify(messages.value))}
  function loadMessages(){const key=messagesKey();if(!key)return;try{const saved=JSON.parse(localStorage.getItem(key)||'[]') as {role:'user'|'assistant';content:string}[];messages.value=Array.isArray(saved)?saved:[]}catch{localStorage.removeItem(key);messages.value=[]}}
  function clearMemory(){objective.value={};objectiveIndex.value=0;messages.value=[];pendingContent=null}
  function reset(){const objectiveStorage=draftKey(),messageStorage=messagesKey();if(objectiveStorage)localStorage.removeItem(objectiveStorage);if(messageStorage)localStorage.removeItem(messageStorage);clearMemory();session.value=null;error.value='';busy.value=false}
  async function restore(){busy.value=true;error.value='';try{let next:Session;try{next=await client.current()}catch(e){if(!(e instanceof ApiClientError)||e.status!==404)throw e;next=await client.create()}if(session.value&&(session.value.id!==next.id||session.value.user_id!==next.user_id))clearMemory();session.value=next;if(next.objective_profile)objective.value={...next.objective_profile};else if(next.step==='objective_profile')loadDraft();loadMessages();return session.value}finally{busy.value=false}}
  function selectObjective(value:string|number){const step=currentObjective.value;if(!step)return;(objective.value as Record<string,unknown>)[step.key]=value;if(objectiveIndex.value<objectiveSteps.length-1)objectiveIndex.value++;persistDraft()}
  function previousObjective(){objectiveIndex.value=Math.max(0,objectiveIndex.value-1);persistDraft()}
  async function submitObjective(){if(!session.value||!objectiveComplete.value)throw new Error('请完成全部客观信息');busy.value=true;try{const key=draftKey();session.value=await client.saveObjective(session.value.id,objective.value as ObjectiveProfile);if(key)localStorage.removeItem(key)}finally{busy.value=false}}
  async function sendContent(content:string,input_mode:InputMode='text'){if(!session.value)throw new Error('会话尚未建立');busy.value=true;error.value='';const retry=pendingContent?.content===content&&pendingContent.inputMode===input_mode?pendingContent:{content,inputMode:input_mode,requestId:makeId()};pendingContent=retry;try{const result=await client.sendMessage(session.value.id,{request_id:retry.requestId,content,input_mode});pendingContent=null;session.value=result.session;messages.value.push({role:'user',content:result.user_message.content},{role:'assistant',content:result.assistant_message.content});persistMessages();return result}catch(e){error.value=e instanceof Error?e.message:'对话暂时不可用';throw e}finally{busy.value=false}}
  async function skipCurrent(){if(session.value?.current_dimension!=='income_stability')throw new Error('当前问题不能跳过');busy.value=true;try{session.value=await client.skip(session.value.id,'income_stability')}finally{busy.value=false}}
  async function complete(){if(!session.value)throw new Error('会话尚未建立');busy.value=true;try{return await client.complete(session.value.id)}finally{busy.value=false}}
  return{session,objectiveIndex,objective,messages,busy,error,currentObjective,objectiveComplete,configureApi,restore,reset,persistMessages,selectObjective,previousObjective,submitObjective,sendContent,skipCurrent,complete}
})
