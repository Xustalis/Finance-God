import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import { useAuthStore } from './stores/auth'
import { useAdminAuthStore } from './stores/adminAuth'
import { bootstrapApplication } from './bootstrap'
import './styles.css'

const app=createApp(App),pinia=createPinia();app.use(pinia);const auth=useAuthStore(pinia),adminAuth=useAdminAuthStore(pinia)
void bootstrapApplication({sessions:[{hasToken:Boolean(auth.token),hydrate:()=>auth.hydrate()},{hasToken:Boolean(adminAuth.token),hydrate:()=>adminAuth.hydrate()}],mount:()=>{app.use(createAppRouter());app.mount('#app')}})
