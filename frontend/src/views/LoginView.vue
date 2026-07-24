<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, Landmark, LoaderCircle } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
const auth=useAuthStore(),router=useRouter(),route=useRoute();const registering=ref(false),email=ref(''),password=ref(''),name=ref(''),showPassword=ref(false),error=ref('')
async function submit(){error.value='';try{if(registering.value)await auth.register(email.value,password.value,name.value);else await auth.login(email.value,password.value);const redirect=typeof route.query.redirect==='string'?route.query.redirect:(auth.isAdmin?'/admin/ai-settings':'/app/exe');await router.replace(redirect)}catch(e){error.value=e instanceof Error?e.message:'认证失败，请稍后再试'}}
</script>
<template>
  <main class="auth-page">
    <section class="auth-brand" aria-labelledby="brand-title"><div class="brand-mark"><Landmark :size="26" /></div><p class="kicker">FINANCE GOD</p><h1 id="brand-title">看清自己的钱，<br>再决定它去哪里。</h1><p>一场克制、诚实的投资画像访谈。</p><blockquote>“好的决策，往往始于对自己边界的了解。”<cite>— 沈砚，价值投资导师</cite></blockquote></section>
    <section class="auth-form-wrap"><div class="auth-form-head"><p class="chapter">{{ registering?'新客入门':'故友归来' }}</p><h2>{{ registering?'创建账户':'登录' }}</h2><p>{{ registering?'建立你的第一份投资画像。':'继续上次未完成的访谈。' }}</p></div>
      <form class="form-stack" @submit.prevent="submit">
        <label v-if="registering">称呼<input v-model.trim="name" name="display-name" autocomplete="name" placeholder="你希望我们如何称呼你"></label>
        <label>邮箱<input v-model.trim="email" name="email" type="email" autocomplete="email" required placeholder="name@example.com"></label>
        <label>密码<span class="password-field"><input v-model="password" name="password" :type="showPassword?'text':'password'" minlength="8" autocomplete="current-password" required placeholder="至少 8 位"><button type="button" class="icon-button" :aria-label="showPassword?'隐藏密码':'显示密码'" :title="showPassword?'隐藏密码':'显示密码'" @click="showPassword=!showPassword"><EyeOff v-if="showPassword" :size="19"/><Eye v-else :size="19"/></button></span></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="primary-button" :disabled="auth.loading"><LoaderCircle v-if="auth.loading" class="spin" :size="19"/><span>{{ registering?'创建账户':'进入访谈' }}</span><ArrowRight v-if="!auth.loading" :size="19"/></button>
      </form>
      <button data-test="auth-mode" class="text-button auth-switch" @click="registering=!registering;error=''">{{ registering?'已有账户，返回登录':'还没有账户？创建一个' }}</button>
    </section>
  </main>
</template>
