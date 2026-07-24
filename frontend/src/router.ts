import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

function authSnapshot(){
  const token=localStorage.getItem('finance-god-token')
  try{return{token,user:JSON.parse(localStorage.getItem('finance-god-user')||'null') as {role?:string}|null}}
  catch{return{token,user:null}}
}

export function createAppRouter(history:RouterHistory=createWebHistory()){
  const router=createRouter({history,routes:[
    {path:'/',redirect:()=>localStorage.getItem('finance-god-token')?'/app/exe':'/login'},
    {path:'/login',name:'login',component:()=>import('@/views/LoginView.vue')},
    {path:'/app/exe',name:'onboarding',component:()=>import('@/views/OnboardingView.vue'),meta:{requiresAuth:true}},
    {path:'/app/profile-report',name:'report',component:()=>import('@/views/ProfileReportView.vue'),meta:{requiresAuth:true}},
    {path:'/admin/ai-settings',name:'admin-settings',component:()=>import('@/views/AdminSettingsView.vue'),meta:{requiresAuth:true,requiresAdmin:true}},
    {path:'/:pathMatch(.*)*',redirect:'/'},
  ]})
  router.beforeEach((to)=>{const auth=authSnapshot();const authenticated=Boolean(auth.token&&auth.user);const isAdmin=auth.user?.role==='admin';if(to.meta.requiresAuth&&!authenticated)return{path:'/login',query:{redirect:to.fullPath}};if(to.meta.requiresAdmin&&!isAdmin)return{path:'/app/exe',query:{notice:'admin_required'}};if(to.path==='/login'&&authenticated)return isAdmin?'/admin/ai-settings':'/app/exe'})
  return router
}
