<script setup lang="ts">
import { computed, ref, watch } from 'vue'

export interface WatchlistInstrument { instrument_id: string; added_at?: string }
export interface WatchlistQuote {
  symbol: string
  name: string
  last: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  previous_close?: number | null
  change: number | null
  change_percent: number | null
  volume?: number | null
  amount?: number | null
  provider_time: string
  frequency: string
  freshness: string
  market_status?: string
}
export interface WatchlistGroup { group_id: string; name: string; description: string | null; revision: number; instruments: readonly WatchlistInstrument[] }
export interface ResearchDimension { dimension: string; label: string; rating: string; detail: string; missing_fields: readonly string[] }
export interface ResearchCandidate {
  instrument_id: string
  symbol: string
  name: string | null
  direction_label: string
  purpose: string
  dimensions: readonly ResearchDimension[]
  exclusions: readonly { reason_code: string; detail: string }[]
  ignored: boolean
  ignore_reason: string | null
  tradable?: boolean
  as_of: string | null
  provider: string | null
}

const ratingColorMap: Record<string, string> = {
  '优': 'rating-good',
  '良': 'rating-fair',
  '中': 'rating-neutral',
  '差': 'rating-poor',
}

const props = defineProps<{
  groups: readonly WatchlistGroup[]
  quotes: readonly WatchlistQuote[]
  candidates: readonly ResearchCandidate[]
  candidateMeta?: {
    generated_at: string
    rule_version: string
    profile_version: number | null
    directions: readonly string[]
    unavailable_reason: string | null
  } | null
  loading: boolean
  watchlistError: string | null
  candidateError: string | null
  candidateNotice?: string | null
  planError?: string | null
  onLoad: () => void | Promise<void>
  onCreateGroup: (input: { name: string; description: string | null }) => void | Promise<void>
  onRenameGroup: (input: { groupId: string; name: string; description: string | null; expectedRevision: number }) => void | Promise<void>
  onDeleteGroup: (input: { groupId: string; expectedRevision: number }) => void | Promise<void>
  onAddInstrument: (input: { groupId: string; instrumentId: string }) => void | Promise<void>
  onRemoveInstrument: (input: { groupId: string; instrumentId: string }) => void | Promise<void>
  onSelectSymbol?: (symbol: string) => void
  onIgnoreCandidate: (input: { instrumentId: string; reason: 'not_now' | 'already_covered' | 'disagree' | 'data_error'; note: string | null }) => void | Promise<void>
  onCreateTradePlan?: (instrumentId: string) => void | Promise<void>
}>()

const selectedGroupId = ref<string | null>(null)
const selectedGroup = computed(() => props.groups.find((item) => item.group_id === selectedGroupId.value) ?? props.groups[0] ?? null)
const showCreateForm = ref(false)
const showEditForm = ref(false)
const newGroupName = ref('')
const newGroupDescription = ref('')
const groupName = ref('')
const groupDescription = ref('')
const instrumentId = ref('')
const directionLabels: Record<string, string> = {
  cash_fixed_income: '现金与固收',
  public_funds: '公募基金',
  equities: '权益（股票）',
  alternatives: '另类配置',
  long_term_insurance: '长期储蓄保险',
}
const candidateDirectionsText = computed(() => (
  props.candidateMeta?.directions
    .map(direction => directionLabels[direction] ?? direction)
    .join('、') || '方向未就绪'
))
const candidateUnavailableText = computed(() => {
  const reason = props.candidateMeta?.unavailable_reason
  if (!reason) return null
  return {
    PROFILE_REQUIRED: '需要先完成投资画像，当前没有生成股票候选。',
    PROFILE_DIRECTIONS_REQUIRED: '画像没有可用的选定或推荐方向。',
    NO_SUPPORTED_DIRECTION_CANDIDATES: '当前画像方向不生成股票候选；如需股票研究，可在画像中选择权益方向。',
    MARKET_DATA_UNAVAILABLE: 'PandaData 行情不可用，候选暂不能进入交易计划。',
  }[reason] ?? `候选生成不可用：${reason}`
})
const neutralCandidateReasons = new Set([
  'PROFILE_REQUIRED',
  'PROFILE_DIRECTIONS_REQUIRED',
  'NO_SUPPORTED_DIRECTION_CANDIDATES',
])
const candidateUnavailableIsError = computed(() => (
  Boolean(
    props.candidateMeta?.unavailable_reason
    && !neutralCandidateReasons.has(props.candidateMeta.unavailable_reason),
  )
))

