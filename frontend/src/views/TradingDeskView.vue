<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTradingDeskStore, type DeskSection } from '@/stores/tradingDesk'
import { useDeskLayoutPreference } from '@/composables/useDeskLayoutPreference'
import DeskAgentPanel from '@/components/desk/DeskAgentPanel.vue'
import MyPanel from '@/components/desk/MyPanel.vue'
import OverviewWorkspace from '@/components/desk/OverviewWorkspace.vue'
import PortfolioWorkspace from '@/components/desk/PortfolioWorkspace.vue'
import WatchlistWorkspace from '@/components/desk/WatchlistWorkspace.vue'
import TradingWorkspace from '@/components/desk/TradingWorkspace.vue'

const desk = useTradingDeskStore()
const remindersOpen = ref(false)
const myOpen = ref(false)
const toastVisible = ref(false)
const workspaceError = ref<string | null>(null)
const spreadRef = ref<HTMLElement | null>(null)
const resizingAgent = ref(false)
const {
  preference: layout,
  storageError,
  layoutStatus,
  toggleAgent,
  setAgentWidth,
  moveTab,
  resetLayout,
} = useDeskLayoutPreference()

const sectionLabels: Record<DeskSection, string> = {
  information: '总览',
  portfolio: '持仓',
  watchlist: '自选',
  trading: '交易',
}
const sections = computed(() => layout.tabOrder.map((id) => ({ id, label: sectionLabels[id] })))
const spreadStyle = computed(() => ({ '--agent-width': `${layout.agentWidthPercent}%` }))

const firstUnread = computed(() => desk.notifications.find((item) => item.status !== 'read') ?? null)
const watchlistGroups = computed(() => (desk.watchlistGroups ?? []).map((group) => ({
  ...group,
  instruments: desk.watchlistInstruments[group.group_id] ?? [],
})))
let alertTimer: ReturnType<typeof setTimeout> | null = null

