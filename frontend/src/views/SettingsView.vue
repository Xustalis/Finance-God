<script setup lang="ts">
/**
 * SettingsView — 我的（个人中心，T00 账户控制）
 * 账户资料（可编辑落库）+ 投资画像 + 自选股 + 通知偏好
 * 用户与画像数据来自 /api/v1/*；仿真钱包与持仓已迁移至「资产」页；无 mock 行情
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import { useAuthStore } from '@/stores/auth'
import { profileApi } from '@/api'
import {
  fetchWatchlists,
  createWatchlistGroup,
  addWatchlistInstrument,
  fetchNotificationPreferences,
  updateNotificationPreferences,
  fetchCurrentMandate,
  fetchMandateHistory,
  saveMandate,
  pauseMandate,
  resumeMandate,
  revokeMandate,
  fetchMandateImpact,
  newIdempotencyKey,
} from '@/api/desk'
import { DEFAULT_SYMBOLS } from '@/types/desk'
import type {
  WatchlistGroup,
  InvestmentMandate,
  MandateImpact,
  MandateSavePayload,
  AutonomyLevel,
} from '@/types/desk'
import type { InvestmentDirection, ProfileWithRecommendations } from '@/types/api'
import { directionScore, localizeArchetype, localizeProfileText } from '@/services/profile'

type TabKey = 'account' | 'profile' | 'watchlist' | 'notifications' | 'authorization'

const market = useMarketStore()
const auth = useAuthStore()

const activeTab = ref<TabKey>('account')

const TABS: { key: TabKey; label: string; test?: string }[] = [
  { key: 'account', label: '账户资料' },
  { key: 'authorization', label: '交易授权' },
  { key: 'profile', label: '投资画像' },
  { key: 'watchlist', label: '自选股' },
  { key: 'notifications', label: '通知偏好' },
]

const tabTitle = computed(() => TABS.find((t) => t.key === activeTab.value)?.label ?? '我的')

/* 货币与地区展示映射 */
const DIRECTION_KINDS: Record<InvestmentDirection, string> = {
  cash_fixed_income: '现金固收',
  public_funds: '公募基金',
  equities: '权益股票',
  alternatives: '另类配置',
  long_term_insurance: '长期储蓄保险',
}
const RISK_LABELS: Record<string, string> = { conservative: '稳健', moderate: '均衡', growth: '成长' }
const HORIZON_LABELS: Record<string, string> = {
  under_1_year: '1 年以内',
  '1_3_years': '1–3 年',
  '3_5_years': '3–5 年',
  '5_plus_years': '5 年以上',
}

/* ── 账户资料（可编辑落库） ───────────────────────── */
const profileForm = ref({ display_name: '', base_currency: 'CNY', region: 'CN' })
const profileSaving = ref(false)
const profileSaveError = ref<string | null>(null)
const profileSaveMessage = ref('')

function resetProfileForm() {
  profileForm.value = {
    display_name: auth.user?.display_name ?? '',
    base_currency: (auth.user?.base_currency ?? 'CNY').toUpperCase(),
    region: (auth.user?.region ?? 'CN').toUpperCase(),
  }
}

const profileDirty = computed(() => {
  const u = auth.user
  if (!u) return false
  const name = profileForm.value.display_name.trim()
  const currency = profileForm.value.base_currency.trim().toUpperCase()
  const region = profileForm.value.region.trim().toUpperCase()
  return (
    name !== (u.display_name ?? '')
    || currency !== (u.base_currency ?? 'CNY').toUpperCase()
    || region !== (u.region ?? 'CN').toUpperCase()
  )
})

const profileFormValid = computed(() => {
  const currency = profileForm.value.base_currency.trim().toUpperCase()
  const region = profileForm.value.region.trim().toUpperCase()
  return /^[A-Z]{3}$/.test(currency) && /^[A-Z]{2}$/.test(region)
})

async function saveAccountProfile() {
  if (profileSaving.value || !profileDirty.value || !profileFormValid.value) return
  profileSaving.value = true
  profileSaveError.value = null
  profileSaveMessage.value = ''
  try {
    await auth.updateProfile({
      display_name: profileForm.value.display_name.trim() || null,
      base_currency: profileForm.value.base_currency.trim().toUpperCase(),
      region: profileForm.value.region.trim().toUpperCase(),
    })
    resetProfileForm()
    profileSaveMessage.value = '账户资料已保存'
  } catch (error) {
    profileSaveError.value = error instanceof Error ? error.message : String(error)
  } finally {
    profileSaving.value = false
  }
}

/* ── 投资画像 ─────────────────────────────────────── */
const profileData = ref<ProfileWithRecommendations | null>(null)
const profileLoading = ref(true)
const profileMissing = ref(false)
const profileError = ref<string | null>(null)

const selectedRecommendation = computed(
  () => profileData.value?.recommendations.find((r) => r.selected) ?? null,
)

async function loadInvestmentProfile() {
  profileLoading.value = true
  profileMissing.value = false
  profileError.value = null
  try {
    profileData.value = await profileApi.latest()
  } catch (error) {
    profileData.value = null
    const status = (error as { status?: number } | null)?.status
    if (status === 404) {
      profileMissing.value = true
    } else {
      profileError.value = error instanceof Error ? error.message : String(error)
    }
  } finally {
    profileLoading.value = false
  }
}

