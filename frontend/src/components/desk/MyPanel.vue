<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTradingDeskStore, type DeskSection } from '@/stores/tradingDesk'
import { resetSimulationAccount } from '@/services/tradingDesk'

type MySection = 'profile' | 'wallet' | 'history' | 'settings'

defineEmits<{
  close: []
}>()

const router = useRouter()
const desk = useTradingDeskStore()
const auth = useAuthStore()
const section = ref<MySection>('profile')
const savingSettings = ref(false)
const settingMessage = ref<string | null>(null)
const displayName = ref(auth.user?.display_name ?? '')
const baseCurrency = ref(auth.user?.base_currency ?? 'CNY')
const region = ref(auth.user?.region ?? 'CN')

// 退出登录
const showLogoutConfirm = ref(false)
const loggingOut = ref(false)

// 钱包重置
const showResetConfirm = ref(false)
const resettingWallet = ref(false)
const resetMessage = ref<string | null>(null)

const sections: ReadonlyArray<{ id: MySection; label: string }> = [
  { id: 'profile', label: '用户画像' },
  { id: 'wallet', label: '钱包' },
  { id: 'history', label: '交易记录' },
  { id: 'settings', label: '设置' },
]

const sideLabels: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  short: '卖空',
  cover: '回补',
  subscribe: '申购',
  redeem: '赎回',
  convert: '转换',
  recurring_invest: '定投',
}

const statusLabels: Record<string, string> = {
  submitted: '已提交',
  accepted: '已接受',
  partially_filled: '部分成交',
  filled: '全部成交',
  cancelled: '已撤销',
  rejected: '已拒绝',
  unknown: '状态待确认',
}

function failureText(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric)
}

