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
} from '@/api/desk'
import { DEFAULT_SYMBOLS } from '@/types/desk'
import type { WatchlistGroup } from '@/types/desk'
import type { InvestmentDirection, ProfileWithRecommendations } from '@/types/api'
import { directionScore, localizeArchetype, localizeProfileText } from '@/services/profile'

type TabKey = 'account' | 'profile' | 'watchlist' | 'notifications'

const market = useMarketStore()
const auth = useAuthStore()

const activeTab = ref<TabKey>('account')

const TABS: { key: TabKey; label: string; test?: string }[] = [
  { key: 'account', label: '账户资料' },
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

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  resetProfileForm()
  loadWatchlists()
  loadNotifPrefs()
  loadInvestmentProfile()
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
</style>
