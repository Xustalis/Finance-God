<script setup lang="ts">
defineProps<{
  currentWidth: number
  minimumWidth: number
}>()
</script>

<template>
  <main class="desktop-width-notice" aria-labelledby="desktop-width-title" data-testid="desktop-width-notice">
    <section class="notice-copy">
      <p class="notice-kicker">桌面工作区</p>
      <h1 id="desktop-width-title">需要更宽的浏览器窗口</h1>
      <p>
        Finance-God 交易工作区最低支持 {{ minimumWidth }} px。当前窗口约为
        <strong>{{ currentWidth }} px</strong>，请扩大浏览器窗口或改用桌面设备。
      </p>
      <p class="notice-boundary">此处不提供移动交易布局。</p>
    </section>
  </main>
</template>

<style scoped>
.desktop-width-notice {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 32px 24px;
  border-top: 10px solid var(--ink);
  color: var(--ink);
  background: var(--paper);
}

.notice-copy {
  width: min(100%, 680px);
  padding-block: 28px;
  border-block: 1px solid var(--rule);
}

.notice-kicker {
  margin-bottom: 14px;
  color: var(--risk);
  font-size: 0.78rem;
  font-weight: 900;
  letter-spacing: 0.12em;
}

h1 {
  margin-bottom: 18px;
  font-size: clamp(2rem, 7vw, 3.5rem);
}

p {
  max-width: 58ch;
  margin-bottom: 12px;
}

.notice-boundary {
  margin-bottom: 0;
  font-weight: 800;
}
</style>
