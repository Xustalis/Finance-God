<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTradingDeskStore, type DeskSection } from '@/stores/tradingDesk'
import DeskAgentPanel from '@/components/desk/DeskAgentPanel.vue'
import OverviewWorkspace from '@/components/desk/OverviewWorkspace.vue'

const MyPanel = defineAsyncComponent(() => import('@/components/desk/MyPanel.vue'))
const PortfolioWorkspace = defineAsyncComponent(() => import('@/components/desk/PortfolioWorkspace.vue'))
const WatchlistWorkspace = defineAsyncComponent(() => import('@/components/desk/WatchlistWorkspace.vue'))
const TradingWorkspace = defineAsyncComponent(() => import('@/components/desk/TradingWorkspace.vue'))
const ReviewWorkspace = defineAsyncComponent(() => import('@/components/desk/ReviewWorkspace.vue'))

const desk = useTradingDeskStore()
const route = useRoute()
const reviewDemoMode = computed(() => import.meta.env.DEV && route.query.preview === '1')
const remindersOpen = ref(false)
const myOpen = ref(false)
const toastVisible = ref(false)
const workspaceError = ref<string | null>(null)

const sectionLabels: Record<DeskSection, string> = {
  information: '总览',
  portfolio: '持仓',
  watchlist: '自选',
  trading: '交易',
  review: '复盘',
}
const sections = (['information', 'portfolio', 'watchlist', 'trading', 'review'] as DeskSection[])
  .map((id) => ({ id, label: sectionLabels[id] }))

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

async function submitMarketOrder(input: { instrumentId: string; side: 'buy' | 'sell'; quantity: string }) {
  if (!desk.account) throw new Error('请先建立模拟账户。')
  const instrumentId = input.instrumentId.trim().toUpperCase()
  await desk.ensureQuote(instrumentId)
  await desk.submitMarketOrder({
    accountId: desk.account.account_id,
    instrumentId,
    side: input.side,
    quantity: input.quantity,
  })
}

async function createTradePlanFromCandidate(instrumentId: string) {
  await desk.startCandidateTradePlan(instrumentId)
  desk.setSection('trading')
}

async function loadWatchlistWorkspace(): Promise<void> {
  await Promise.all([desk.loadWatchlists(), desk.loadCandidates()])
}

onMounted(() => { void desk.initialize() })
watch(() => desk.section, () => { workspaceError.value = null })
watch(() => desk.requestedReminderId, (reminderId) => {
  if (reminderId) remindersOpen.value = true
})
watch(firstUnread, (notice) => {
  if (alertTimer) clearTimeout(alertTimer)
  toastVisible.value = Boolean(notice)
  if (notice && !notice.required && notice.severity !== 'required') {
    alertTimer = setTimeout(() => { toastVisible.value = false }, 8_000)
  }
}, { immediate: true })

