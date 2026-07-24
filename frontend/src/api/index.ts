import { adminHttpApi, api } from './client'
import type { AISetting, AuthData, EditableAISetting, MessageTurn, ObjectiveProfile, ProfileDimension, ProfileWithRecommendations, Session, User } from '@/types/api'
import { adminUpdatePayload } from '@/services/admin'

export const authApi = {
  login:(email:string,password:string)=>api.post<AuthData>('/auth/login',{email,password}),
  register:(email:string,password:string,display_name:string)=>api.post<AuthData>('/auth/register',{email,password,display_name:display_name||null}),
  me:()=>api.get<User>('/auth/me'),
}
export const adminAuthApi = {
  login:(email:string,password:string)=>adminHttpApi.post<AuthData>('/auth/admin/login',{email,password}),
  me:()=>adminHttpApi.get<User>('/auth/me'),
}
export const onboardingApi = {
  current:()=>api.get<Session>('/onboarding/sessions/current'), create:()=>api.post<Session>('/onboarding/sessions'),
  saveObjective:(id:string,body:ObjectiveProfile)=>api.put<Session>(`/onboarding/sessions/${id}/objective-profile`,body),
  sendMessage:(id:string,body:{request_id?:string;content:string;input_mode?:'text'|'voice'})=>api.post<MessageTurn>(`/onboarding/sessions/${id}/messages`,body),
  skip:(id:string,dimension:ProfileDimension)=>api.post<Session>(`/onboarding/sessions/${id}/skip`,{dimension}),
  complete:(id:string)=>api.post<ProfileWithRecommendations>(`/onboarding/sessions/${id}/complete`),
}
export const profileApi = { latest:()=>api.get<ProfileWithRecommendations>('/profiles/me/latest'), select:(id:string,selected_direction:string)=>api.post(`/profiles/${id}/direction-selection`,{selected_direction}) }
export const adminApi = { list:()=>adminHttpApi.get<AISetting[]>('/admin/ai-settings'), update:(body:EditableAISetting)=>adminHttpApi.put<AISetting>('/admin/ai-settings',adminUpdatePayload(body)), test:(body:{capability:string;provider:string;model_name:string})=>adminHttpApi.post<{ok:boolean;adapter:string;credential_status:string}>('/admin/ai-settings/test',body) }
