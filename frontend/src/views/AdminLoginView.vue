<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, Landmark, LoaderCircle } from 'lucide-vue-next'
import { useAdminAuthStore } from '@/stores/adminAuth'

const auth = useAdminAuthStore(), router = useRouter(), route = useRoute()
const email = ref(''), password = ref(''), showPassword = ref(false), error = ref('')
async function submit() {
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    await router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/admin/ai-settings')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '管理员认证失败' }
}
</script>

<template><main class="auth-page admin-auth-page"><section class="auth-brand" aria-labelledby="admin-brand-title"><div class="brand-mark"><Landmark :size="26" /></div><p class="kicker">FINANCE GOD · ADMIN</p><h1 id="admin-brand-title">保持模型可控，<br>让每一次判断可追溯。</h1><p>独立管理会话，不影响当前用户登录。</p></section><section class="auth-form-wrap"><div class="auth-form-head"><p class="chapter">系统管理</p><h2>管理端登录</h2><p>仅限已授权管理员账户。</p></div><form class="form-stack" @submit.prevent="submit"><label>管理员邮箱<input v-model.trim="email" name="email" type="email" autocomplete="username" required></label><label>密码<span class="password-field"><input v-model="password" name="password" :type="showPassword?'text':'password'" autocomplete="current-password" required><button type="button" class="icon-button" :aria-label="showPassword?'隐藏密码':'显示密码'" :title="showPassword?'隐藏密码':'显示密码'" @click="showPassword=!showPassword"><EyeOff v-if="showPassword" :size="19"/><Eye v-else :size="19"/></button></span></label><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="auth.loading"><LoaderCircle v-if="auth.loading" class="spin" :size="19"/><span>进入管理端</span><ArrowRight v-if="!auth.loading" :size="19"/></button></form></section></main></template>