function failureText(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

async function runWorkspaceAction(action: () => Promise<unknown>): Promise<void> {
  workspaceError.value = null
  try { await action() } catch (error) { workspaceError.value = failureText(error) }
}

function startAgentResize(event: PointerEvent) {
  if (layout.agentCollapsed || window.innerWidth < 1024) return
  resizingAgent.value = true
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function resizeAgent(event: PointerEvent) {
  if (!resizingAgent.value || !spreadRef.value) return
  const bounds = spreadRef.value.getBoundingClientRect()
  const widthPercent = ((bounds.right - event.clientX) / bounds.width) * 100
  setAgentWidth(widthPercent, false, false)
}

function finishAgentResize(event: PointerEvent) {
  if (!resizingAgent.value) return
  resizingAgent.value = false
  const target = event.currentTarget as HTMLElement
  if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId)
  setAgentWidth(layout.agentWidthPercent, true)
}

function resizeAgentWithKeyboard(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight' && event.key !== 'Home') return
  event.preventDefault()
  if (event.key === 'Home') {
    setAgentWidth(50, true)
    return
  }
  const direction = event.key === 'ArrowLeft' ? 2 : -2
  setAgentWidth(layout.agentWidthPercent + direction, true)
}

async function createDraft(input: { instrumentId: string; side: 'buy' | 'sell'; orderType: 'market' | 'limit'; quantity: string; limitPrice: string | null }) {
  if (!desk.account) throw new Error('请先建立仿真账户。')
  const instrumentId = input.instrumentId.trim().toUpperCase()
  // 行情缓存未覆盖的标的向服务端实时查询真实快照，而不是直接拒绝。
  const quote = await desk.ensureQuote(instrumentId)
  if (!quote || quote.last === null) throw new Error('该标的没有可用的真实行情，无法创建引用价格明确的订单草稿。')
  // 收盘时段的 stale 快照仍是带上游时间的真实行情，可作为仿真引用价；仅在状态不可识别时拒绝。
  if (!['in_session', 'released', 'closed'].includes(quote.market_status)) {
    throw new Error(`该标的行情状态为 ${quote.market_status}，请等待服务端提供已发布的行情后再创建草稿。`)
  }
  await desk.createDraft({
    mode: 'manual', account_id: desk.account.account_id, instrument_id: instrumentId,
    side: input.side, order_type: input.orderType, quantity: input.quantity,
    limit_price: input.limitPrice ?? undefined, reference_price: String(quote.last),
    time_in_force: 'day', valid_until: new Date(Date.now() + 15 * 60_000).toISOString(),
    input_versions: [{ object_type: 'market_quote', object_id: quote.symbol, version: quote.provider_time }],
  })
}

async function loadWatchlistWorkspace(): Promise<void> {
  await Promise.all([desk.loadWatchlists(), desk.loadCandidates()])
}

onMounted(() => { void desk.initialize() })
watch(firstUnread, (notice) => {
  if (alertTimer) clearTimeout(alertTimer)
  toastVisible.value = Boolean(notice)
  if (notice) alertTimer = setTimeout(() => { toastVisible.value = false }, 8_000)
}, { immediate: true })
onBeforeUnmount(() => {
  if (alertTimer) clearTimeout(alertTimer)
  desk.dispose()
})
</script>

<template>
  <main class="desk-page" aria-label="Finance God 交易台">
    <header class="desk-topbar">
      <RouterLink class="desk-wordmark" to="/desk" aria-label="FINANCE GOD 交易台">
        <strong>FINANCE GOD</strong><span>金融教父 · 投研与决策档案</span>
      </RouterLink>
      <div class="topbar-actions editorial-actions">
        <button class="topbar-text-button" type="button" aria-label="打开提醒" @click="remindersOpen = !remindersOpen">
          <span>提醒</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M9.5 21h5"/></svg><sup v-if="desk.unreadCount">{{ desk.unreadCount }}</sup>
        </button>
        <span class="topbar-divider" aria-hidden="true"></span>
        <button class="topbar-text-button" type="button" aria-label="打开我的" @click="myOpen = !myOpen">
          <span>我的</span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M4.5 21c.8-4 3.4-6 7.5-6s6.7 2 7.5 6"/></svg>
        </button>
      </div>
    </header>

    <section
      ref="spreadRef"
      class="desk-spread"
      :class="{ 'agent-collapsed': layout.agentCollapsed, 'is-resizing': resizingAgent }"
      :style="spreadStyle"
    >
      <section class="desk-left" aria-label="信息与交易工作区">
        <div class="desk-workspace-bar">
          <nav class="desk-nav" aria-label="交易台工作区">
            <button v-for="item in sections" :key="item.id" type="button" :class="{ active: desk.section === item.id }" @click="desk.setSection(item.id)">{{ item.label }}</button>
          </nav>
          <details class="layout-menu">
            <summary aria-label="调整工作区布局">布局</summary>
            <div class="layout-menu-content">
              <header><strong>工作区布局</strong><small>偏好保存在当前浏览器</small></header>
              <button type="button" class="layout-agent-toggle" @click="toggleAgent">
                {{ layout.agentCollapsed ? '展开 Agent 面板' : '收起 Agent 为 rail' }}
              </button>
              <label>
                <span>Agent 宽度</span>
                <output>{{ layout.agentWidthPercent }}%</output>
                <input
                  type="range"
                  min="32"
                  max="60"
                  step="1"
                  :value="layout.agentWidthPercent"
                  :disabled="layout.agentCollapsed"
                  @input="setAgentWidth(Number(($event.target as HTMLInputElement).value), true)"
                >
              </label>
              <ol aria-label="工作区标签顺序">
                <li v-for="(item, index) in sections" :key="item.id">
                  <span>{{ item.label }}</span>
                  <button type="button" :disabled="index === 0" :aria-label="`${item.label}左移`" @click="moveTab(item.id, -1)">←</button>
                  <button type="button" :disabled="index === sections.length - 1" :aria-label="`${item.label}右移`" @click="moveTab(item.id, 1)">→</button>
                </li>
              </ol>
              <button type="button" class="layout-reset" @click="resetLayout">重置布局</button>
              <p v-if="storageError" class="data-error" role="alert">{{ storageError }}</p>
              <p v-else-if="layoutStatus" class="layout-status" role="status">{{ layoutStatus }}</p>
            </div>
          </details>
        </div>

        <div class="desk-left-content">
          <OverviewWorkspace
            v-if="desk.section === 'information'"
            :quotes="desk.quotes ?? []" :bars="desk.bars ?? []" :selected-symbol="desk.symbol" :loading="desk.loadingMarket" :market-error="desk.marketError" :bars-error="desk.barsError ?? null"
            :sentiment-facts="desk.sentimentFacts" :sentiment-error="desk.sentimentFactsError"
            :information-facts="desk.informationFacts" :information-error="desk.informationFactsError"
            :on-select-symbol="desk.setSymbol" :on-refresh="() => desk.refreshMarket({ withBars: true })"
            :on-period-change="(p: string) => desk.setBarsFrequency(p === 'daily' ? undefined : '1m')"
          />
          <PortfolioWorkspace
            v-else-if="desk.section === 'portfolio'"
            :account="desk.account ?? null" :portfolio="desk.portfolio ?? null" :quotes="desk.quotes ?? []" :loading="desk.loadingSimulation"
            :error="workspaceError || desk.simulationError" :on-load="desk.loadSimulationData"
            :on-create-account="(initialCash) => runWorkspaceAction(() => desk.createAccount(initialCash))"
          />
          <WatchlistWorkspace
            v-else-if="desk.section === 'watchlist'"
            :groups="watchlistGroups" :candidates="desk.candidates?.candidates ?? []"
            :loading="desk.loadingWatchlists || desk.loadingCandidates" :watchlist-error="workspaceError || desk.watchlistError" :candidate-error="desk.candidateError"
            :on-load="loadWatchlistWorkspace"
            :on-create-group="(input) => runWorkspaceAction(() => desk.createWatchlist(input.name, input.description))"
            :on-rename-group="(input) => runWorkspaceAction(async () => { const group = desk.watchlistGroups.find((item) => item.group_id === input.groupId); if (!group || group.revision !== input.expectedRevision) throw new Error('分组已被更新，请刷新后再试。'); await desk.renameWatchlist(group, input.name, input.description) })"
            :on-delete-group="(input) => runWorkspaceAction(async () => { const group = desk.watchlistGroups.find((item) => item.group_id === input.groupId); if (!group || group.revision !== input.expectedRevision) throw new Error('分组已被更新，请刷新后再试。'); await desk.removeWatchlist(group) })"
            :on-add-instrument="(input) => runWorkspaceAction(() => desk.addToWatchlist(input.groupId, input.instrumentId))"
            :on-remove-instrument="(input) => runWorkspaceAction(() => desk.removeFromWatchlist(input.groupId, input.instrumentId))"
            :on-ignore-candidate="(input) => runWorkspaceAction(() => desk.ignoreCandidate(input.instrumentId, input.reason, input.note))"
          />
          <TradingWorkspace
            v-else
            :account="desk.account ?? null" :selected-symbol="desk.symbol" :draft="desk.activeDraft ?? null" :receipt="desk.activeOrder ?? null"
            :loading="desk.loadingSimulation" :error="workspaceError || desk.tradeError || desk.simulationError" :on-load="desk.loadSimulationData"
            :on-create-draft="(input) => runWorkspaceAction(() => createDraft(input))"
            :on-review-draft="() => runWorkspaceAction(() => desk.reviewDraft())"
            :on-confirm-soft-risk="(input) => runWorkspaceAction(() => desk.acknowledgeSoftRisk(input.reasonHash))"
            :on-confirm-draft="(input) => runWorkspaceAction(() => desk.confirmDraft(input.summaryHash))"
            :on-submit-draft="() => runWorkspaceAction(() => desk.submitDraft())"
          />
        </div>
      </section>

      <button
        v-if="!layout.agentCollapsed"
        class="desk-resizer"
        type="button"
        role="separator"
        aria-label="调整 Agent 面板宽度"
        aria-orientation="vertical"
        :aria-valuemin="32"
        :aria-valuemax="60"
        :aria-valuenow="layout.agentWidthPercent"
        @pointerdown="startAgentResize"
        @pointermove="resizeAgent"
        @pointerup="finishAgentResize"
        @pointercancel="finishAgentResize"
        @keydown="resizeAgentWithKeyboard"
      ></button>
      <DeskAgentPanel :collapsed="layout.agentCollapsed" @toggle="toggleAgent" @reset-layout="resetLayout" />
    </section>

    <aside v-if="remindersOpen" class="reminder-panel" aria-label="提醒记录"><header><h2>提醒记录</h2><button type="button" @click="remindersOpen = false">关闭</button></header><p v-if="desk.notificationError" class="data-error">{{ desk.notificationError }}</p><p v-else-if="!desk.notifications.length">暂无服务端提醒。</p><ol v-else><li v-for="notice in desk.notifications" :key="notice.notification_id"><strong>{{ notice.title }}</strong><p>{{ notice.message }}</p><small>{{ notice.created_at }}</small><button type="button" @click="desk.dismissNotification(notice)">标记已读</button></li></ol></aside>
    <aside v-if="toastVisible && firstUnread && !remindersOpen" class="alert-toast" role="status"><strong>{{ firstUnread.title }}</strong><p>{{ firstUnread.message }}</p><button type="button" @click="remindersOpen = true">查看记录</button><button type="button" @click="desk.dismissNotification(firstUnread)">关闭</button></aside>

    <MyPanel v-if="myOpen" @close="myOpen = false" />
  </main>
</template>
