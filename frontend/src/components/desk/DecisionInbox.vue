<script setup lang="ts">
/**
 * DecisionInbox — 决策收件箱（T01 总览）
 * 聚合订单异常与未读通知，按 P0–P3 优先级排序展示。
 * 每条都来自真实订单或真实通知，不在前端派生或伪造待办；
 * 请求失败以显式错误态呈现，绝不将失败当作“无待办”。
 */
import { ref, computed, onMounted } from 'vue'
import { fetchDecisionInbox } from '@/api/desk'
import type { DecisionInboxView, DecisionInboxItem, DecisionPriority } from '@/types/desk'

const inbox = ref<DecisionInboxView | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const PRIORITY_LABELS: Record<DecisionPriority, string> = {
  P0: '紧急',
  P1: '待处理',
  P2: '需关注',
  P3: '提示',
}

/** action_route 契约值 → 前端路由路径。 */
const ROUTE_PATHS: Record<string, string> = {
  orders: '/orders',
  portfolio: '/portfolio',
  overview: '/overview',
}
function routePath(route: string | null): string | null {
  return route ? (ROUTE_PATHS[route] ?? null) : null
}

const items = computed<DecisionInboxItem[]>(() => inbox.value?.items ?? [])
const counts = computed(() => inbox.value?.counts ?? null)

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN')
}

async function load() {
  loading.value = true
  error.value = null
  try {
    inbox.value = await fetchDecisionInbox()
  } catch (e) {
    inbox.value = null
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section class="inbox">
    <h2 class="inbox-heading">
      <span>决策收件箱</span>
      <small>DECISION INBOX</small>
    </h2>
    <p class="inbox-note">聚合订单异常与未读通知；仿真账户事实，非行情。</p>

    <div v-if="counts" class="count-strip">
      <span class="count p0" :class="{ zero: counts.p0 === 0 }">紧急 {{ counts.p0 }}</span>
      <span class="count p1" :class="{ zero: counts.p1 === 0 }">待处理 {{ counts.p1 }}</span>
      <span class="count p2" :class="{ zero: counts.p2 === 0 }">需关注 {{ counts.p2 }}</span>
      <span class="count p3" :class="{ zero: counts.p3 === 0 }">提示 {{ counts.p3 }}</span>
    </div>

    <div v-if="loading" class="inbox-state" role="status">加载收件箱…</div>
    <div v-else-if="error" class="inbox-state error" role="alert">
      <strong>收件箱不可用</strong>
      <span>{{ error }}</span>
      <button class="secondary-button compact" @click="load">重试</button>
    </div>
    <div v-else-if="items.length === 0" class="inbox-state">
      <span>暂无需要处理的事项。</span>
    </div>
    <ul v-else class="inbox-list">
      <li
        v-for="item in items"
        :key="item.item_id"
        class="inbox-item"
        :class="`prio-${item.priority.toLowerCase()}`"
      >
        <div class="item-head">
          <span class="prio-tag" :class="`prio-${item.priority.toLowerCase()}`">
            {{ item.priority }} · {{ PRIORITY_LABELS[item.priority] }}
          </span>
          <span v-if="item.required" class="required-tag">需处理</span>
          <span class="item-time">{{ formatTime(item.occurred_at) }}</span>
        </div>
        <strong class="item-title">{{ item.title }}</strong>
        <p class="item-detail">{{ item.detail }}</p>
        <router-link
          v-if="routePath(item.action_route)"
          :to="routePath(item.action_route) as string"
          class="item-action"
        >
          前往处理 →
        </router-link>
      </li>
    </ul>

    <div class="inbox-refresh">
      <button class="secondary-button compact" :disabled="loading" @click="load">刷新收件箱</button>
    </div>
  </section>
</template>

<style scoped>
.inbox { padding: 18px 20px; border-bottom: 1px solid var(--rule); }

.inbox-heading {
  display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  margin: 0 0 6px; font-size: 15px; font-weight: 900; letter-spacing: 0.04em;
}
.inbox-heading small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em;
}
.inbox-note { margin: 0 0 12px; color: var(--muted-ink); font-size: 11px; line-height: 1.5; }

.count-strip { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.count {
  font-family: var(--font-numeric); font-size: 11px; font-weight: 800;
  padding: 2px 8px; border: 1px solid var(--rule);
}
.count.p0 { color: var(--risk); border-color: var(--risk); }
.count.p1 { color: var(--ink); }
.count.p2, .count.p3 { color: var(--muted-ink); border-color: var(--faint-rule); }
.count.zero { color: var(--muted-ink); border-color: var(--faint-rule); opacity: 0.6; }

.inbox-state {
  display: grid; gap: 8px; justify-items: start;
  padding: 14px 0; color: var(--muted-ink); font-size: 13px;
}
.inbox-state.error { color: var(--risk); }
.inbox-state strong { display: block; }

.inbox-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; }
.inbox-item {
  padding: 10px 0 10px 12px; border-bottom: 1px solid var(--faint-rule);
  border-left: 3px solid var(--faint-rule);
}
.inbox-item:last-child { border-bottom: 0; }
.inbox-item.prio-p0 { border-left-color: var(--risk); }
.inbox-item.prio-p1 { border-left-color: var(--ink); }

.item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.prio-tag {
  font-family: var(--font-numeric); font-size: 10px; font-weight: 800;
  letter-spacing: 0.04em;
}
.prio-tag.prio-p0 { color: var(--risk); }
.prio-tag.prio-p1 { color: var(--ink); }
.prio-tag.prio-p2, .prio-tag.prio-p3 { color: var(--muted-ink); }
.required-tag {
  font-size: 10px; font-weight: 800; color: var(--risk);
  border: 1px solid var(--risk); padding: 0 5px;
}
.item-time {
  margin-left: auto; font-family: var(--font-numeric);
  font-size: 10px; color: var(--muted-ink);
}
.item-title { display: block; font-size: 14px; font-weight: 700; }
.item-detail { margin: 3px 0 5px; font-size: 12px; color: var(--muted-ink); line-height: 1.5; }
.item-action {
  font-size: 12px; font-weight: 700; color: var(--ink);
  text-decoration: underline; text-underline-offset: 2px;
}
.item-action:hover { color: var(--risk); }

.inbox-refresh { margin-top: 12px; }
</style>