async function toggleReminders(): Promise<void> {
  remindersOpen.value = !remindersOpen.value
  if (remindersOpen.value) await desk.loadNotificationHistory()
}
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
        <button class="topbar-text-button" type="button" aria-label="打开提醒" @click="toggleReminders">
          <span>提醒</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M9.5 21h5"/></svg><sup v-if="desk.unreadCount">{{ desk.unreadCount }}</sup>
        </button>
        <span class="topbar-divider" aria-hidden="true"></span>
        <button class="topbar-text-button" type="button" aria-label="打开我的" @click="myOpen = !myOpen">
          <span>我的</span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M4.5 21c.8-4 3.4-6 7.5-6s6.7 2 7.5 6"/></svg>
        </button>
      </div>
    </header>

    <section class="desk-spread">
      <section class="desk-left" aria-label="信息与交易工作区">
        <div class="desk-workspace-bar">
          <nav class="desk-nav" aria-label="交易台工作区">
            <button v-for="item in sections" :key="item.id" type="button" :class="{ active: desk.section === item.id }" @click="desk.setSection(item.id)">{{ item.label }}</button>
          </nav>
          <div v-if="desk.simulationClock" class="simulation-time-strip" role="status">
            <span>历史演示</span>
            <strong>{{ new Date(desk.simulationClock.current_time).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }}</strong>
            <span>1× · {{ desk.simulationClock.status === 'running' ? '运行中' : '闭市暂停' }}</span>
            <button
              v-if="desk.simulationClock.status === 'paused_market_closed'"
              type="button"
              class="refresh-button"
              @click="runWorkspaceAction(() => desk.resumeClock())"
            >进入下一交易时段</button>
          </div>
        </div>

        <div class="desk-left-content">
          <OverviewWorkspace
            v-if="desk.section === 'information'"
            :quotes="desk.quotes ?? []" :bars="desk.bars ?? []" :selected-symbol="desk.symbol" :loading="desk.loadingMarket" :market-error="desk.marketError" :bars-error="desk.barsError ?? null"
            :minute-periods-available="desk.minuteBarsSupported"
            :market-loaded-at="desk.marketLoadedAt"
            :sentiment-facts="desk.simulationClock ? null : desk.sentimentFacts" :sentiment-error="desk.simulationClock ? null : desk.sentimentFactsError"
            :sentiment-notice="desk.simulationClock ? '历史演示不提供时点还原的市场情绪事实。' : desk.marketFactsNotice"
            :information-facts="desk.simulationClock ? null : desk.informationFacts" :information-error="desk.simulationClock ? null : desk.informationFactsError"
            :information-notice="desk.simulationClock ? '历史演示不展示现实资讯，避免引入未来信息。' : desk.marketFactsNotice"
            :market-news="desk.simulationClock ? null : desk.marketNews" :market-news-error="desk.simulationClock ? null : desk.marketNewsError"
            :market-news-notice="desk.simulationClock ? '历史演示不展示现实资讯，避免引入未来信息。' : null"
            :on-select-symbol="desk.setSymbol" :on-refresh="desk.refreshOverviewWorkspace"
            :on-period-change="(frequency: string) => desk.setBarsFrequency(frequency)"
          />
          <PortfolioWorkspace
            v-else-if="desk.section === 'portfolio'"
            :account="desk.account ?? null" :account-state="desk.accountState" :portfolio="desk.portfolio ?? null" :quotes="desk.quotes ?? []"
            :loading="desk.loadingSimulation || desk.loadingMarket"
            :error="workspaceError || desk.simulationError || desk.marketError" :on-load="desk.refreshPortfolioWorkspace"
            :on-create-account="(input) => runWorkspaceAction(() => desk.createAccount(input.initialCash, input.simulationStartAt))"
          />
          <WatchlistWorkspace
            v-else-if="desk.section === 'watchlist'"
            :groups="watchlistGroups" :candidates="desk.simulationClock ? [] : (desk.candidates?.candidates ?? [])"
            :candidate-meta="desk.simulationClock ? null : desk.candidates"
            :loading="desk.loadingWatchlists || desk.loadingCandidates" :watchlist-error="workspaceError || desk.watchlistError"
            :candidate-error="desk.simulationClock ? null : desk.candidateError"
            :candidate-notice="desk.simulationClock ? '历史演示不提供研究候选，避免引入未来信息。' : null"
            :on-load="loadWatchlistWorkspace"
            :on-create-group="(input) => runWorkspaceAction(() => desk.createWatchlist(input.name, input.description))"
            :on-rename-group="(input) => runWorkspaceAction(async () => { const group = desk.watchlistGroups.find((item) => item.group_id === input.groupId); if (!group || group.revision !== input.expectedRevision) throw new Error('分组已被更新，请刷新后再试。'); await desk.renameWatchlist(group, input.name, input.description) })"
            :on-delete-group="(input) => runWorkspaceAction(async () => { const group = desk.watchlistGroups.find((item) => item.group_id === input.groupId); if (!group || group.revision !== input.expectedRevision) throw new Error('分组已被更新，请刷新后再试。'); await desk.removeWatchlist(group) })"
            :on-add-instrument="(input) => runWorkspaceAction(() => desk.addToWatchlist(input.groupId, input.instrumentId))"
            :on-remove-instrument="(input) => runWorkspaceAction(() => desk.removeFromWatchlist(input.groupId, input.instrumentId))"
            :on-ignore-candidate="(input) => runWorkspaceAction(() => desk.ignoreCandidate(input.instrumentId, input.reason, input.note))"
            :on-create-trade-plan="(instrumentId) => runWorkspaceAction(() => createTradePlanFromCandidate(instrumentId))"
            :plan-error="desk.tradePlanError"
          />
          <TradingWorkspace
            v-else-if="desk.section === 'trading'"
            :account="desk.account ?? null" :account-state="desk.accountState" :selected-symbol="desk.symbol" :quotes="desk.quotes ?? []"
            :bars="desk.bars ?? []" :bars-error="desk.barsError ?? null"
            :minute-periods-available="desk.minuteBarsSupported"
            :portfolio="desk.portfolio ?? null" :receipt="desk.activeOrder ?? null" :fills="desk.fills ?? []"
            :prefill="desk.tradeDraftPrefill"
            :loading="desk.loadingSimulation || desk.loadingMarket"
            :error="workspaceError || desk.orderError || desk.simulationError || desk.marketError"
            :on-load="desk.refreshTradingWorkspace"
            :on-open-portfolio="() => desk.setSection('portfolio')"
            :on-ensure-quote-symbol="desk.ensureQuoteSymbol"
            :on-select-symbol="desk.setSymbol"
            :on-period-change="(p: string) => desk.setBarsFrequency(p === 'daily' ? undefined : '1m')"
            :on-submit="(input) => runWorkspaceAction(() => submitMarketOrder(input))"
          />
          <ReviewWorkspace
            v-else
            :episodes="desk.tradeEpisodes"
            :selected="desk.selectedTradeEpisode"
            :decisions="desk.tradeEpisodeDecisions"
            :review="desk.tradeEpisodeReview"
            :loading="desk.tradeReviewLoading || desk.agentLearningLoading"
            :error="desk.tradeReviewError"
            :learning-summary="desk.agentLearningSummary"
            :learning-loading="desk.agentLearningLoading"
            :learning-error="desk.agentLearningError"
            :demo-mode="reviewDemoMode"
            :on-load="desk.loadReviewWorkspace"
            :on-retry-learning="desk.loadAgentLearningSummary"
            :on-select="desk.selectTradeEpisode"
            :on-retry="desk.retrySelectedTradeReview"
          />
        </div>
      </section>

      <DeskAgentPanel />
    </section>

    <aside v-if="remindersOpen" class="reminder-panel" aria-label="提醒记录"><header><h2>提醒记录</h2><button type="button" @click="remindersOpen = false">关闭</button></header><p v-if="desk.notificationStreamError" class="data-error" role="status">{{ desk.notificationStreamError }}</p><p v-if="desk.notificationError" class="data-error">{{ desk.notificationError }}</p><p v-else-if="!desk.notificationHistory.length">暂无服务端提醒。</p><ol v-else><li v-for="notice in desk.notificationHistory" :key="notice.notification_id"><strong>{{ notice.required ? '高优先级 · ' : '' }}{{ notice.title }}</strong><p>{{ notice.message }}</p><small v-if="notice.details?.symbol">{{ notice.details.symbol }} · 上游 {{ notice.details.provider_time }} · 检测 {{ notice.details.detected_at }}</small><small>{{ notice.created_at }} · {{ notice.status === 'read' ? '已读' : '未读' }}</small><button v-if="notice.status !== 'read'" type="button" @click="desk.dismissNotification(notice)">标记已读</button></li></ol></aside>
    <aside v-if="toastVisible && firstUnread && !remindersOpen" class="alert-toast" role="status"><strong>{{ firstUnread.title }}</strong><p>{{ firstUnread.message }}</p><button type="button" @click="remindersOpen = true">查看记录</button><button type="button" @click="toastVisible = false">隐藏</button></aside>

    <MyPanel v-if="myOpen" @close="myOpen = false" />
  </main>
</template>