/* ── 自选股 ───────────────────────────────────────── */
const watchlists = ref<WatchlistGroup[]>([])
const watchlistLoading = ref(true)
const watchlistError = ref<string | null>(null)
const newGroupName = ref('')
const newGroupDesc = ref('')
const creatingGroup = ref(false)
const addSymbolTarget = ref<string | null>(null)
const addSymbolId = ref('')
const addingSymbol = ref(false)

async function loadWatchlists() {
  watchlistLoading.value = true
  watchlistError.value = null
  try {
    const data = await fetchWatchlists()
    watchlists.value = Array.isArray(data) ? data : []
  } catch (e) {
    watchlistError.value = e instanceof Error ? e.message : String(e)
  } finally {
    watchlistLoading.value = false
  }
}

async function handleCreateGroup() {
  if (!newGroupName.value.trim()) return
  creatingGroup.value = true
  watchlistError.value = null
  try {
    await createWatchlistGroup(newGroupName.value.trim(), newGroupDesc.value.trim() || undefined)
    newGroupName.value = ''
    newGroupDesc.value = ''
    await loadWatchlists()
  } catch (e) {
    watchlistError.value = e instanceof Error ? e.message : String(e)
  } finally {
    creatingGroup.value = false
  }
}

async function handleAddInstrument(groupId: string) {
  if (!addSymbolId.value.trim()) return
  addingSymbol.value = true
  watchlistError.value = null
  try {
    await addWatchlistInstrument(groupId, addSymbolId.value.trim())
    addSymbolId.value = ''
    addSymbolTarget.value = null
    await loadWatchlists()
  } catch (e) {
    watchlistError.value = e instanceof Error ? e.message : String(e)
  } finally {
    addingSymbol.value = false
  }
}

function suggestSymbols() {
  return DEFAULT_SYMBOLS
}

/* ── 通知偏好 ─────────────────────────────────────── */
const notifPrefs = ref<Record<string, boolean>>({})
const notifLoading = ref(true)
const notifSaving = ref(false)
const notifError = ref<string | null>(null)
const notifMessage = ref('')

const notifLabels: Record<string, string> = {
  order_filled: '订单成交',
  order_cancelled: '订单取消',
  risk_alert: '风险提醒',
  market_alert: '行情异动',
  workflow_complete: '工作流完成',
  system: '系统通知',
}

async function loadNotifPrefs() {
  notifLoading.value = true
  notifError.value = null
  try {
    const data = await fetchNotificationPreferences()
    notifPrefs.value = data.category_preferences
  } catch (e) {
    notifError.value = e instanceof Error ? e.message : String(e)
  } finally {
    notifLoading.value = false
  }
}

async function saveNotifPrefs() {
  notifSaving.value = true
  notifError.value = null
  notifMessage.value = ''
  try {
    await updateNotificationPreferences(notifPrefs.value)
    notifMessage.value = '通知偏好已保存'
  } catch (e) {
    notifError.value = e instanceof Error ? e.message : String(e)
  } finally {
    notifSaving.value = false
  }
}

/* ── 交易授权（T00，仿真业务数据）───────────── */
const MARKET_OPTIONS = ['CN', 'HK', 'US'] as const
const ASSET_OPTIONS: { value: string; label: string }[] = [
  { value: 'stock', label: '股票' },
  { value: 'etf', label: 'ETF' },
  { value: 'lof', label: 'LOF' },
  { value: 'otc_fund', label: '场外基金' },
]
const SIDE_OPTIONS: { value: string; label: string }[] = [
  { value: 'buy', label: '买入' },
  { value: 'sell', label: '卖出' },
  { value: 'short', label: '做空' },
  { value: 'subscribe', label: '申购' },
  { value: 'redeem', label: '赎回' },
  { value: 'convert', label: '转换' },
  { value: 'recurring_invest', label: '定投' },
]
const ORDER_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'market', label: '市价单' },
  { value: 'limit', label: '限价单' },
  { value: 'fund', label: '基金单' },
]
const AUTONOMY_OPTIONS: { value: AutonomyLevel; label: string }[] = [
  { value: 'L0', label: 'L0·仅手动（每笔人工确认）' },
  { value: 'L1', label: 'L1·半自动（AI 提议、人工批准）' },
  { value: 'L2', label: 'L2·自动（限定范围内自主执行）' },
]
const STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  paused: '已暂停',
  revoked: '已撤销',
  expired: '已过期',
}

interface MandateForm {
  autonomy_level: AutonomyLevel
  allowed_markets: string[]
  allowed_assets: string[]
  allowed_sides: string[]
  allowed_order_types: string[]
  max_single_order_amount: string
  valid_until: string
  note: string
}

const currentMandate = ref<InvestmentMandate | null>(null)
const mandateHistory = ref<InvestmentMandate[]>([])
const mandateImpact = ref<MandateImpact | null>(null)
const mandateLoading = ref(true)
const mandateError = ref<string | null>(null)
const mandateMessage = ref('')
const mandateSaving = ref(false)
const mandateStatusBusy = ref(false)
const mandateForm = ref<MandateForm>({
  autonomy_level: 'L0',
  allowed_markets: [],
  allowed_assets: [],
  allowed_sides: [],
  allowed_order_types: [],
  max_single_order_amount: '',
  valid_until: '',
  note: '',
})