function quoteFor(instrumentId: string): WatchlistQuote | null {
  return props.quotes.find((q) => q.symbol === instrumentId) ?? null
}
function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return value.toFixed(2)
}
function formatChange(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return (value >= 0 ? '+' : '') + value.toFixed(2)
}
function formatPercent(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return (value >= 0 ? '+' : '') + value.toFixed(2) + '%'
}
function formatVolume(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (value >= 1e4) return (value / 1e4).toFixed(0) + '万'
  return String(value)
}
function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (value >= 1e4) return (value / 1e4).toFixed(0) + '万'
  return value.toFixed(2)
}
function changeClass(value: number | null): string {
  if (value === null || value === undefined) return ''
  if (value > 0) return 'quote-up'
  if (value < 0) return 'quote-down'
  return ''
}
function formatDate(iso: string | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hours = String(d.getHours()).padStart(2, '0')
    const minutes = String(d.getMinutes()).padStart(2, '0')
    return `${month}-${day} ${hours}:${minutes}`
  } catch { return iso.slice(0, 10) }
}
function ratingClass(rating: string): string {
  return ratingColorMap[rating] ?? 'rating-neutral'
}

function selectGroup(group: WatchlistGroup) {
  selectedGroupId.value = group.group_id
  groupName.value = group.name
  groupDescription.value = group.description ?? ''
  showEditForm.value = false
}
async function createGroup() {
  if (!newGroupName.value.trim()) return
  await props.onCreateGroup({ name: newGroupName.value.trim(), description: newGroupDescription.value.trim() || null })
  newGroupName.value = ''
  newGroupDescription.value = ''
  showCreateForm.value = false
}
async function renameGroup() {
  if (!selectedGroup.value || !groupName.value.trim()) return
  await props.onRenameGroup({ groupId: selectedGroup.value.group_id, name: groupName.value.trim(), description: groupDescription.value.trim() || null, expectedRevision: selectedGroup.value.revision })
  showEditForm.value = false
}
async function addInstrument() {
  if (!selectedGroup.value || !instrumentId.value.trim()) return
  await props.onAddInstrument({ groupId: selectedGroup.value.group_id, instrumentId: instrumentId.value.trim() })
  instrumentId.value = ''
}

watch(
  () => [selectedGroup.value?.group_id, selectedGroup.value?.revision] as const,
  () => {
    if (!selectedGroup.value) {
      groupName.value = ''
      groupDescription.value = ''
      return
    }
    selectedGroupId.value = selectedGroup.value.group_id
    groupName.value = selectedGroup.value.name
    groupDescription.value = selectedGroup.value.description ?? ''
  },
  { immediate: true },
)
</script>

