import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import { useAuthStore } from './stores/auth'
import { bootstrapApplication } from './bootstrap'
import './styles.css'

const app=createApp(App),pinia=createPinia();app.use(pinia);const auth=useAuthStore(pinia)
void bootstrapApplication({hasToken:Boolean(auth.token),hydrate:()=>auth.hydrate(),mount:()=>{app.use(createAppRouter());app.mount('#app')}})