function toDateInput(iso: string): string {
  return iso.slice(0, 10)
}

function resetMandateForm() {
  const m = currentMandate.value
  if (!m) return
  mandateForm.value = {
    autonomy_level: m.autonomy_level,
    allowed_markets: [...m.allowed_markets],
    allowed_assets: [...m.allowed_assets],
    allowed_sides: [...m.allowed_sides],
    allowed_order_types: [...m.allowed_order_types],
    max_single_order_amount: m.limits.max_single_order_amount,
    valid_until: toDateInput(m.valid_until),
    note: m.note ?? '',
  }
}

function toggleScope(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

const mandateFormValid = computed(() => {
  const f = mandateForm.value
  const amount = Number(f.max_single_order_amount)
  return (
    f.allowed_markets.length > 0
    && f.allowed_assets.length > 0
    && f.allowed_sides.length > 0
    && f.allowed_order_types.length > 0
    && Number.isFinite(amount)
    && amount > 0
    && f.valid_until.length === 10
  )
})

function sameSet(a: string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false
  const sorted = [...b].sort()
  return [...a].sort().every((v, i) => v === sorted[i])
}

const mandateDirty = computed(() => {
  const m = currentMandate.value
  if (!m) return false
  const f = mandateForm.value
  return (
    f.autonomy_level !== m.autonomy_level
    || !sameSet(f.allowed_markets, m.allowed_markets)
    || !sameSet(f.allowed_assets, m.allowed_assets)
    || !sameSet(f.allowed_sides, m.allowed_sides)
    || !sameSet(f.allowed_order_types, m.allowed_order_types)
    || f.max_single_order_amount !== m.limits.max_single_order_amount
    || f.valid_until !== toDateInput(m.valid_until)
    || f.note.trim() !== (m.note ?? '')
  )
})

async function loadMandate() {
  mandateLoading.value = true
  mandateError.value = null
  try {
    currentMandate.value = await fetchCurrentMandate()
    resetMandateForm()
    mandateHistory.value = await fetchMandateHistory()
    mandateImpact.value = await fetchMandateImpact()
  } catch (e) {
    mandateError.value = e instanceof Error ? e.message : String(e)
  } finally {
    mandateLoading.value = false
  }
}

async function refreshMandateAux() {
  try {
    mandateHistory.value = await fetchMandateHistory()
    mandateImpact.value = await fetchMandateImpact()
  } catch {
    /* 历史/影响面为辅助信息，不阻断主流程 */
  }
}

async function saveMandateVersion() {
  const m = currentMandate.value
  if (!m || mandateSaving.value || !mandateDirty.value || !mandateFormValid.value) return
  mandateSaving.value = true
  mandateError.value = null
  mandateMessage.value = ''
  const f = mandateForm.value
  const shortMarkets = m.short_markets.filter((mk) => f.allowed_markets.includes(mk))
  const payload: MandateSavePayload = {
    expected_revision: m.version,
    autonomy_level: f.autonomy_level,
    allowed_markets: [...f.allowed_markets],
    allowed_assets: [...f.allowed_assets],
    allowed_sides: [...f.allowed_sides],
    allowed_order_types: [...f.allowed_order_types],
    short_markets: shortMarkets,
    limits: { ...m.limits, max_single_order_amount: f.max_single_order_amount.trim() },
    valid_until: new Date(`${f.valid_until}T00:00:00Z`).toISOString(),
    note: f.note.trim() || null,
  }
  try {
    currentMandate.value = await saveMandate(payload, newIdempotencyKey('mandate-save'))
    resetMandateForm()
    mandateMessage.value = `已保存新版本 v${currentMandate.value.version}`
    await refreshMandateAux()
  } catch (e) {
    mandateError.value = e instanceof Error ? e.message : String(e)
  } finally {
    mandateSaving.value = false
  }
}

async function changeStatus(action: 'pause' | 'resume' | 'revoke') {
  const m = currentMandate.value
  if (!m || mandateStatusBusy.value) return
  if (action === 'revoke' && !window.confirm('撤销后新下单意图将被拦截，确定撤销当前授权？')) return
  mandateStatusBusy.value = true
  mandateError.value = null
  mandateMessage.value = ''
  try {
    const fn = action === 'pause' ? pauseMandate : action === 'resume' ? resumeMandate : revokeMandate
    currentMandate.value = await fn(m.version)
    resetMandateForm()
    mandateMessage.value = { pause: '已暂停授权', resume: '已恢复授权', revoke: '已撤销授权' }[action]
    await refreshMandateAux()
  } catch (e) {
    mandateError.value = e instanceof Error ? e.message : String(e)
  } finally {
    mandateStatusBusy.value = false
  }
}

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  resetProfileForm()
  loadWatchlists()
  loadNotifPrefs()
  loadInvestmentProfile()
  loadMandate()
})
onUnmounted(() => market.stopPolling())
</script>

