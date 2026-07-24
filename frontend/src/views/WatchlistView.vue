<script setup lang="ts">
/**
 * WatchlistView — 自选与候选（T02）
 * 8/4 布局：左主表（互斥 Tab「我的自选」「系统候选」）+ 右常驻 Inspector；
 * 底部 64px 比较托盘（最多 4 标的），选 2–4 个进入同路由全宽比较态。
 * 候选五维评分各维独立、无综合分；数据不足显式标 missing 且禁用交易台入口。
 * 忽略候选仅记录反馈，不删证据。所有结论/行情来自后端，不在前端伪造。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Masthead from '@/components/desk/Masthead.vue'
import { useMarketStore } from '@/stores/market'
import {
  addWatchlistInstrument,
  createWatchlistGroup,
  createCandidateTradePlan,
  deleteWatchlistGroup,
  fetchCandidates,
  fetchWatchlistInstruments,
  fetchWatchlists,
  ignoreCandidate,
  newIdempotencyKey,
  removeWatchlistInstrument,
  searchInstruments,
  unignoreCandidate,
  updateWatchlistGroup,
} from '@/api/desk'
import { directionOf, formatChange, formatNumber, formatPercent } from '@/types/desk'
import type {
  Candidate,
  CandidateIgnoreReason,
  CandidateRating,
  CandidateResponse,
  InstrumentSummary,
  WatchlistGroup,
  WatchlistInstrument,
} from '@/types/desk'

type WatchlistTab = 'watchlist' | 'candidates'
type InspectorSource = 'watchlist' | 'candidate' | 'search'

interface InspectorTarget {
  source: InspectorSource
  symbol: string
  name: string | null
  groupId: string | null
  candidate: Candidate | null
}

const router = useRouter()
const market = useMarketStore()

const activeTab = ref<WatchlistTab>('watchlist')

// ─── 自选 ──────────────────────────────────────────
const groups = ref<WatchlistGroup[]>([])
const groupsLoading = ref(false)
const groupsError = ref<string | null>(null)
const activeGroupId = ref<string | null>(null)
const instrumentsByGroup = ref<Record<string, WatchlistInstrument[]>>({})
const instrumentsError = ref<string | null>(null)
const newGroupName = ref('')
const groupActionError = ref<string | null>(null)

// ─── 候选 ──────────────────────────────────────────
const candidateResp = ref<CandidateResponse | null>(null)
const candidatesLoading = ref(false)
const candidatesError = ref<string | null>(null)
const planCreatingId = ref<string | null>(null)
const planCreationError = ref<string | null>(null)
const expanded = ref<Set<string>>(new Set())
const ignoringId = ref<string | null>(null)
const ignoreReason = ref<CandidateIgnoreReason>('not_now')
const ignoreNote = ref('')

// ─── Inspector（跨 Tab 保持） ──────────────────────
const inspector = ref<InspectorTarget | null>(null)

// ─── 比较托盘 ──────────────────────────────────────
const compare = ref<string[]>([])
const comparing = ref(false)

// ─── 搜索 ──────────────────────────────────────────
const searchQuery = ref('')
const searchResults = ref<InstrumentSummary[]>([])
const searchLoading = ref(false)
const searchError = ref<string | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | null = null

const IGNORE_REASONS: { value: CandidateIgnoreReason; label: string }[] = [
  { value: 'not_now', label: '暂不关注' },
  { value: 'already_covered', label: '已持有替代' },
  { value: 'disagree', label: '观点不同' },
  { value: 'data_error', label: '数据错误' },
]

const RATING_META: Record<CandidateRating, { label: string; cls: string }> = {
  strong: { label: '强', cls: 'rate-strong' },
  adequate: { label: '适中', cls: 'rate-adequate' },
  weak: { label: '弱', cls: 'rate-weak' },
  missing: { label: '缺失', cls: 'rate-missing' },
}

const SOURCE_LABEL: Record<InspectorSource, string> = {
  watchlist: '我的自选',
  candidate: '系统候选',
  search: '搜索',
}

const activeGroup = computed(() =>
  groups.value.find((g) => g.group_id === activeGroupId.value) ?? null,
)

const activeInstruments = computed(() =>
  activeGroupId.value ? instrumentsByGroup.value[activeGroupId.value] ?? [] : [],
)

const candidates = computed(() => candidateResp.value?.candidates ?? [])

const compareCandidates = computed(() =>
  compare.value
    .map((id) => candidates.value.find((c) => c.instrument_id === id))
    .filter((c): c is Candidate => Boolean(c)),
)

const canCompare = computed(() => compare.value.length >= 2)

const dataAsOf = computed(() => candidateResp.value?.generated_at ?? null)

function ratingMeta(rating: CandidateRating) {
  return RATING_META[rating]
}

function ignoreReasonLabel(reason: string | null): string {
  if (!reason) return ''
  return IGNORE_REASONS.find((r) => r.value === reason)?.label ?? reason
}

function quoteFor(symbol: string) {
  return market.quotesMap.get(symbol) ?? null
}

// ─── 数据加载 ──────────────────────────────────────
async function loadGroups() {
  groupsLoading.value = true
  groupsError.value = null
  try {
    const data = await fetchWatchlists()
    groups.value = data
    if (!activeGroupId.value && data.length > 0) {
      activeGroupId.value = data[0].group_id
    }
    await Promise.all(data.map((g) => loadInstruments(g.group_id)))
    syncPolling()
  } catch (err) {
    groupsError.value = err instanceof Error ? err.message : String(err)
  } finally {
    groupsLoading.value = false
  }
}

async function loadInstruments(groupId: string) {
  instrumentsError.value = null
  try {
    const data = await fetchWatchlistInstruments(groupId)
    instrumentsByGroup.value = { ...instrumentsByGroup.value, [groupId]: data }
  } catch (err) {
    instrumentsError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadCandidates() {
  candidatesLoading.value = true
  candidatesError.value = null
  try {
    candidateResp.value = await fetchCandidates()
    syncPolling()
  } catch (err) {
    candidateResp.value = null
    candidatesError.value = err instanceof Error ? err.message : String(err)
  } finally {
    candidatesLoading.value = false
  }
}

function syncPolling() {
  const symbols = new Set<string>()
  for (const list of Object.values(instrumentsByGroup.value)) {
    for (const item of list) symbols.add(item.instrument_id)
  }
  for (const candidate of candidates.value) symbols.add(candidate.symbol)
  if (symbols.size > 0) market.startPolling([...symbols])
}

// ─── 自选分组操作 ──────────────────────────────────
async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  groupActionError.value = null
  try {
    const created = await createWatchlistGroup(name)
    groups.value = [...groups.value, created]
    instrumentsByGroup.value = { ...instrumentsByGroup.value, [created.group_id]: [] }
    activeGroupId.value = created.group_id
    newGroupName.value = ''
  } catch (err) {
    groupActionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function renameGroup(group: WatchlistGroup) {
  const next = window.prompt('重命名分组', group.name)
  if (next === null) return
  const name = next.trim()
  if (!name || name === group.name) return
  groupActionError.value = null
  try {
    const updated = await updateWatchlistGroup(
      group.group_id,
      name,
      group.revision,
      group.description ?? undefined,
    )
    groups.value = groups.value.map((g) => (g.group_id === updated.group_id ? updated : g))
  } catch (err) {
    groupActionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function removeGroup(group: WatchlistGroup) {
  if (!window.confirm(`删除分组「${group.name}」及其标的？`)) return
  groupActionError.value = null
  try {
    await deleteWatchlistGroup(group.group_id, group.revision)
    groups.value = groups.value.filter((g) => g.group_id !== group.group_id)
    const rest = { ...instrumentsByGroup.value }
    delete rest[group.group_id]
    instrumentsByGroup.value = rest
    if (activeGroupId.value === group.group_id) {
      activeGroupId.value = groups.value[0]?.group_id ?? null
    }
  } catch (err) {
    groupActionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function addInstrument(instrument: InstrumentSummary) {
  if (!activeGroupId.value) {
    groupActionError.value = '请先创建或选择一个分组'
    return
  }
  const groupId = activeGroupId.value
  groupActionError.value = null
  try {
    const created = await addWatchlistInstrument(groupId, instrument.symbol)
    const current = instrumentsByGroup.value[groupId] ?? []
    if (!current.some((i) => i.instrument_id === created.instrument_id)) {
      instrumentsByGroup.value = {
        ...instrumentsByGroup.value,
        [groupId]: [created, ...current],
      }
    }
    clearSearch()
    syncPolling()
  } catch (err) {
    groupActionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function removeInstrument(groupId: string, instrumentId: string) {
  groupActionError.value = null
  try {
    await removeWatchlistInstrument(groupId, instrumentId)
    const current = instrumentsByGroup.value[groupId] ?? []
    instrumentsByGroup.value = {
      ...instrumentsByGroup.value,
      [groupId]: current.filter((i) => i.instrument_id !== instrumentId),
    }
    if (inspector.value?.symbol === instrumentId && inspector.value.source === 'watchlist') {
      inspector.value = null
    }
  } catch (err) {
    groupActionError.value = err instanceof Error ? err.message : String(err)
  }
}

// ─── 候选操作 ──────────────────────────────────────
function toggleExpand(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function startIgnore(candidate: Candidate) {
  ignoringId.value = candidate.instrument_id
  ignoreReason.value = 'not_now'
  ignoreNote.value = ''
}

function cancelIgnore() {
  ignoringId.value = null
  ignoreNote.value = ''
}

async function confirmIgnore(candidate: Candidate) {
  candidatesError.value = null
  try {
    await ignoreCandidate(candidate.instrument_id, ignoreReason.value, ignoreNote.value || undefined)
    cancelIgnore()
    await loadCandidates()
  } catch (err) {
    candidatesError.value = err instanceof Error ? err.message : String(err)
  }
}

async function restoreCandidate(candidate: Candidate) {
  candidatesError.value = null
  try {
    await unignoreCandidate(candidate.instrument_id)
    await loadCandidates()
  } catch (err) {
    candidatesError.value = err instanceof Error ? err.message : String(err)
  }
}

// ─── Inspector 与比较托盘 ──────────────────────────
function inspectWatchlist(item: WatchlistInstrument) {
  inspector.value = {
    source: 'watchlist',
    symbol: item.instrument_id,
    name: quoteFor(item.instrument_id)?.name ?? null,
    groupId: item.group_id,
    candidate: null,
  }
}

function inspectCandidate(candidate: Candidate) {
  inspector.value = {
    source: 'candidate',
    symbol: candidate.symbol,
    name: candidate.name,
    groupId: null,
    candidate,
  }
}

function inspectSearch(instrument: InstrumentSummary) {
  inspector.value = {
    source: 'search',
    symbol: instrument.symbol,
    name: null,
    groupId: null,
    candidate: null,
  }
}

function toggleCompare(candidate: Candidate) {
  const id = candidate.instrument_id
  if (compare.value.includes(id)) {
    compare.value = compare.value.filter((c) => c !== id)
  } else if (compare.value.length < 4) {
    compare.value = [...compare.value, id]
  }
}

function inCompare(candidate: Candidate) {
  return compare.value.includes(candidate.instrument_id)
}

function clearCompare() {
  compare.value = []
  comparing.value = false
}

// ─── 进入交易台（T03），携带来源/分组/候选原因 ────
function enterDesk(target: {
  symbol: string
  source: InspectorSource
  direction?: string
  reason?: string
  groupId?: string | null
}) {
  const query: Record<string, string> = { symbol: target.symbol, source: target.source }
  if (target.direction) query.direction = target.direction
  if (target.reason) query.reason = target.reason
  if (target.groupId) query.group = target.groupId
  void router.push({ path: '/desk', query })
}

function viewCandidateResearch(candidate: Candidate) {
  if (!candidate.tradable) return
  enterDesk({
    symbol: candidate.symbol,
    source: 'candidate',
    direction: candidate.direction,
    reason: candidate.purpose,
  })
}

async function createCandidatePlan(candidate: Candidate) {
  if (!candidate.tradable || candidate.ignored || planCreatingId.value) return
  planCreatingId.value = candidate.instrument_id
  planCreationError.value = null
  try {
    const created = await createCandidateTradePlan(
      candidate.instrument_id,
      newIdempotencyKey('candidate-trade-plan'),
    )
    await router.push(`/trade-plans/${created.object.plan_id}`)
  } catch (err) {
    planCreationError.value = err instanceof Error ? err.message : String(err)
  } finally {
    planCreatingId.value = null
  }
}

// ─── 搜索 ──────────────────────────────────────────
watch(searchQuery, (value) => {
  if (searchTimer) clearTimeout(searchTimer)
  const query = value.trim()
  searchError.value = null
  if (!query) {
    searchResults.value = []
    return
  }
  searchTimer = setTimeout(() => void runSearch(query), 250)
})

async function runSearch(query: string) {
  searchLoading.value = true
  searchError.value = null
  try {
    const data = await searchInstruments(query)
    searchResults.value = data.instruments
  } catch (err) {
    searchResults.value = []
    searchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    searchLoading.value = false
  }
}

function clearSearch() {
  searchQuery.value = ''
  searchResults.value = []
}

onMounted(() => {
  market.checkHealth()
  void loadGroups()
  void loadCandidates()
})

onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
  market.stopPolling()
})
</script>

<template>
  <div class="watchlist-page">
    <Masthead />

    <!-- 子头：标题 + 搜索 + 数据时点 -->
    <div class="sub-header">
      <div class="sub-lead">
        <span class="kicker">行情 · WATCHLIST</span>
        <h1>自选与候选</h1>
      </div>
      <div class="sub-search">
        <input
          v-model="searchQuery"
          type="search"
          class="search-input"
          placeholder="搜索股票、ETF、基金"
          aria-label="搜索标的"
        />
        <div v-if="searchQuery.trim()" class="search-panel">
          <p v-if="searchLoading" class="hint">搜索中…</p>
          <p v-else-if="searchError" class="hint error">{{ searchError }}</p>
          <p v-else-if="searchResults.length === 0" class="hint">无匹配标的</p>
          <ul v-else class="search-list">
            <li v-for="item in searchResults" :key="item.symbol" class="search-row">
              <button class="search-pick" @click="inspectSearch(item)">
                <strong>{{ item.symbol }}</strong>
                <span>{{ item.market }} · {{ item.asset_class }} · {{ item.currency }}</span>
                <em v-if="!item.simulation_supported" class="unsupported">不支持仿真</em>
              </button>
              <button class="mini-btn" :disabled="!activeGroupId" @click="addInstrument(item)">
                加入自选
              </button>
            </li>
          </ul>
        </div>
      </div>
      <div class="sub-meta">
        <span class="meta-label">数据时点</span>
        <strong>{{ dataAsOf ? new Date(dataAsOf).toLocaleString() : '—' }}</strong>
        <span class="meta-provider">{{ market.provider || '—' }}</span>
      </div>
    </div>

    <!-- Tabs：互斥 -->
    <nav class="tabs" role="tablist" aria-label="自选与候选">
      <button
        class="tab"
        role="tab"
        :aria-selected="activeTab === 'watchlist'"
        :class="{ active: activeTab === 'watchlist' }"
        @click="activeTab = 'watchlist'"
      >
        我的自选
      </button>
      <button
        class="tab"
        role="tab"
        :aria-selected="activeTab === 'candidates'"
        :class="{ active: activeTab === 'candidates' }"
        @click="activeTab = 'candidates'"
      >
        系统候选
      </button>
    </nav>

    <!-- 全宽比较态 -->
    <section v-if="comparing && canCompare" class="compare-view">
      <header class="compare-head">
        <h2>候选比较（{{ compareCandidates.length }}）</h2>
        <button class="mini-btn" @click="comparing = false">返回列表</button>
      </header>
      <table class="compare-table">
        <thead>
          <tr>
            <th>维度</th>
            <th v-for="c in compareCandidates" :key="c.instrument_id">
              {{ c.symbol }}<small>{{ c.name || c.direction_label }}</small>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="dimKey in ['portfolio_fit', 'risk', 'cost', 'liquidity', 'evidence']" :key="dimKey">
            <th scope="row">
              {{ compareCandidates[0]?.dimensions.find((d) => d.dimension === dimKey)?.label || dimKey }}
            </th>
            <td v-for="c in compareCandidates" :key="c.instrument_id + dimKey">
              <template v-for="d in c.dimensions" :key="d.dimension">
                <span v-if="d.dimension === dimKey" class="rate-badge" :class="ratingMeta(d.rating).cls">
                  {{ ratingMeta(d.rating).label }}
                </span>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="compare-note">
        组合影响预览基于各候选「组合适配」维度；预览不创建计划，形成多标的调整时进入交易计划（T04）。
      </p>
    </section>

    <!-- 8/4 主区 -->
    <div v-else class="body">
      <main class="main-col">
        <!-- 我的自选 -->
        <div v-if="activeTab === 'watchlist'" class="pane">
          <div class="group-bar">
            <button
              v-for="g in groups"
              :key="g.group_id"
              class="group-chip"
              :class="{ active: g.group_id === activeGroupId }"
              @click="activeGroupId = g.group_id"
            >
              {{ g.name }}
              <span class="count">{{ (instrumentsByGroup[g.group_id] || []).length }}</span>
            </button>
            <form class="group-add" @submit.prevent="createGroup">
              <input v-model="newGroupName" class="group-input" placeholder="新建分组" aria-label="新建分组名称" />
              <button type="submit" class="mini-btn" :disabled="!newGroupName.trim()">新建</button>
            </form>
          </div>

          <div v-if="activeGroup" class="group-actions">
            <span class="group-title">{{ activeGroup.name }}</span>
            <button class="link-btn" @click="renameGroup(activeGroup)">改名</button>
            <button class="link-btn danger" @click="removeGroup(activeGroup)">删除分组</button>
          </div>

          <p v-if="groupsLoading" class="hint">加载自选…</p>
          <p v-else-if="groupsError" class="hint error">自选加载失败：{{ groupsError }}</p>
          <p v-else-if="groups.length === 0" class="hint">
            暂无自选分组。可在上方新建分组，或从「系统候选」加入。
          </p>
          <p v-else-if="activeInstruments.length === 0" class="hint">
            该分组暂无标的。使用顶部搜索添加，或切换到系统候选。
          </p>
          <table v-else class="grid-table">
            <thead>
              <tr>
                <th>代码</th><th>最新价</th><th>涨跌幅</th><th>数据源</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in activeInstruments"
                :key="item.instrument_id"
                class="grid-row"
                :class="{ selected: inspector?.source === 'watchlist' && inspector.symbol === item.instrument_id }"
                @click="inspectWatchlist(item)"
              >
                <td class="mono">{{ item.instrument_id }}</td>
                <td class="mono">{{ quoteFor(item.instrument_id) ? formatNumber(quoteFor(item.instrument_id)!.last) : '—' }}</td>
                <td class="mono" :class="quoteFor(item.instrument_id) ? directionOf(quoteFor(item.instrument_id)!) : ''">
                  {{ quoteFor(item.instrument_id) ? formatPercent(quoteFor(item.instrument_id)!.change_percent) : '—' }}
                </td>
                <td class="muted">{{ quoteFor(item.instrument_id)?.provider || '—' }}</td>
                <td>
                  <button class="link-btn danger" @click.stop="removeInstrument(item.group_id, item.instrument_id)">移除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 系统候选 -->
        <div v-else class="pane">
          <p class="purpose">{{ candidateResp?.purpose_summary || '系统候选：根据目标组合与授权提出的待研究资产，非买入指令。' }}</p>
          <p v-if="candidateResp?.unavailable_reason" class="hint error" role="alert">
            行情上游不可用（{{ candidateResp.unavailable_reason }}）：候选评分部分维度缺失，交易台入口已禁用。
          </p>
          <p v-if="candidatesLoading" class="hint">生成候选…</p>
          <p v-else-if="candidatesError" class="hint error">候选加载失败：{{ candidatesError }}</p>
          <p v-else-if="candidates.length === 0" class="hint">当前无符合候选，或筛选过严。</p>
          <ul v-else class="candidate-list">
            <li
              v-for="c in candidates"
              :key="c.instrument_id"
              class="candidate-card"
              :class="{ ignored: c.ignored, selected: inspector?.source === 'candidate' && inspector.symbol === c.symbol }"
            >
              <div class="candidate-head" @click="inspectCandidate(c)">
                <div class="candidate-id">
                  <strong class="mono">{{ c.symbol }}</strong>
                  <span>{{ c.name || c.direction_label }}</span>
                  <span class="tag">{{ c.direction_label }}</span>
                  <span v-if="c.ignored" class="tag ignored-tag">已忽略 · {{ ignoreReasonLabel(c.ignore_reason) }}</span>
                </div>
                <div class="candidate-quote" v-if="quoteFor(c.symbol)">
                  <strong class="mono">{{ formatNumber(quoteFor(c.symbol)!.last) }}</strong>
                  <span class="mono" :class="directionOf(quoteFor(c.symbol)!)">
                    {{ formatChange(quoteFor(c.symbol)!.change) }} ({{ formatPercent(quoteFor(c.symbol)!.change_percent) }})
                  </span>
                </div>
              </div>
              <p class="candidate-purpose">{{ c.purpose }}</p>

              <div class="dim-row">
                <span
                  v-for="d in c.dimensions"
                  :key="d.dimension"
                  class="rate-badge"
                  :class="ratingMeta(d.rating).cls"
                  :title="d.detail"
                >
                  {{ d.label }}·{{ ratingMeta(d.rating).label }}
                </span>
                <button class="link-btn" @click="toggleExpand(c.instrument_id)">
                  {{ expanded.has(c.instrument_id) ? '收起拆解' : '展开拆解' }}
                </button>
              </div>

              <div v-if="expanded.has(c.instrument_id)" class="dim-detail">
                <div v-for="d in c.dimensions" :key="d.dimension" class="dim-item">
                  <div class="dim-item-head">
                    <span class="rate-badge" :class="ratingMeta(d.rating).cls">{{ ratingMeta(d.rating).label }}</span>
                    <strong>{{ d.label }}</strong>
                  </div>
                  <p>{{ d.detail }}</p>
                  <ul v-if="Object.keys(d.metrics).length" class="metrics">
                    <li v-for="(v, k) in d.metrics" :key="k"><span>{{ k }}</span><em class="mono">{{ v }}</em></li>
                  </ul>
                  <p v-if="d.missing_fields.length" class="missing">缺失字段：{{ d.missing_fields.join('、') }}</p>
                </div>
              </div>

              <ul v-if="c.exclusions.length" class="exclusions">
                <li v-for="ex in c.exclusions" :key="ex.reason_code">排除：{{ ex.detail }}</li>
              </ul>

              <div class="candidate-actions">
                <button
                  class="mini-btn primary"
                  :disabled="!c.tradable || c.ignored || Boolean(planCreatingId)"
                  :title="c.tradable ? '创建待审阅交易计划' : '数据不足或冲突，不能创建交易计划'"
                  @click="createCandidatePlan(c)"
                >
                  {{ planCreatingId === c.instrument_id ? '正在创建…' : '创建交易计划' }}
                </button>
                <button class="mini-btn" :disabled="!c.tradable" @click="viewCandidateResearch(c)">
                  查看研究
                </button>
                <button class="mini-btn" :class="{ active: inCompare(c) }" :disabled="!inCompare(c) && compare.length >= 4" @click="toggleCompare(c)">
                  {{ inCompare(c) ? '移出比较' : '加入比较' }}
                </button>
                <button v-if="!c.ignored" class="link-btn" @click="startIgnore(c)">忽略</button>
                <button v-else class="link-btn" @click="restoreCandidate(c)">撤销忽略</button>
              </div>

              <form v-if="ignoringId === c.instrument_id" class="ignore-form" @submit.prevent="confirmIgnore(c)">
                <select v-model="ignoreReason" aria-label="忽略原因">
                  <option v-for="r in IGNORE_REASONS" :key="r.value" :value="r.value">{{ r.label }}</option>
                </select>
                <input v-model="ignoreNote" placeholder="备注（可选）" aria-label="忽略备注" />
                <button type="submit" class="mini-btn">确认</button>
                <button type="button" class="link-btn" @click="cancelIgnore">取消</button>
              </form>
            </li>
          </ul>
        </div>
        <p v-if="groupActionError" class="hint error" role="alert">{{ groupActionError }}</p>
        <p v-if="instrumentsError" class="hint error" role="alert">{{ instrumentsError }}</p>
        <p v-if="planCreationError" class="hint error" role="alert">交易计划创建失败：{{ planCreationError }}</p>
      </main>

      <!-- 常驻 Inspector -->
      <aside class="inspector">
        <h2 class="section-title"><span>对象详情</span><small>INSPECTOR</small></h2>
        <div v-if="!inspector" class="inspector-empty">从左侧选择自选或候选查看详情。</div>
        <div v-else class="inspector-body">
          <span class="source-badge">来源：{{ SOURCE_LABEL[inspector.source] }}</span>
          <div class="inspector-id">
            <strong class="mono">{{ inspector.symbol }}</strong>
            <span v-if="inspector.name">{{ inspector.name }}</span>
          </div>
          <div v-if="quoteFor(inspector.symbol)" class="inspector-quote">
            <div class="row"><span>最新价</span><strong class="mono">{{ formatNumber(quoteFor(inspector.symbol)!.last) }}</strong></div>
            <div class="row"><span>涨跌幅</span><strong class="mono" :class="directionOf(quoteFor(inspector.symbol)!)">{{ formatPercent(quoteFor(inspector.symbol)!.change_percent) }}</strong></div>
            <div class="row"><span>数据时点</span><strong>{{ quoteFor(inspector.symbol)!.provider_time }}</strong></div>
            <div class="row"><span>数据源</span><strong>{{ quoteFor(inspector.symbol)!.provider }}</strong></div>
          </div>
          <p v-else class="hint">暂无实时行情。</p>

          <template v-if="inspector.candidate">
            <p class="inspector-purpose">{{ inspector.candidate.purpose }}</p>
            <div class="inspector-dims">
              <div v-for="d in inspector.candidate.dimensions" :key="d.dimension" class="row">
                <span>{{ d.label }}</span>
                <span class="rate-badge" :class="ratingMeta(d.rating).cls">{{ ratingMeta(d.rating).label }}</span>
              </div>
            </div>
          </template>

          <div class="inspector-actions">
            <button
              v-if="inspector.candidate"
              class="mini-btn primary"
              :disabled="!inspector.candidate.tradable || inspector.candidate.ignored || Boolean(planCreatingId)"
              @click="createCandidatePlan(inspector.candidate)"
            >
              {{ planCreatingId === inspector.candidate.instrument_id ? '正在创建…' : '创建交易计划' }}
            </button>
            <button
              v-if="inspector.candidate"
              class="mini-btn"
              :disabled="!inspector.candidate.tradable"
              @click="viewCandidateResearch(inspector.candidate)"
            >
              查看研究
            </button>
            <button
              v-else
              class="mini-btn primary"
              @click="enterDesk({ symbol: inspector.symbol, source: inspector.source, groupId: inspector.groupId })"
            >
              查看研究
            </button>
            <button
              v-if="inspector.candidate && !inspector.candidate.ignored"
              class="link-btn"
              @click="startIgnore(inspector.candidate)"
            >
              忽略
            </button>
            <button
              v-if="inspector.source === 'watchlist' && inspector.groupId"
              class="link-btn danger"
              @click="removeInstrument(inspector.groupId, inspector.symbol)"
            >
              移除
            </button>
          </div>
        </div>
      </aside>
    </div>

    <!-- 64px 比较托盘 -->
    <footer class="compare-tray">
      <span class="tray-label">比较托盘</span>
      <div class="tray-items">
        <span v-if="compare.length === 0" class="tray-empty">从系统候选选 2–4 个标的进行比较</span>
        <button v-for="id in compare" :key="id" class="tray-chip" @click="compare = compare.filter((c) => c !== id)">
          {{ id }} ✕
        </button>
      </div>
      <div class="tray-actions">
        <button v-if="compare.length" class="link-btn" @click="clearCompare">清空</button>
        <button class="mini-btn primary" :disabled="!canCompare" @click="comparing = true">
          比较（{{ compare.length }}/4）
        </button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.watchlist-page {
  display: grid;
  grid-template-rows: 64px auto auto 1fr 64px;
  min-height: 100vh;
  border-top: 10px solid var(--ink);
  background: var(--paper);
  font-variant-numeric: tabular-nums lining-nums;
}

.sub-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 420px) auto;
  align-items: center;
  gap: 20px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--rule);
}
.sub-lead .kicker {
  display: block;
  color: var(--risk);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.12em;
}
.sub-lead h1 { margin: 2px 0 0; font-size: 26px; font-weight: 800; letter-spacing: -0.01em; }

.sub-search { position: relative; }
.search-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--rule);
  background: var(--paper-light);
  font-size: 14px;
}
.search-panel {
  position: absolute;
  z-index: 40;
  left: 0; right: 0; top: calc(100% + 4px);
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--rule);
  background: var(--paper-light);
  box-shadow: var(--shadow);
}
.search-list { list-style: none; margin: 0; padding: 0; }
.search-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--faint-rule);
}
.search-pick {
  display: grid;
  gap: 1px;
  flex: 1;
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
}
.search-pick strong { font-family: var(--font-numeric); }
.search-pick span { color: var(--muted-ink); font-size: 11px; }
.unsupported { color: var(--risk); font-size: 11px; }

.sub-meta {
  display: grid;
  justify-items: end;
  gap: 1px;
  font-size: 11px;
  color: var(--muted-ink);
}
.sub-meta strong { font-family: var(--font-numeric); font-size: 13px; color: var(--ink); }
.meta-label { font-weight: 700; letter-spacing: 0.08em; }

.tabs {
  display: flex;
  gap: 0;
  padding: 0 20px;
  border-bottom: 2px solid var(--rule);
}
.tab {
  padding: 10px 22px;
  background: transparent;
  border: 0;
  border-bottom: 3px solid transparent;
  margin-bottom: -2px;
  font-size: 15px;
  font-weight: 700;
  color: var(--muted-ink);
  cursor: pointer;
}
.tab.active { color: var(--risk); border-bottom-color: var(--risk); font-weight: 900; }

.body {
  display: grid;
  grid-template-columns: minmax(0, 8fr) minmax(320px, 4fr);
  min-height: 0;
  overflow: hidden;
}
.main-col { min-width: 0; padding: 16px 20px 24px; overflow-y: auto; }
.inspector {
  min-width: 0;
  border-left: 1px solid var(--rule);
  padding-bottom: 24px;
  overflow-y: auto;
}

.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 16px 7px;
  border-bottom: 1px solid var(--rule);
  font-size: 14px;
  font-weight: 900;
  margin: 0;
}
.section-title small { color: var(--muted-ink); font-size: 8px; letter-spacing: 0.1em; }

.group-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.group-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--rule);
  background: var(--paper-light);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.group-chip.active { background: var(--ink); color: var(--paper-light); }
.group-chip .count { font-family: var(--font-numeric); font-size: 11px; opacity: 0.7; }
.group-add { display: inline-flex; gap: 4px; }
.group-input { padding: 4px 8px; border: 1px solid var(--rule); font-size: 13px; width: 120px; }

.group-actions { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.group-title { font-weight: 800; }

.grid-table, .compare-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.grid-table th, .compare-table th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--rule); color: var(--muted-ink); font-size: 11px; }
.grid-table td { padding: 6px 8px; border-bottom: 1px solid var(--faint-rule); }
.grid-row { cursor: pointer; }
.grid-row:hover { background: var(--faint-rule); }
.grid-row.selected { background: rgb(33 26 18 / 8%); }
.mono { font-family: var(--font-numeric); }
.muted { color: var(--muted-ink); }
.up { color: var(--positive); }
.down { color: var(--risk); }

.purpose { color: var(--muted-ink); font-size: 13px; margin: 4px 0 12px; }
.candidate-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.candidate-card { border: 1px solid var(--rule); padding: 12px; background: var(--paper-light); }
.candidate-card.selected { border-color: var(--risk); }
.candidate-card.ignored { opacity: 0.6; }
.candidate-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; cursor: pointer; }
.candidate-id { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.candidate-id strong { font-size: 16px; }
.candidate-quote { text-align: right; display: grid; gap: 2px; }
.tag { font-size: 11px; padding: 1px 6px; border: 1px solid var(--rule); color: var(--muted-ink); }
.ignored-tag { color: var(--risk); border-color: var(--risk); }
.candidate-purpose { font-size: 13px; margin: 8px 0; }

.dim-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.rate-badge { font-size: 11px; font-weight: 700; padding: 1px 7px; border: 1px solid var(--rule); }
.rate-strong { color: var(--positive); border-color: var(--positive); }
.rate-adequate { color: var(--ink); }
.rate-weak { color: var(--risk); border-color: var(--risk); }
.rate-missing { color: var(--muted-ink); background: repeating-linear-gradient(45deg, transparent, transparent 3px, var(--faint-rule) 3px, var(--faint-rule) 6px); }

.dim-detail { margin-top: 10px; display: grid; gap: 10px; border-top: 1px solid var(--faint-rule); padding-top: 10px; }
.dim-item-head { display: flex; align-items: center; gap: 8px; }
.dim-item p { font-size: 13px; margin: 4px 0; }
.metrics { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 10px; }
.metrics li { display: flex; gap: 4px; font-size: 11px; color: var(--muted-ink); }
.missing { color: var(--risk); font-size: 12px; }

.exclusions { margin: 10px 0 0; padding-left: 18px; color: var(--risk); font-size: 12px; }
.candidate-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 10px; }
.ignore-form { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }
.ignore-form select, .ignore-form input { padding: 4px 8px; border: 1px solid var(--rule); font-size: 12px; }

.mini-btn {
  padding: 5px 12px;
  border: 1px solid var(--rule);
  background: var(--paper-light);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.mini-btn:hover:not(:disabled) { background: var(--faint-rule); }
.mini-btn.primary { background: var(--ink); color: var(--paper-light); border-color: var(--ink); }
.mini-btn.active { border-color: var(--risk); color: var(--risk); }
.mini-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.link-btn { background: transparent; border: 0; color: var(--muted-ink); font-size: 12px; font-weight: 700; cursor: pointer; text-decoration: underline; }
.link-btn:hover { color: var(--ink); }
.link-btn.danger { color: var(--risk); }

.hint { color: var(--muted-ink); font-size: 13px; padding: 12px 0; }
.hint.error { color: var(--risk); }

.inspector-empty { padding: 20px 16px; color: var(--muted-ink); font-size: 13px; }
.inspector-body { padding: 14px 16px; display: grid; gap: 12px; }
.source-badge { font-size: 11px; font-weight: 700; color: var(--risk); letter-spacing: 0.06em; }
.inspector-id { display: flex; align-items: baseline; gap: 8px; }
.inspector-id strong { font-size: 20px; }
.inspector-quote .row, .inspector-dims .row, .row { display: flex; justify-content: space-between; align-items: baseline; padding: 4px 0; font-size: 13px; border-bottom: 1px solid var(--faint-rule); }
.row span { color: var(--muted-ink); }
.inspector-purpose { font-size: 13px; }
.inspector-actions { display: flex; flex-wrap: wrap; gap: 10px; }

.compare-view { padding: 16px 20px; overflow-y: auto; }
.compare-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.compare-table th, .compare-table td { border: 1px solid var(--rule); padding: 8px; text-align: center; }
.compare-table th small { display: block; color: var(--muted-ink); font-weight: 400; font-size: 10px; }
.compare-note { margin-top: 12px; color: var(--muted-ink); font-size: 12px; }

.compare-tray {
  display: flex;
  align-items: center;
  gap: 14px;
  height: 64px;
  padding: 0 20px;
  border-top: 2px solid var(--rule);
  background: var(--paper-light);
}
.tray-label { font-size: 11px; font-weight: 900; letter-spacing: 0.1em; color: var(--muted-ink); }
.tray-items { display: flex; flex: 1; align-items: center; gap: 8px; overflow-x: auto; }
.tray-empty { color: var(--muted-ink); font-size: 12px; }
.tray-chip { padding: 4px 10px; border: 1px solid var(--rule); background: var(--paper); font-family: var(--font-numeric); font-size: 12px; cursor: pointer; }
.tray-actions { display: flex; align-items: center; gap: 10px; }

@media (max-width: 1279px) {
  .body { grid-template-columns: minmax(0, 1fr) minmax(280px, 340px); }
  .sub-header { grid-template-columns: 1fr; gap: 10px; }
}
</style>