<template>
  <section class="watchlist-workspace" aria-labelledby="watchlist-title">
    <!-- 紧凑页头：工具栏式 -->
    <header class="wl-page-header">
      <h1 id="watchlist-title" class="wl-page-title">
        自选
        <span v-if="groups.length" class="wl-stock-count">{{ groups.reduce((s, g) => s + g.instruments.length, 0) }} 只标的</span>
      </h1>
      <button class="wl-text-action" type="button" :disabled="loading" @click="onLoad">
        <span v-if="loading" class="wl-spin">↻</span>
        {{ loading ? '刷新中…' : '刷新行情' }}
      </button>
    </header>

    <!-- 分组与行情 -->
    <section class="wl-section" aria-labelledby="group-title">
      <h2 id="group-title" class="sr-only">自选分组</h2>

      <!-- 有分组时 -->
      <template v-if="groups.length">
        <nav class="wl-group-tabs" aria-label="自选分组">
          <button
            v-for="group in groups" :key="group.group_id" type="button"
            :class="['wl-tab', { active: selectedGroup?.group_id === group.group_id }]"
            @click="selectGroup(group)"
          >
            <span class="wl-tab-name">{{ group.name }}</span>
            <span class="wl-tab-count">{{ group.instruments.length }}</span>
          </button>
          <button class="wl-tab wl-tab--add" type="button" @click="showCreateForm = !showCreateForm">
            {{ showCreateForm ? '取消' : '+ 新建' }}
          </button>
        </nav>

        <!-- 新建分组（折叠） -->
        <form v-if="showCreateForm" class="wl-inline-form" @submit.prevent="createGroup">
          <input v-model="newGroupName" placeholder="分组名称" maxlength="100" required>
          <input v-model="newGroupDescription" placeholder="说明（可选）" maxlength="500">
          <button class="ink-button" type="submit">创建</button>
        </form>

        <!-- 选中分组详情 -->
        <div v-if="selectedGroup" class="wl-group-detail">
          <!-- 紧凑操作栏：仅在有描述时显示描述，操作紧靠右 -->
          <div class="wl-group-toolbar">
            <small v-if="selectedGroup.description" class="wl-group-desc">{{ selectedGroup.description }}</small>
            <span v-else class="wl-group-desc"></span>
            <div class="wl-toolbar-actions">
              <button class="wl-text-action wl-text-action--subtle" type="button" @click="showEditForm = !showEditForm">{{ showEditForm ? '取消' : '编辑' }}</button>
              <button class="wl-text-action wl-text-action--subtle wl-text-action--danger" type="button" @click="onDeleteGroup({ groupId: selectedGroup.group_id, expectedRevision: selectedGroup.revision })">删除</button>
            </div>
          </div>

          <!-- 编辑分组（折叠） -->
          <form v-if="showEditForm" class="wl-inline-form" @submit.prevent="renameGroup">
            <input v-model="groupName" placeholder="分组名称" maxlength="100" required>
            <input v-model="groupDescription" placeholder="说明（可选）" maxlength="500">
            <button class="ink-button" type="submit">保存</button>
          </form>

          <!-- 行情表格 -->
          <div class="wl-quote-table-wrap">
            <table class="wl-quote-table">
              <thead>
                <tr>
                  <th scope="col">标的</th>
                  <th scope="col" class="num-col">最新价</th>
                  <th scope="col" class="num-col">涨跌额</th>
                  <th scope="col" class="num-col">涨跌幅</th>
                  <th scope="col" class="num-col wl-col-vol">成交量</th>
                  <th scope="col" class="num-col wl-col-amt">成交额</th>
                  <th scope="col" class="wl-col-op">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="instrument in selectedGroup.instruments" :key="instrument.instrument_id">
                  <th scope="row">
                    <button v-if="onSelectSymbol" class="instrument-select" type="button" @click="onSelectSymbol(instrument.instrument_id)">
                      <span class="instrument-name">{{ quoteFor(instrument.instrument_id)?.name || instrument.instrument_id }}</span>
                      <small class="instrument-code">{{ instrument.instrument_id }}</small>
                    </button>
                    <span v-else class="instrument-select">
                      <span class="instrument-name">{{ quoteFor(instrument.instrument_id)?.name || instrument.instrument_id }}</span>
                      <small class="instrument-code">{{ instrument.instrument_id }}</small>
                    </span>
                  </th>
                  <td class="num-col" :class="changeClass(quoteFor(instrument.instrument_id)?.change ?? null)">{{ formatPrice(quoteFor(instrument.instrument_id)?.last ?? null) }}</td>
                  <td class="num-col" :class="changeClass(quoteFor(instrument.instrument_id)?.change ?? null)">{{ formatChange(quoteFor(instrument.instrument_id)?.change ?? null) }}</td>
                  <td class="num-col" :class="changeClass(quoteFor(instrument.instrument_id)?.change_percent ?? null)">{{ formatPercent(quoteFor(instrument.instrument_id)?.change_percent ?? null) }}</td>
                  <td class="num-col wl-col-vol">{{ formatVolume(quoteFor(instrument.instrument_id)?.volume) }}</td>
                  <td class="num-col wl-col-amt">{{ formatAmount(quoteFor(instrument.instrument_id)?.amount) }}</td>
                  <td class="wl-col-op">
                    <button class="wl-remove-btn" type="button" @click="onRemoveInstrument({ groupId: selectedGroup!.group_id, instrumentId: instrument.instrument_id })">移除</button>
                  </td>
                </tr>
                <!-- 空分组占位行 -->
                <tr v-if="!selectedGroup.instruments.length" class="wl-empty-row">
                  <td colspan="7">暂无标的，在下方输入代码添加</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 添加标的：紧贴表格底部 -->
          <form class="wl-inline-form wl-add-form" @submit.prevent="addInstrument">
            <input v-model="instrumentId" placeholder="输入代码，如 000001.SZ" required>
            <button class="ink-button" type="submit">加入</button>
          </form>
        </div>
      </template>

      <!-- 无分组时：简洁空状态 -->
      <div v-else class="wl-empty-state">
        <p class="wl-empty-message">尚无自选分组，创建后即可管理关注标的。</p>
        <form class="wl-inline-form" @submit.prevent="createGroup">
          <input v-model="newGroupName" placeholder="分组名称，如 重点跟踪" maxlength="100" required>
          <input v-model="newGroupDescription" placeholder="说明（可选）" maxlength="500">
          <button class="ink-button" type="submit">创建分组</button>
        </form>
        <dl class="wl-guidance">
          <div><dt>分组</dt><dd>按策略或关注维度组织标的</dd></div>
          <div><dt>标的</dt><dd>使用代码 + 交易所后缀（如 000001.SZ）</dd></div>
          <div><dt>数据边界</dt><dd>自选只保存关注关系，不生成交易建议</dd></div>
        </dl>
      </div>

      <p v-if="watchlistError" class="data-error" role="alert">自选读取失败：{{ watchlistError }}</p>
    </section>

    <!-- 可研究候选 -->
    <section class="wl-section wl-candidate-section" aria-labelledby="candidate-title">
      <header class="wl-section-header">
        <h2 id="candidate-title">可研究候选</h2>
        <div v-if="candidateMeta" class="wl-meta-tags">
          <span class="wl-meta-tag">画像 v{{ candidateMeta.profile_version ?? '—' }}</span>
          <span class="wl-meta-tag">{{ candidateDirectionsText }}</span>
          <span class="wl-meta-tag">{{ formatDate(candidateMeta.generated_at) }}</span>
        </div>
        <small v-else class="wl-meta">基于画像投影与市场事实生成</small>
      </header>

      <div v-if="candidates.length" class="wl-candidate-list">
        <article v-for="candidate in candidates" :key="candidate.instrument_id" :class="['wl-candidate-card', { 'wl-candidate-card--ignored': candidate.ignored }]">
          <header class="wl-candidate-header">
            <div class="wl-candidate-identity">
              <strong>{{ candidate.name || candidate.symbol }}</strong>
              <span class="wl-candidate-symbol">{{ candidate.symbol }}</span>
              <span class="wl-candidate-direction">{{ candidate.direction_label }}</span>
            </div>
            <div class="wl-candidate-actions" v-if="!candidate.ignored">
              <button class="wl-text-action" type="button" @click="onIgnoreCandidate({ instrumentId: candidate.instrument_id, reason: 'not_now', note: null })">暂不研究</button>
              <button v-if="onCreateTradePlan" class="ink-button wl-plan-btn" type="button" :disabled="candidate.tradable === false" :title="candidate.tradable === false ? '服务端判定该候选暂不可生成交易计划' : '向服务端申请研究型交易计划'" @click="onCreateTradePlan(candidate.instrument_id)">申请交易计划</button>
            </div>
            <small v-else class="wl-ignored-label">已忽略：{{ candidate.ignore_reason || '—' }}</small>
          </header>
          <p class="wl-candidate-purpose">{{ candidate.purpose }}</p>
          <div class="wl-candidate-body">
            <div class="wl-dimensions">
              <div v-for="dimension in candidate.dimensions.slice(0, 5)" :key="dimension.dimension" class="wl-dimension-item">
                <span class="wl-dim-label">{{ dimension.label }}</span>
                <span :class="['wl-dim-rating', ratingClass(dimension.rating)]">{{ dimension.rating }}</span>
                <span class="wl-dim-detail">{{ dimension.detail }}</span>
              </div>
            </div>
            <aside v-if="candidate.exclusions.length || candidate.dimensions.some((item) => item.missing_fields.length)" class="wl-exclusions">
              <p v-for="exclusion in candidate.exclusions" :key="exclusion.reason_code">{{ exclusion.detail }}</p>
              <p v-for="dimension in candidate.dimensions.filter((item) => item.missing_fields.length)" :key="`${dimension.dimension}-missing`">缺失：{{ dimension.missing_fields.join('、') }}</p>
            </aside>
          </div>
          <footer class="wl-candidate-footer">
            <small>{{ candidate.provider || '—' }} · {{ formatDate(candidate.as_of ?? undefined) }}</small>
          </footer>
        </article>
      </div>

      <!-- 无候选状态卡 -->
      <div
        v-else-if="candidateUnavailableText"
        data-test="candidate-status"
        :class="['wl-candidate-status', { 'wl-candidate-status--error': candidateUnavailableIsError }]"
        role="status"
      >
        <p class="wl-candidate-status-text">{{ candidateUnavailableText }}</p>
        <a v-if="!candidateUnavailableIsError" href="/app/profile-report" class="ink-button wl-candidate-status-btn">调整画像方向</a>
      </div>
      <p v-else-if="candidateNotice" data-test="candidate-status" class="wl-empty-hint" role="status">{{ candidateNotice }}</p>
      <p v-else-if="!candidateError" data-test="candidate-status" class="wl-empty-hint" role="status">暂无可研究候选。候选需同时具备画像投影与 PandaData 实时快照。</p>
      <p v-if="candidateError" class="data-error" role="alert">候选读取失败：{{ candidateError }}</p>
      <p v-if="planError" class="data-error" role="alert">交易计划：{{ planError }}</p>
    </section>
  </section>
</template>