<template>
  <DeskLayout>
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>我的</span>
          <small>ACCOUNT</small>
        </h2>
        <div class="settings-nav">
          <button
            v-for="tab in TABS"
            :key="tab.key"
            :data-test="tab.test"
            class="settings-nav-item"
            :class="{ active: activeTab === tab.key }"
            :aria-current="activeTab === tab.key ? 'true' : undefined"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>
      </section>
    </template>

    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>我的</span>
          <span>ACCOUNT</span>
        </div>
        <h1 class="lead-title">{{ tabTitle }}</h1>
      </div>

      <!-- 账户资料 -->
      <section v-if="activeTab === 'account'" class="settings-section">
        <form class="form-card" @submit.prevent="saveAccountProfile">
          <h2 class="form-title">账户资料</h2>
          <p class="scope-note">修改后保存至账户；昵称用于全站显示，货币与地区为账户元数据。</p>
          <label class="field">
            <span>昵称</span>
            <input v-model="profileForm.display_name" maxlength="100" placeholder="未设置" />
          </label>
          <label class="field">
            <span>基准货币（三位大写，如 CNY）</span>
            <input v-model="profileForm.base_currency" maxlength="3" placeholder="CNY" />
          </label>
          <label class="field">
            <span>地区（两位大写，如 CN）</span>
            <input v-model="profileForm.region" maxlength="2" placeholder="CN" />
          </label>
          <p v-if="profileSaveError" class="form-error" role="alert">{{ profileSaveError }}</p>
          <p v-if="profileSaveMessage" class="success-note" role="status">{{ profileSaveMessage }}</p>
          <div class="form-actions">
            <button
              class="primary-button compact"
              :disabled="profileSaving || !profileDirty || !profileFormValid"
            >
              {{ profileSaving ? '正在保存…' : '保存资料' }}
            </button>
            <button
              v-if="profileDirty"
              type="button"
              class="text-button"
              @click="resetProfileForm(); profileSaveMessage = ''"
            >
              撤销改动
            </button>
          </div>
        </form>

        <h2 class="form-title user-heading">登录信息</h2>
        <div class="info-card">
          <div class="info-row" v-if="auth.user?.email">
            <span>邮箱</span>
            <strong>{{ auth.user.email }}</strong>
          </div>
          <div class="info-row" v-if="auth.user?.role">
            <span>角色</span>
            <strong>{{ auth.user.role }}</strong>
          </div>
          <div class="info-row" v-if="auth.user?.status">
            <span>状态</span>
            <strong>{{ auth.user.status }}</strong>
          </div>
          <div class="info-row" v-if="auth.user?.created_at">
            <span>创建时间</span>
            <strong>{{ new Date(auth.user.created_at).toLocaleDateString('zh-CN') }}</strong>
          </div>
          <div class="info-row" v-if="auth.user?.last_login_at">
            <span>最近登录</span>
            <strong>{{ new Date(auth.user.last_login_at).toLocaleString('zh-CN') }}</strong>
          </div>
        </div>

        <div class="account-portfolio-link">
          <p class="scope-note">仿真钱包初始化、重置、持仓与资金流水已迁移至「资产」页统一管理。</p>
          <RouterLink to="/portfolio" class="secondary-button compact">前往资产页</RouterLink>
        </div>
      </section>

      <!-- 交易授权（T00，仿真业务数据） -->
      <section v-if="activeTab === 'authorization'" class="settings-section">
        <p class="scope-note sim-note">授权数据为<strong>仿真业务数据</strong>，用于约束本平台仿真下单意图；本页不存储任何经纪商账号或密码。</p>

        <div v-if="mandateLoading" class="table-state" role="status">正在加载授权…</div>
        <div v-else-if="mandateError && !currentMandate" class="account-load-error" role="alert">
          <strong>授权加载失败</strong>
          <span>{{ mandateError }}</span>
          <button class="secondary-button compact" @click="loadMandate">重新加载</button>
        </div>
        <template v-else-if="currentMandate">
          <!-- 授权状态摘要 -->
          <div class="info-card mandate-summary">
            <div class="info-row">
              <span>当前状态</span>
              <strong :class="currentMandate.status === 'active' ? 'ok' : 'warn'">
                {{ STATUS_LABELS[currentMandate.status] ?? currentMandate.status }}（v{{ currentMandate.version }}）
              </strong>
            </div>
            <div class="info-row">
              <span>自主级别</span>
              <strong>{{ currentMandate.autonomy_level }}</strong>
            </div>
            <div class="info-row">
              <span>单笔上限</span>
              <strong>{{ currentMandate.limits.max_single_order_amount }}</strong>
            </div>
            <div class="info-row">
              <span>有效期至</span>
              <strong>{{ new Date(currentMandate.valid_until).toLocaleDateString('zh-CN') }}</strong>
            </div>
          </div>

          <!-- 紧急操作 -->
          <div class="form-actions mandate-emergency">
            <button
              v-if="currentMandate.status !== 'active'"
              class="primary-button compact"
              :disabled="mandateStatusBusy"
              @click="changeStatus('resume')"
            >恢复授权</button>
            <button
              v-else
              class="secondary-button compact"
              :disabled="mandateStatusBusy"
              @click="changeStatus('pause')"
            >暂停授权</button>
            <button
              class="text-button danger"
              :disabled="mandateStatusBusy || currentMandate.status === 'revoked'"
              @click="changeStatus('revoke')"
            >撤销授权</button>
          </div>

          <!-- 授权编辑器 -->
          <form class="form-card" @submit.prevent="saveMandateVersion">
            <h2 class="form-title">编辑授权（保存即创建新版本）</h2>
            <label class="field">
              <span>自主级别</span>
              <select v-model="mandateForm.autonomy_level">
                <option v-for="o in AUTONOMY_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>

            <div class="field">
              <span>可交易市场</span>
              <div class="chip-choices">
                <label v-for="mk in MARKET_OPTIONS" :key="mk" class="choice">
                  <input
                    type="checkbox"
                    :checked="mandateForm.allowed_markets.includes(mk)"
                    @change="mandateForm.allowed_markets = toggleScope(mandateForm.allowed_markets, mk)"
                  />
                  {{ mk }}
                </label>
              </div>
            </div>

            <div class="field">
              <span>可交易资产</span>
              <div class="chip-choices">
                <label v-for="o in ASSET_OPTIONS" :key="o.value" class="choice">
                  <input
                    type="checkbox"
                    :checked="mandateForm.allowed_assets.includes(o.value)"
                    @change="mandateForm.allowed_assets = toggleScope(mandateForm.allowed_assets, o.value)"
                  />
                  {{ o.label }}
                </label>
              </div>
            </div>

            <div class="field">
              <span>可交易方向</span>
              <div class="chip-choices">
                <label v-for="o in SIDE_OPTIONS" :key="o.value" class="choice">
                  <input
                    type="checkbox"
                    :checked="mandateForm.allowed_sides.includes(o.value)"
                    @change="mandateForm.allowed_sides = toggleScope(mandateForm.allowed_sides, o.value)"
                  />
                  {{ o.label }}
                </label>
              </div>
            </div>

            <div class="field">
              <span>可用订单类型</span>
              <div class="chip-choices">
                <label v-for="o in ORDER_TYPE_OPTIONS" :key="o.value" class="choice">
                  <input
                    type="checkbox"
                    :checked="mandateForm.allowed_order_types.includes(o.value)"
                    @change="mandateForm.allowed_order_types = toggleScope(mandateForm.allowed_order_types, o.value)"
                  />
                  {{ o.label }}
                </label>
              </div>
            </div>

            <label class="field">
              <span>单笔上限（金额）</span>
              <input v-model.trim="mandateForm.max_single_order_amount" inputmode="decimal" placeholder="如 1000000" />
            </label>
            <label class="field">
              <span>有效期至</span>
              <input v-model="mandateForm.valid_until" type="date" />
            </label>
            <label class="field">
              <span>备注（可选）</span>
              <input v-model="mandateForm.note" maxlength="500" placeholder="本次授权调整说明" />
            </label>

            <p v-if="mandateError && currentMandate" class="form-error" role="alert">{{ mandateError }}</p>
            <p v-if="mandateMessage" class="success-note" role="status">{{ mandateMessage }}</p>
            <div class="form-actions">
              <button class="primary-button compact" :disabled="mandateSaving || !mandateDirty || !mandateFormValid">
                {{ mandateSaving ? '正在保存…' : '保存新版本' }}
              </button>
              <button
                v-if="mandateDirty"
                type="button"
                class="text-button"
                @click="resetMandateForm(); mandateMessage = ''"
              >撤销改动</button>
            </div>
          </form>

          <!-- 受影响面 -->
          <h2 class="form-title user-heading">受影响的现存订单意图</h2>
          <div v-if="!mandateImpact || mandateImpact.affected.length === 0" class="table-state">
            当前授权下无被拦截的现存订单意图（已评估 {{ mandateImpact?.evaluated ?? 0 }} 项）。
          </div>
          <ul v-else class="impact-list">
            <li v-for="item in mandateImpact.affected" :key="item.reference" class="impact-item">
              <div class="impact-head">
                <strong>{{ item.instrument_id }}</strong>
                <span>{{ item.side }} · {{ item.order_type }}</span>
              </div>
              <ul class="impact-reasons">
                <li v-for="f in item.findings" :key="f.code">{{ f.message }}</li>
              </ul>
            </li>
          </ul>

          <!-- 版本历史 -->
          <h2 class="form-title user-heading">版本历史</h2>
          <div v-if="mandateHistory.length === 0" class="table-state">暂无历史版本</div>
          <ul v-else class="history-list">
            <li v-for="h in mandateHistory" :key="h.mandate_id" class="history-item">
              <span class="history-ver">v{{ h.version }}</span>
              <span class="history-status">{{ STATUS_LABELS[h.status] ?? h.status }} · {{ h.autonomy_level }}</span>
              <span class="history-time">{{ new Date(h.created_at).toLocaleString('zh-CN') }}</span>
            </li>
          </ul>
        </template>
      </section>

      <!-- 投资画像 -->
      <section v-if="activeTab === 'profile'" class="settings-section">
        <div v-if="profileLoading" class="table-state" role="status">正在加载投资画像…</div>
        <div v-else-if="profileMissing" class="account-initialization">
          <strong>尚未生成投资画像</strong>
          <p>完成画像访谈后，这里显示你的投资者原型、风险区间与推荐方向。</p>
          <RouterLink to="/app/exe" class="primary-button compact">前往画像访谈</RouterLink>
        </div>
        <div v-else-if="profileError" class="account-load-error" role="alert">
          <strong>投资画像加载失败</strong>
          <span>{{ profileError }}</span>
          <button class="secondary-button compact" @click="loadInvestmentProfile">重新加载画像</button>
        </div>
        <template v-else-if="profileData">
          <div class="profile-summary">
            <div class="info-row">
              <span>投资者原型</span>
              <strong>{{ localizeArchetype(profileData.profile.archetype_title, profileData.profile.archetype_code) }} · 第 {{ profileData.profile.version }} 版</strong>
            </div>
            <div class="info-row">
              <span>风险区间</span>
              <strong>{{ RISK_LABELS[profileData.profile.risk_level] ?? profileData.profile.risk_level }}（阶段亏损参考 {{ profileData.profile.loss_tolerance_percent }}%）</strong>
            </div>
            <div class="info-row">
              <span>资金期限</span>
              <strong>{{ HORIZON_LABELS[profileData.profile.objective_profile?.fund_horizon ?? ''] ?? '待确认' }}</strong>
            </div>
            <div class="info-row">
              <span>画像完整度</span>
              <strong>{{ Math.round(profileData.profile.completeness * 100) }}%</strong>
            </div>
            <div class="info-row">
              <span>已选交易方向</span>
              <strong v-if="selectedRecommendation">{{ DIRECTION_KINDS[selectedRecommendation.direction] }}</strong>
              <strong v-else class="muted">尚未选择</strong>
            </div>
          </div>

          <h2 class="form-title user-heading">推荐方向</h2>
          <div v-if="profileData.profile.education_only" class="table-state">
            未成年画像仅提供金融教育方向，不支持选择可执行投资方向。
          </div>
          <ul v-else class="direction-list">
            <li
              v-for="item in profileData.recommendations"
              :key="item.id"
              class="direction-item"
              :class="{ selected: item.selected }"
            >
              <div class="direction-head">
                <span class="direction-rank">{{ String(item.rank).padStart(2, '0') }}</span>
                <strong class="direction-name">{{ DIRECTION_KINDS[item.direction] }}</strong>
                <span class="direction-score">匹配 {{ directionScore(item.score).label }}</span>
                <span v-if="item.selected" class="direction-tag">已选</span>
              </div>
              <p class="direction-reason">{{ localizeProfileText(item.reason) }}</p>
            </li>
          </ul>

          <div class="form-actions">
            <RouterLink to="/app/profile-report" class="secondary-button compact">查看完整画像报告</RouterLink>
            <RouterLink to="/app/exe" class="text-button">重新访谈更新画像</RouterLink>
          </div>
        </template>
      </section>

      <!-- 自选股 -->
      <section v-if="activeTab === 'watchlist'" class="settings-section">
        <div class="form-card">
          <h2 class="form-title">创建自选组</h2>
          <form class="inline-form" @submit.prevent="handleCreateGroup">
            <input v-model.trim="newGroupName" placeholder="组名称（如：科技股）" required />
            <input v-model.trim="newGroupDesc" placeholder="描述（可选）" />
            <button class="primary-button compact" :disabled="creatingGroup || !newGroupName">
              {{ creatingGroup ? '创建中...' : '创建' }}
            </button>
          </form>
        </div>

        <p v-if="watchlistError" class="form-error" role="alert">
          {{ watchlistError }}
          <button class="text-button" @click="watchlistError = null">关闭</button>
        </p>

        <div v-if="watchlistLoading" class="table-state">加载自选股...</div>
        <div v-else-if="watchlists.length === 0" class="table-state">
          <span>暂无自选组，请创建一个开始添加标的。</span>
        </div>
        <div v-else class="watchlist-groups">
          <div v-for="group in watchlists" :key="group.group_id" class="wl-group">
            <div class="wl-group-header">
              <div>
                <h3 class="wl-group-name">{{ group.name }}</h3>
                <p v-if="group.description" class="wl-group-desc">{{ group.description }}</p>
              </div>
              <span class="wl-group-meta">v{{ group.revision }}</span>
            </div>
            <div v-if="group.instruments && group.instruments.length > 0" class="wl-instruments">
              <span v-for="inst in group.instruments" :key="inst.instrument_id" class="wl-chip">
                {{ inst.instrument_id }}
              </span>
            </div>
            <div v-else class="wl-empty">暂无标的</div>
            <div class="wl-add">
              <template v-if="addSymbolTarget === group.group_id">
                <input
                  v-model.trim="addSymbolId"
                  placeholder="输入标的代码（如 000001.SZ）"
                  @keydown.enter="handleAddInstrument(group.group_id)"
                  list="symbol-suggestions"
                />
                <datalist id="symbol-suggestions">
                  <option v-for="s in suggestSymbols()" :key="s" :value="s" />
                </datalist>
                <button class="primary-button compact" :disabled="addingSymbol || !addSymbolId" @click="handleAddInstrument(group.group_id)">
                  {{ addingSymbol ? '添加中...' : '添加' }}
                </button>
                <button class="text-button" @click="addSymbolTarget = null; addSymbolId = ''">取消</button>
              </template>
              <button v-else class="text-button" @click="addSymbolTarget = group.group_id; addSymbolId = ''">
                + 添加标的
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 通知偏好 -->
      <section v-if="activeTab === 'notifications'" class="settings-section">
        <div v-if="notifLoading" class="table-state">加载通知偏好...</div>
        <template v-else>
          <div class="prefs-list">
            <label v-for="(_enabled, category) in notifPrefs" :key="String(category)" class="pref-item">
              <span class="pref-label">{{ notifLabels[String(category)] || String(category) }}</span>
              <label class="switch">
                <input v-model="notifPrefs[String(category)]" type="checkbox" />
                <span aria-hidden="true"></span>
                {{ notifPrefs[String(category)] ? '开启' : '关闭' }}
              </label>
            </label>
            <div v-if="Object.keys(notifPrefs).length === 0" class="table-state">
              <span>暂无可配置的通知类别</span>
            </div>
          </div>
          <p v-if="notifError" class="form-error" role="alert">{{ notifError }}</p>
          <p v-if="notifMessage" class="success-note" role="status">{{ notifMessage }}</p>
          <div class="form-actions" v-if="Object.keys(notifPrefs).length > 0">
            <button class="primary-button compact" :disabled="notifSaving" @click="saveNotifPrefs">
              {{ notifSaving ? '保存中...' : '保存偏好' }}
            </button>
          </div>
        </template>
      </section>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>快速参考</span>
          <small>REFERENCE</small>
        </h2>
        <div class="summary-grid">
          <div class="summary-row">
            <span>授权状态</span>
            <strong>{{ currentMandate ? (STATUS_LABELS[currentMandate.status] ?? currentMandate.status) : '—' }}</strong>
          </div>
          <div class="summary-row">
            <span>自主级别</span>
            <strong>{{ currentMandate ? currentMandate.autonomy_level : '—' }}</strong>
          </div>
        </div>
        <div class="summary-grid">
          <div class="summary-row">
            <span>画像完整度</span>
            <strong>{{ profileData ? `${Math.round(profileData.profile.completeness * 100)}%` : '—' }}</strong>
          </div>
          <div class="summary-row">
            <span>已选方向</span>
            <strong>{{ selectedRecommendation ? DIRECTION_KINDS[selectedRecommendation.direction] : '—' }}</strong>
          </div>
        </div>
        <div class="summary-grid">
          <div class="summary-row">
            <span>自选组数</span>
            <strong>{{ watchlists.length }}</strong>
          </div>
          <div class="summary-row">
            <span>自选标的</span>
            <strong>{{ watchlists.reduce((s, g) => s + (g.instruments?.length ?? 0), 0) }}</strong>
          </div>
          <div class="summary-row">
            <span>通知类别</span>
            <strong>{{ Object.keys(notifPrefs).length }}</strong>
          </div>
          <div class="summary-row">
            <span>数据源</span>
            <strong>{{ market.provider }}</strong>
          </div>
        </div>
      </section>
    </template>
  </DeskLayout>
