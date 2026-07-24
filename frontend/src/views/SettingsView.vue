<script setup lang="ts">
/**
 * SettingsView — 设置页
 * 自选股管理 + 通知偏好 + 工作区偏好
 * 所有数据来自 /api/workspace/* 后端 API，无 mock
 */
import { ref, onMounted, onUnmounted } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import { useAuthStore } from '@/stores/auth'
import {
  fetchWatchlists,
  createWatchlistGroup,
  addWatchlistInstrument,
  fetchNotificationPreferences,
  updateNotificationPreferences,
} from '@/api/desk'
import { DEFAULT_SYMBOLS } from '@/types/desk'
import type { WatchlistGroup } from '@/types/desk'

const market = useMarketStore()
const auth = useAuthStore()

const activeTab = ref<'watchlist' | 'notifications' | 'account'>('watchlist')

/* 自选股 */
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

/* 通知偏好 */
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
    const data = await fetchNotificationPreferences() as any
    notifPrefs.value = data?.category_preferences ?? {}
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
  loadWatchlists()
  loadNotifPrefs()
})
onUnmounted(() => market.stopPolling())
</script>

<template>
  <DeskLayout>
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>设置</span>
          <small>SETTINGS</small>
        </h2>
        <div class="settings-nav">
          <button
            class="settings-nav-item"
            :class="{ active: activeTab === 'watchlist' }"
            @click="activeTab = 'watchlist'"
          >
            自选股
          </button>
          <button
            class="settings-nav-item"
            :class="{ active: activeTab === 'notifications' }"
            @click="activeTab = 'notifications'"
          >
            通知偏好
          </button>
          <button
            class="settings-nav-item"
            :class="{ active: activeTab === 'account' }"
            @click="activeTab = 'account'"
          >
            账户信息
          </button>
        </div>
      </section>
    </template>

    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>设置</span>
          <span>SETTINGS</span>
        </div>
        <h1 class="lead-title">
          {{ activeTab === 'watchlist' ? '自选股管理' : activeTab === 'notifications' ? '通知偏好' : '账户信息' }}
        </h1>
      </div>

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

      <!-- 账户信息 -->
      <section v-if="activeTab === 'account'" class="settings-section">
        <div class="info-card">
          <div class="info-row">
            <span>用户</span>
            <strong>{{ auth.user?.display_name || auth.user?.email || '—' }}</strong>
          </div>
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
        <div class="summary-grid">
          <div class="summary-row">
            <span>默认标的</span>
            <strong>{{ DEFAULT_SYMBOLS.length }}</strong>
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

.form-actions { padding: 16px 0; }

/* 账户信息 */
.info-card { }
.info-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 10px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.info-row:last-child { border-bottom: 0; }
.info-row span { color: var(--muted-ink); }
.info-row strong { font-family: var(--font-numeric); font-weight: 700; }

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
