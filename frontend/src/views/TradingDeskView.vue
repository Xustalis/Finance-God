<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTradingDeskStore, type DeskSection } from '@/stores/tradingDesk'
import { canUseQuoteAsDraftReference, draftReferenceBlockedReason } from '@/services/tradingDesk'
import DeskAgentPanel from '@/components/desk/DeskAgentPanel.vue'
import OverviewWorkspace from '@/components/desk/OverviewWorkspace.vue'

const MyPanel = defineAsyncComponent(() => import('@/components/desk/MyPanel.vue'))
const PortfolioWorkspace = defineAsyncComponent(() => import('@/components/desk/PortfolioWorkspace.vue'))
const WatchlistWorkspace = defineAsyncComponent(() => import('@/components/desk/WatchlistWorkspace.vue'))
const TradingWorkspace = defineAsyncComponent(() => import('@/components/desk/TradingWorkspace.vue'))

const desk = useTradingDeskStore()
const remindersOpen = ref(false)
const myOpen = ref(false)
const toastVisible = ref(false)
const workspaceError = ref<string | null>(null)

const sectionLabels: Record<DeskSection, string> = {
  information: '总览',
  portfolio: '持仓',
  watchlist: '自选',
  trading: '交易',
}
const sections = (['information', 'portfolio', 'watchlist', 'trading'] as DeskSection[])
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

async function createDraft(input: { instrumentId: string; side: 'buy' | 'sell'; orderType: 'market' | 'limit'; quantity: string; limitPrice: string | null }) {
  if (!desk.account) throw new Error('请先建立仿真账户。')
  const instrumentId = input.instrumentId.trim().toUpperCase()
  // 行情缓存未覆盖的标的向服务端实时查询真实快照，而不是直接拒绝。
  const quote = await desk.ensureQuote(instrumentId)
  if (!quote || !canUseQuoteAsDraftReference(quote)) {
    throw new Error(draftReferenceBlockedReason(quote))
  }
  await desk.createDraft({
    mode: 'manual', account_id: desk.account.account_id, instrument_id: instrumentId,
    side: input.side, order_type: input.orderType, quantity: input.quantity,
    limit_price: input.limitPrice ?? undefined, reference_price: String(quote.last),
    time_in_force: 'day', valid_until: new Date(Date.now() + 15 * 60_000).toISOString(),
    input_versions: [{ object_type: 'market_quote', object_id: quote.symbol, version: quote.provider_time }],
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

    <section class="desk-spread">
      <section class="desk-left" aria-label="信息与交易工作区">
        <div class="desk-workspace-bar">
          <nav class="desk-nav" aria-label="交易台工作区">
            <button v-for="item in sections" :key="item.id" type="button" :class="{ active: desk.section === item.id }" @click="desk.setSection(item.id)">{{ item.label }}</button>
          </nav>
        </div>

        <div class="desk-left-content">
          <OverviewWorkspace
            v-if="desk.section === 'information'"
            :quotes="desk.quotes ?? []" :bars="desk.bars ?? []" :selected-symbol="desk.symbol" :loading="desk.loadingMarket" :market-error="desk.marketError" :bars-error="desk.barsError ?? null"
            :market-loaded-at="desk.marketLoadedAt"
            :sentiment-facts="desk.sentimentFacts" :sentiment-error="desk.sentimentFactsError"
            :information-facts="desk.informationFacts" :information-error="desk.informationFactsError"
            :on-select-symbol="desk.setSymbol" :on-refresh="() => desk.refreshMarket({ withBars: true })"
            :on-period-change="(p: string) => desk.setBarsFrequency(p === 'daily' ? undefined : '1m')"
          />
          <PortfolioWorkspace
            v-else-if="desk.section === 'portfolio'"
            :account="desk.account ?? null" :account-state="desk.accountState" :portfolio="desk.portfolio ?? null" :quotes="desk.quotes ?? []"
            :loading="desk.loadingSimulation || desk.loadingMarket"
            :error="workspaceError || desk.simulationError || desk.marketError" :on-load="desk.refreshPortfolioWorkspace"
            :on-create-account="(initialCash) => runWorkspaceAction(() => desk.createAccount(initialCash))"
          />
          <WatchlistWorkspace
            v-else-if="desk.section === 'watchlist'"
            :groups="watchlistGroups" :candidates="desk.candidates?.candidates ?? []"
            :candidate-meta="desk.candidates"
            :loading="desk.loadingWatchlists || desk.loadingCandidates" :watchlist-error="workspaceError || desk.watchlistError" :candidate-error="desk.candidateError"
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
            v-else
            :account="desk.account ?? null" :account-state="desk.accountState" :selected-symbol="desk.symbol" :quotes="desk.quotes ?? []"
            :draft="desk.activeDraft ?? null" :receipt="desk.activeOrder ?? null"
            :prefill="desk.tradeDraftPrefill"
            :trade-plan="desk.activeTradePlan ?? null"
            :loading="desk.loadingSimulation || desk.loadingMarket"
            :error="workspaceError || desk.orderError || desk.tradePlanError || desk.simulationError || desk.marketError"
            :on-load="desk.refreshTradingWorkspace"
            :on-open-portfolio="() => desk.setSection('portfolio')"
            :on-ensure-quote-symbol="desk.ensureQuoteSymbol"
            :on-create-draft="(input) => runWorkspaceAction(() => createDraft(input))"
            :on-review-draft="() => runWorkspaceAction(() => desk.reviewDraft())"
            :on-confirm-soft-risk="(input) => runWorkspaceAction(() => desk.acknowledgeSoftRisk(input.reasonHash))"
            :on-confirm-draft="(input) => runWorkspaceAction(() => desk.confirmDraft(input.summaryHash))"
            :on-submit-draft="() => runWorkspaceAction(() => desk.submitDraft())"
            :on-reconcile-order="() => runWorkspaceAction(() => desk.reconcileOrder())"
          />
        </div>
      </section>

      <DeskAgentPanel />
    </section>

    <aside v-if="remindersOpen" class="reminder-panel" aria-label="提醒记录"><header><h2>提醒记录</h2><button type="button" @click="remindersOpen = false">关闭</button></header><p v-if="desk.notificationError" class="data-error">{{ desk.notificationError }}</p><p v-else-if="!desk.notifications.length">暂无服务端提醒。</p><ol v-else><li v-for="notice in desk.notifications" :key="notice.notification_id"><strong>{{ notice.title }}</strong><p>{{ notice.message }}</p><small>{{ notice.created_at }}</small><button type="button" @click="desk.dismissNotification(notice)">标记已读</button></li></ol></aside>
    <aside v-if="toastVisible && firstUnread && !remindersOpen" class="alert-toast" role="status"><strong>{{ firstUnread.title }}</strong><p>{{ firstUnread.message }}</p><button type="button" @click="remindersOpen = true">查看记录</button><button type="button" @click="toastVisible = false">隐藏</button></aside>

    <MyPanel v-if="myOpen" @close="myOpen = false" />
  </main>
</template>