</template>

<style scoped>
.rail-section { padding: 0; }
.rail-section + .rail-section { border-top: 1px solid var(--rule); }

.section-title {
  display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  padding: 18px 18px 7px; border-bottom: 1px solid var(--rule);
  font-size: 15px; font-weight: 900; letter-spacing: 0.04em; margin: 0;
}
.section-title small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em; white-space: nowrap;
}

.settings-nav { padding: 8px 18px; display: grid; gap: 4px; }
.settings-nav-item {
  display: block; width: 100%; padding: 10px 12px;
  background: transparent; border: 1px solid var(--faint-rule);
  color: var(--ink); font-size: 13px; font-weight: 600;
  text-align: left; cursor: pointer; transition: all 0.15s;
}
.settings-nav-item:hover { border-color: var(--rule); }
.settings-nav-item.active { border-color: var(--risk); background: rgb(143 48 39 / 5%); font-weight: 900; }
.settings-nav-item:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }

.lead-header { margin-bottom: 12px; }
.lead-kicker {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 5px; padding-bottom: 4px; border-bottom: 3px double var(--rule);
  color: var(--muted-ink); font-size: 9px; font-weight: 700; letter-spacing: 0.13em;
}
.lead-kicker span:first-child { color: var(--risk); font-size: 10px; font-weight: 900; }
.lead-title {
  font-size: clamp(1.8rem, 3vw, 2.8rem); font-weight: 700; line-height: 1.1;
  letter-spacing: -0.02em; margin: 0;
}

