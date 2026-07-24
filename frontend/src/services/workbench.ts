export interface CompletionPayload{profileId:string;sessionId:string;selectedDirection:string;archetypeCode:string;riskLevel:string;completeness:number}
export type HandoffStatus='sent'|'already_sent'|'invalid_origin'|'no_target'
function validOrigin(raw:string|undefined):string|null{if(!raw||raw==='*')return null;try{const url=new URL(raw);if(!['http:','https:'].includes(url.protocol))return null;return url.origin}catch{return null}}
type MessageTarget=Pick<Window,'postMessage'>
interface WindowHost extends MessageTarget{parent:WindowHost;opener:MessageTarget|null}
function resolveWorkbenchTarget(host:WindowHost):MessageTarget|null{try{if(host.parent&&host.parent!==host)return host.parent;if(host.opener)return host.opener}catch{return null}return null}
export function emitProfileCompleted(host:WindowHost,rawOrigin:string|undefined,payload:CompletionPayload,sent:Set<string>):HandoffStatus{
  const origin=validOrigin(rawOrigin);if(!origin)return'invalid_origin';const target=resolveWorkbenchTarget(host);if(!target)return'no_target';const key=`${payload.profileId}:${payload.selectedDirection}`;if(sent.has(key))return'already_sent'
  target.postMessage({type:'FINANCE_GOD_PROFILE_COMPLETED',schemaVersion:'1.0',payload},origin);sent.clear();sent.add(key);return'sent'
}
export async function saveAndEmitProfileCompleted(save:()=>Promise<unknown>,host:WindowHost,rawOrigin:string|undefined,payload:CompletionPayload,sent:Set<string>):Promise<HandoffStatus>{await save();return emitProfileCompleted(host,rawOrigin,payload,sent)}
