import { ref } from 'vue'
type RecognitionCtor=new()=>{lang:string;interimResults:boolean;continuous:boolean;start():void;stop():void;onresult:((event:any)=>void)|null;onerror:((event:any)=>void)|null;onend:(()=>void)|null}
interface SpeechEnv{webkitSpeechRecognition?:RecognitionCtor;SpeechRecognition?:RecognitionCtor;speechSynthesis?:SpeechSynthesis;SpeechSynthesisUtterance?:typeof SpeechSynthesisUtterance}
export function createSpeechController(env:SpeechEnv=globalThis as SpeechEnv){
  const Recognition=env.SpeechRecognition||env.webkitSpeechRecognition;const mode=ref<'text'|'voice'>(Recognition?'voice':'text');const listening=ref(false);const transcript=ref('');const error=ref('');const speaking=ref(true);let recognition:InstanceType<RecognitionCtor>|null=null
  function startListening(){if(!Recognition){mode.value='text';error.value='当前浏览器不支持语音识别，已切换为文字输入';return false}try{recognition=new Recognition();recognition.lang='zh-CN';recognition.interimResults=false;recognition.continuous=false;recognition.onresult=(event)=>{transcript.value=event.results[0][0].transcript;listening.value=false};recognition.onerror=()=>{mode.value='text';listening.value=false;error.value='语音识别未成功，已保留文字输入'};recognition.onend=()=>{listening.value=false};recognition.start();listening.value=true;return true}catch{mode.value='text';error.value='语音识别未成功，已切换为文字输入';return false}}
  function stopListening(){recognition?.stop();listening.value=false}
  function speak(text:string){if(!speaking.value||!env.speechSynthesis||!env.SpeechSynthesisUtterance)return;env.speechSynthesis.cancel();const utterance=new env.SpeechSynthesisUtterance(text);utterance.lang='zh-CN';env.speechSynthesis.speak(utterance)}
  function toggleSpeaking(){speaking.value=!speaking.value;if(!speaking.value)env.speechSynthesis?.cancel()}
  return{mode,listening,transcript,error,speaking,recognitionAvailable:Boolean(Recognition),startListening,stopListening,speak,toggleSpeaking}
}