.settings-section { padding: 0; }

.form-card { padding: 0 0 20px; border-bottom: 1px solid var(--rule); margin-bottom: 16px; }
.form-title {
  font-size: 14px; font-weight: 900; letter-spacing: 0.03em;
  margin: 0 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--faint-rule);
}
.inline-form {
  display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; align-items: end;
}
.inline-form input { min-height: 38px; font-size: 13px; }

.field { display: grid; gap: 5px; margin-bottom: 12px; }
.field span { color: var(--muted-ink); font-size: 12px; }
.field input { min-height: 36px; font-size: 13px; }

.table-state { padding: 40px 20px; color: var(--muted-ink); font-size: 14px; text-align: center; }

.watchlist-groups { display: grid; gap: 16px; }
.wl-group { border: 1px solid var(--rule); }
.wl-group-header {
  display: flex; align-items: start; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--faint-rule);
}
.wl-group-name { font-size: 15px; font-weight: 700; margin: 0; }
.wl-group-desc { font-size: 12px; color: var(--muted-ink); margin: 2px 0 0; }
.wl-group-meta {
  font-family: var(--font-numeric); font-size: 11px; color: var(--muted-ink); font-weight: 700;
}

.wl-instruments { padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 6px; }
.wl-chip {
  padding: 3px 10px; border: 1px solid var(--faint-rule);
  font-family: var(--font-numeric); font-size: 12px; font-weight: 700;
}
.wl-empty { padding: 12px 16px; color: var(--muted-ink); font-size: 13px; }
.wl-add {
  padding: 8px 16px; border-top: 1px solid var(--faint-rule);
  display: flex; align-items: center; gap: 8px;
}
.wl-add input { min-height: 34px; font-size: 13px; flex: 1; }

