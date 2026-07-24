import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api'
import type { User } from '@/types/api'
const TOKEN='finance-god-token', USER='finance-god-user'
function storedUser():User|null{ try{return JSON.parse(localStorage.getItem(USER)||'null') as User|null}catch{return null} }
export const useAuthStore=defineStore('auth',()=>{
  const token=ref(localStorage.getItem(TOKEN)); const user=ref<User|null>(storedUser()); const loading=ref(false)
  const authenticated=computed(()=>Boolean(token.value&&user.value)); const isAdmin=computed(()=>user.value?.role==='admin')
  function persist(data:{access_token:string;user:User}){token.value=data.access_token;user.value=data.user;localStorage.setItem(TOKEN,data.access_token);localStorage.setItem(USER,JSON.stringify(data.user))}
  async function login(email:string,password:string){loading.value=true;try{persist(await authApi.login(email,password))}finally{loading.value=false}}
  async function register(email:string,password:string,name:string){loading.value=true;try{persist(await authApi.register(email,password,name))}finally{loading.value=false}}
  async function hydrate(){if(!token.value)return;try{user.value=await authApi.me();localStorage.setItem(USER,JSON.stringify(user.value))}catch{logout()}}
  async function updateProfile(payload:{display_name?:string|null;base_currency?:string;region?:string}){const updated=await authApi.updateMe(payload);user.value=updated;localStorage.setItem(USER,JSON.stringify(updated));return updated}
  function logout(){token.value=null;user.value=null;localStorage.removeItem(TOKEN);localStorage.removeItem(USER)}
  return{token,user,loading,authenticated,isAdmin,login,register,hydrate,updateProfile,logout}
})