function formatNumber(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 8 }).format(numeric)
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function displayText(value: string | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined) return fallback
  const text = String(value).trim()
  return text === '' || text === '—' ? fallback : text
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value}%`
}

function formatCompleteness(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

async function selectSection(next: MySection) {
  section.value = next
  settingMessage.value = null
  if (next === 'wallet' || next === 'history') await desk.loadSimulationData()
  if (next === 'settings') {
    displayName.value = auth.user?.display_name ?? ''
    baseCurrency.value = auth.user?.base_currency ?? 'CNY'
    region.value = auth.user?.region ?? 'CN'
  }
}

async function saveSettings() {
  savingSettings.value = true
  settingMessage.value = null
  try {
    await auth.updateProfile({
      display_name: displayName.value || null,
      base_currency: baseCurrency.value,
      region: region.value,
    })
    settingMessage.value = '用户设置已保存。该信息不会提供给 Agent。'
  } catch (error) {
    settingMessage.value = failureText(error)
  } finally {
    savingSettings.value = false
  }
}

async function handleLogout() {
  loggingOut.value = true
  try {
    auth.logout()
    await router.push('/login')
  } finally {
    loggingOut.value = false
    showLogoutConfirm.value = false
  }
}

async function handleResetWallet() {
  if (!desk.account?.account_id) {
    resetMessage.value = '未找到模拟账户，无法重置。'
    showResetConfirm.value = false
    return
  }
  resettingWallet.value = true
  resetMessage.value = null
  try {
    const key = `wallet-reset-${Date.now()}`
    const now = new Date().toISOString()
    await resetSimulationAccount(desk.account.account_id, '1000000', now, key)
    resetMessage.value = '钱包已重置为 ¥1,000,000。'
    await desk.loadSimulationData()
  } catch (error) {
    resetMessage.value = failureText(error)
  } finally {
    resettingWallet.value = false
    showResetConfirm.value = false
  }
}

function openWorkspace(next: DeskSection) {
  desk.setSection(next)
}
</script>

<template>
  <aside class="my-panel" aria-label="我的">
    <header>
      <div>
        <p class="chapter">个人数据与偏好</p>
        <h2>我的</h2>
      </div>
      <button type="button" aria-label="关闭我的" @click="$emit('close')">关闭</button>
    </header>

    <nav aria-label="我的内容">
      <button
        v-for="item in sections"
        :key="item.id"
        type="button"
        :class="{ active: section === item.id }"
        :aria-current="section === item.id ? 'page' : undefined"
        @click="selectSection(item.id)"
      >
        {{ item.label }}
      </button>
    </nav>

    <section v-if="section === 'profile'" data-test="my-profile">
      <p class="chapter">只读画像</p>
      <template v-if="desk.profileSummary">
        <h3>{{ displayText(desk.profileSummary.archetype_title, '画像摘要') }}</h3>
        <dl>
          <div><dt>风险偏好</dt><dd>{{ displayText(desk.profileSummary.risk_level) }}</dd></div>
          <div><dt>损失容忍</dt><dd>{{ formatPercent(desk.profileSummary.loss_tolerance_percent) }}</dd></div>
          <div><dt>完整度</dt><dd>{{ formatCompleteness(desk.profileSummary.completeness) }}</dd></div>
          <div><dt>投资期限</dt><dd>{{ displayText(desk.profileSummary.objective_profile?.fund_horizon) }}</dd></div>
          <div><dt>投资经验</dt><dd>{{ displayText(desk.profileSummary.objective_profile?.investment_experience) }}</dd></div>
          <div><dt>版本</dt><dd>{{ desk.profileSummary.version == null ? '—' : `v${desk.profileSummary.version}` }}</dd></div>
        </dl>
        <p v-if="!desk.profile?.profile?.objective_profile" class="data-footnote">
          期限与经验仅在完整画像可用时显示具体值；交易台投影不会下发原始问卷明细。
        </p>
        <RouterLink to="/app/profile-report">查看完整画像报告</RouterLink>
      </template>
      <div v-else-if="desk.profileError === 'PROFILE_NOT_FOUND' || desk.profileProjection?.available === false" class="my-empty-state">
        <h3>尚未完成投资画像</h3>
        <p class="my-empty-copy">交易台不会伪造画像。完成引导访谈后，此处会显示风险偏好、期限与完整度等只读摘要。</p>
        <RouterLink class="ink-button" to="/app/exe">前往完成画像</RouterLink>
      </div>
      <p v-else class="data-error" role="alert">{{ desk.profileError || '无法读取画像。' }}</p>
    </section>

    <section v-else-if="section === 'wallet'" data-test="my-wallet">
      <header class="my-section-heading">
        <div><p class="chapter">模拟数据</p><h3>钱包</h3></div>
        <button class="refresh-button" type="button" :disabled="desk.loadingSimulation" @click="desk.loadSimulationData">
          {{ desk.loadingSimulation ? '读取中' : '刷新' }}
        </button>
      </header>
      <p v-if="desk.accountError" class="data-error" role="alert">{{ desk.accountError }}</p>
      <template v-else-if="desk.account">
        <dl class="wallet-ledger">
          <div><dt>现金总额</dt><dd>{{ formatMoney(desk.account.cash_total_rmb) }}</dd></div>
          <div><dt>可用现金</dt><dd>{{ formatMoney(desk.account.cash_available_rmb) }}</dd></div>
          <div><dt>冻结现金</dt><dd>{{ formatMoney(desk.account.cash_frozen_rmb) }}</dd></div>
          <div><dt>保证金</dt><dd>{{ formatMoney(desk.account.margin_rmb) }}</dd></div>
        </dl>
        <p class="data-footnote">
          模拟账户 · {{ desk.account.status }} · 修订 {{ desk.account.revision }}
          <span v-if="desk.simulationLoadedAt">· 读取于 {{ formatTime(desk.simulationLoadedAt) }}</span>
        </p>
      </template>
      <div v-else-if="!desk.loadingSimulation" class="my-empty-state">
        <p>尚未建立模拟账户。钱包不会显示示例资金。</p>
        <button class="ink-button" type="button" @click="openWorkspace('portfolio'); $emit('close')">前往持仓建立账户</button>
      </div>
    </section>

    <section v-else-if="section === 'history'" data-test="my-history">
      <header class="my-section-heading">
        <div><p class="chapter">模拟数据</p><h3>交易记录</h3></div>
        <button class="refresh-button" type="button" :disabled="desk.loadingSimulation" @click="desk.loadSimulationData">
          {{ desk.loadingSimulation ? '读取中' : '刷新' }}
        </button>
      </header>

      <div class="history-block">
        <h4>订单</h4>
        <p v-if="desk.ordersError" class="data-error" role="alert">{{ desk.ordersError }}</p>
        <div v-else-if="desk.orders.length" class="market-table-wrap">
          <table class="market-table history-table">
            <caption class="sr-only">模拟订单记录</caption>
            <thead><tr><th>更新时间</th><th>标的</th><th>方向</th><th>状态</th><th class="numeric">委托</th><th class="numeric">成交</th><th class="numeric">均价</th><th class="numeric">费用</th></tr></thead>
            <tbody>
              <tr v-for="order in desk.orders" :key="order.order_id">
                <td><time :datetime="order.updated_at">{{ formatTime(order.updated_at) }}</time><small>{{ order.order_id }}</small></td>
                <td><strong>{{ order.instrument_id }}</strong><small>{{ order.order_type }}</small></td>
                <td>{{ sideLabels[order.side] ?? order.side }}</td>
                <td>{{ statusLabels[order.status] ?? order.status }}</td>
                <td class="numeric">{{ formatNumber(order.quantity) }}</td>
                <td class="numeric">{{ formatNumber(order.cumulative_filled) }}</td>
                <td class="numeric">{{ formatMoney(order.average_fill_price) }}</td>
                <td class="numeric">{{ formatMoney(order.total_fee_rmb) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else-if="!desk.loadingSimulation" class="my-empty-copy">暂无服务端模拟订单记录。</p>
      </div>

      <div class="history-block">
        <h4>成交</h4>
        <p v-if="desk.fillsError" class="data-error" role="alert">{{ desk.fillsError }}</p>
        <div v-else-if="desk.fills.length" class="market-table-wrap">
          <table class="market-table history-table">
            <caption class="sr-only">模拟成交记录</caption>
            <thead><tr><th>成交时间</th><th>标的</th><th>方向</th><th class="numeric">数量</th><th class="numeric">价格</th><th class="numeric">费用</th></tr></thead>
            <tbody>
              <tr v-for="fill in desk.fills" :key="fill.fill_id">
                <td><time :datetime="fill.occurred_at">{{ formatTime(fill.occurred_at) }}</time><small>{{ fill.order_id }}</small></td>
                <td><strong>{{ fill.instrument_id }}</strong><small>{{ fill.fill_id }}</small></td>
                <td>{{ sideLabels[fill.side ?? ''] ?? fill.side ?? '—' }}</td>
                <td class="numeric">{{ formatNumber(fill.quantity) }}</td>
                <td class="numeric">{{ formatMoney(fill.price) }}</td>
                <td class="numeric">{{ formatMoney(fill.fee) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else-if="!desk.loadingSimulation" class="my-empty-copy">暂无服务端模拟成交记录。</p>
      </div>

      <div class="history-block">
        <h4>决策日志与复盘</h4>
        <p class="my-empty-copy">按完整持仓周期查看当时决策、成交偏离、终局复盘和画像版本反馈。</p>
        <button class="ink-button" type="button" @click="openWorkspace('review'); $emit('close')">打开交易复盘</button>
      </div>

      <p v-if="desk.simulationLoadedAt" class="data-footnote">订单与成交读取于 {{ formatTime(desk.simulationLoadedAt) }}。</p>
    </section>

    <section v-else class="settings-section" data-test="my-settings">
      <!-- 账户资料 -->
      <form class="settings-form" @submit.prevent="saveSettings">
        <p class="chapter">账户资料</p>
        <h3>个人信息</h3>
        <div class="settings-field-row">
          <label>显示名称<input v-model="displayName" name="display-name" maxlength="100" autocomplete="name" placeholder="输入显示名称"></label>
        </div>
        <div class="settings-field-row settings-field-pair">
          <label>基础货币<select v-model="baseCurrency" name="base-currency"><option>CNY</option><option>USD</option></select></label>
          <label>地区<select v-model="region" name="region"><option>CN</option><option>US</option></select></label>
        </div>
        <p class="data-footnote">设置不会进入 Agent 上下文、快捷指令或工具调用。</p>
        <p v-if="settingMessage" :class="{ 'data-error': !settingMessage.includes('已保存') }" role="status">{{ settingMessage }}</p>
        <button class="ink-button" type="submit" :disabled="savingSettings">{{ savingSettings ? '正在保存' : '保存设置' }}</button>
      </form>

      <!-- 账户信息 -->
      <div class="settings-info-block">
        <p class="chapter">账户信息</p>
        <dl class="settings-account-info">
          <div><dt>邮箱</dt><dd>{{ auth.user?.email ?? '—' }}</dd></div>
          <div><dt>账户状态</dt><dd>{{ auth.user?.status === 'active' ? '正常' : (auth.user?.status ?? '—') }}</dd></div>
          <div><dt>注册时间</dt><dd>{{ formatTime(auth.user?.created_at) }}</dd></div>
          <div><dt>上次登录</dt><dd>{{ formatTime(auth.user?.last_login_at) }}</dd></div>
        </dl>
      </div>

      <!-- 仿真钱包重置 -->
      <div class="settings-danger-zone">
        <p class="chapter">仿真账户</p>
        <h3>钱包重置</h3>
        <p class="data-footnote">重置后模拟账户将恢复为 ¥1,000,000 初始资金，所有持仓与历史订单将归档至旧账户。此操作不可撤销。</p>
        <p v-if="resetMessage" :class="{ 'data-error': !resetMessage.includes('已重置') }" role="status">{{ resetMessage }}</p>
        <template v-if="!showResetConfirm">
          <button class="ink-button danger-button" type="button" :disabled="!desk.account" @click="showResetConfirm = true">重置钱包</button>
        </template>
        <div v-else class="confirm-bar">
          <span class="confirm-warning">确认重置？所有模拟数据将归档。</span>
          <button class="ink-button danger-button" type="button" :disabled="resettingWallet" @click="handleResetWallet">{{ resettingWallet ? '正在重置…' : '确认重置' }}</button>
          <button class="ink-button" type="button" @click="showResetConfirm = false">取消</button>
        </div>
      </div>

      <!-- 退出登录 -->
      <div class="settings-danger-zone settings-logout-zone">
        <p class="chapter">会话</p>
        <h3>退出登录</h3>
        <p class="data-footnote">退出后需重新输入邮箱和密码登录。本地浏览器缓存将被清除。</p>
        <template v-if="!showLogoutConfirm">
          <button class="ink-button danger-button" type="button" @click="showLogoutConfirm = true">退出登录</button>
        </template>
        <div v-else class="confirm-bar">
          <span class="confirm-warning">确认退出当前账户？</span>
          <button class="ink-button danger-button" type="button" :disabled="loggingOut" @click="handleLogout">{{ loggingOut ? '正在退出…' : '确认退出' }}</button>
          <button class="ink-button" type="button" @click="showLogoutConfirm = false">取消</button>
        </div>
      </div>
    </section>
  </aside>
</template>