/* 通知偏好 */
.prefs-list { display: grid; gap: 0; }
.pref-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; border-bottom: 1px solid var(--faint-rule);
  font-size: 14px; cursor: pointer;
}
.pref-item:last-child { border-bottom: 0; }
.pref-label { font-weight: 600; }

.switch {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted-ink); cursor: pointer;
}
.switch input[type="checkbox"] {
  width: 38px; height: 20px; min-height: auto;
  appearance: none; background: var(--faint-rule); border: 0;
  border-radius: 10px; position: relative; cursor: pointer;
  transition: background 0.2s; padding: 0;
}
.switch input[type="checkbox"]:checked { background: var(--positive); }
.switch input[type="checkbox"]::after {
  content: ''; position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px; background: white;
  border-radius: 50%; transition: transform 0.2s;
}
.switch input[type="checkbox"]:checked::after { transform: translateX(18px); }

.form-actions { padding: 16px 0; display: flex; align-items: center; gap: 14px; }

/* 账户资料 / 画像入口 */
.account-initialization,
.account-load-error {
  display: grid; gap: 10px; padding: 14px 0;
}
.account-initialization p,
.scope-note { margin: 0; color: var(--muted-ink); font-size: 12px; }
.account-initialization label { display: grid; gap: 5px; }
.account-initialization label span { color: var(--muted-ink); font-size: 12px; }
.account-initialization input { min-height: 36px; }
.account-load-error span { color: var(--risk); font-size: 12px; }

