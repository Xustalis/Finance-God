<template>
  <main class="rebuilding-page" aria-labelledby="rebuilding-title">
    <header class="app-header">
      <RouterLink class="wordmark" to="/app/profile-report">
        <span>策</span>Finance God
      </RouterLink>
    </header>
    <section class="rebuilding-content">
      <p class="chapter">产品更新</p>
      <h1 id="rebuilding-title">交易工作区正在重构</h1>
      <p>行情、持仓、订单与交易工具暂不可用。已保存的画像方向会保留，新的交易工作区完成后将从该配置继续。</p>
      <RouterLink class="primary-button" to="/app/profile-report">返回画像报告</RouterLink>
    </section>
  </main>
</template>

<style scoped>
.rebuilding-page { min-height: 100vh; background: var(--paper); color: var(--ink); }
.rebuilding-content { max-width: 720px; margin: clamp(5rem, 18vh, 12rem) auto; padding: 0 1.5rem; }
.rebuilding-content h1 { margin: .5rem 0 1rem; font-size: clamp(2rem, 5vw, 3.4rem); }
.rebuilding-content p:not(.chapter) { max-width: 56ch; color: var(--muted-ink); line-height: 1.8; margin-bottom: 2rem; }
</style>