.account-portfolio-link {
  display: grid; gap: 8px; padding-top: 16px; margin-top: 4px;
  border-top: 1px solid var(--faint-rule); justify-items: start;
}

.user-heading { margin-top: 0; }
.info-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 10px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.info-row:last-child { border-bottom: 0; }
.info-row span { color: var(--muted-ink); }
.info-row strong { font-family: var(--font-numeric); font-weight: 700; }
.info-row strong.muted { color: var(--muted-ink); font-weight: 600; }

/* 投资画像 */
.profile-summary { display: grid; padding-bottom: 16px; margin-bottom: 8px; border-bottom: 1px solid var(--rule); }
.direction-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.direction-item { border: 1px solid var(--faint-rule); padding: 10px 12px; }
.direction-item.selected { border-color: var(--risk); background: rgb(143 48 39 / 4%); }
.direction-head { display: flex; align-items: baseline; gap: 10px; }
.direction-rank { font-family: var(--font-numeric); font-size: 12px; color: var(--muted-ink); font-weight: 700; }
.direction-name { font-size: 14px; font-weight: 700; }
.direction-score { font-family: var(--font-numeric); font-size: 12px; color: var(--muted-ink); margin-left: auto; }
.direction-tag { font-size: 11px; font-weight: 900; color: var(--risk); }
.direction-reason { margin: 6px 0 0; font-size: 12px; color: var(--muted-ink); }

.summary-grid { padding: 14px 18px; }
.summary-grid + .summary-grid { border-top: 1px solid var(--rule); }
.summary-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; }

.form-error {
  color: var(--risk); background: #f5ebe8; padding: .65rem .8rem;
  border-left: 3px solid var(--risk); margin: 12px 0;
}
.success-note {
  color: var(--positive); background: var(--jade-pale); padding: .65rem .8rem;
  border-left: 3px solid var(--positive); margin: 12px 0;
}

/* 交易授权 */
.sim-note { margin-bottom: 12px; }
.sim-note strong { color: var(--risk); }
.mandate-summary { margin-bottom: 12px; }
.info-row strong.ok { color: var(--positive); }
.info-row strong.warn { color: var(--risk); }
.mandate-emergency { padding-top: 0; padding-bottom: 16px; border-bottom: 1px solid var(--rule); margin-bottom: 16px; }
.field select { min-height: 36px; font-size: 13px; }
.chip-choices { display: flex; flex-wrap: wrap; gap: 12px; }
.chip-choices .choice {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; cursor: pointer;
}
.chip-choices .choice input { min-height: auto; }
.text-button.danger { color: var(--risk); }
.text-button.danger:disabled { color: var(--muted-ink); cursor: not-allowed; }

.impact-list { list-style: none; margin: 0 0 16px; padding: 0; display: grid; gap: 8px; }
.impact-item { border: 1px solid var(--risk); padding: 10px 12px; background: rgb(143 48 39 / 4%); }
.impact-head { display: flex; align-items: baseline; gap: 10px; }
.impact-head span { color: var(--muted-ink); font-size: 12px; }
.impact-reasons { margin: 6px 0 0; padding-left: 18px; color: var(--risk); font-size: 12px; }

.history-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; }
.history-item {
  display: flex; align-items: baseline; gap: 12px;
  padding: 8px 0; border-bottom: 1px solid var(--faint-rule); font-size: 13px;
}
.history-item:last-child { border-bottom: 0; }
.history-ver { font-family: var(--font-numeric); font-weight: 900; color: var(--risk); }
.history-status { font-weight: 600; }
.history-time { margin-left: auto; color: var(--muted-ink); font-size: 12px; font-family: var(--font-numeric); }
</style>
