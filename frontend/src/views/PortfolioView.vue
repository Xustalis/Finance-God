<script setup lang="ts">
/**
 * PortfolioView — 资产页（ASSETS）
 * 单一资产承载页：钱包（仿真账户，可初始化/重置）+ 持仓明细 + 资金流水 + 资产统计。
 * 数量与成本来自后端仿真 projection；市值与浮动盈亏由前端用实时 PandaData 行情计算；
 * 缺行情的标的只标注「暂不可估值」，绝不用成交价伪造现价或盈亏。
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import {
  fetchCurrentAccount,
  fetchPortfolio,
  fetchOrders,
  fetchFills,
  createSimulationAccount,
  resetSimulationAccount,
  isDeskApiError,
  newIdempotencyKey,
} from '@/api/desk'
import { DEFAULT_SYMBOLS, DEFAULT_SIMULATION_CASH_RMB } from '@/types/desk'
import type {
  SimulationAccount,
  PortfolioView,
  SimulationFill,
  StoredOrderView,
} from '@/types/desk'

const market = useMarketStore()

/* ── 仿真账户（钱包） ─────────────────────────────── */
const account = ref<SimulationAccount | null>(null)
const accountError = ref<string | null>(null)
const accountMissing = ref(false)

/* ── 持仓 / 订单 / 成交 ───────────────────────────── */
const portfolio = ref<PortfolioView | null>(null)
const positionsError = ref<string | null>(null)
const orders = ref<StoredOrderView[]>([])
const ordersError = ref<string | null>(null)
const fills = ref<SimulationFill[]>([])
const fillsError = ref<string | null>(null)
const loading = ref(true)

/* ── 账户初始化 ───────────────────────────────────── */
const initialCashRmb = ref(100_000)
const accountCreating = ref(false)
let accountCreationKey: string | null = null

/* ── 钱包重置 ─────────────────────────────────────── */
const accountResetting = ref(false)
const resetConfirming = ref(false)
const resetError = ref<string | null>(null)

function formatRmb(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatQty(value: number): string {
  return Number.isInteger(value)
    ? value.toString()
    : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}

function failureMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}

const SIDE_LABELS: Record<string, string> = { buy: '买入', sell: '卖出', short: '卖空' }
function sideLabel(side: string | null): string {
  return side ? (SIDE_LABELS[side] ?? side) : '—'
}

const fillRows = computed(() =>
  [...fills.value].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)),
)
const totalFees = computed(() => fills.value.reduce((sum, f) => sum + f.fee, 0))

/** 权威持仓事实（数量/成本/已实现盈亏），无账户时为空。 */
const positions = computed(() => portfolio.value?.positions ?? [])
/** 账户层累计已实现盈亏（后端回放成交结算）。 */
const realizedPnlTotal = computed(() => portfolio.value?.realized_pnl_rmb ?? 0)

interface PositionRow {
  instrument_id: string
  quantity: number
  available: number
  costTotal: number
  costUnit: number | null
  realized: number
  hasQuote: boolean
  price: number | null
  marketValue: number | null
  pnl: number | null
}

const positionRows = computed<PositionRow[]>(() =>
  positions.value.map((p) => {
    const quote = market.quotesMap.get(p.instrument_id)
    const price = quote ? quote.last : null
    const hasQuote = price !== null && price !== undefined && Number.isFinite(price)
    const marketValue = hasQuote ? p.quantity * (price as number) : null
    const pnl = marketValue !== null ? marketValue - p.cost_basis_rmb : null
    return {
      instrument_id: p.instrument_id,
      quantity: p.quantity,
      available: p.available_quantity,
      costTotal: p.cost_basis_rmb,
      costUnit: p.average_cost_rmb,
      realized: p.realized_pnl_rmb,
      hasQuote,
      price: hasQuote ? (price as number) : null,
      marketValue,
      pnl,
    }
  }),
)

const positionSymbols = computed(() => [
  ...new Set(positions.value.map((p) => p.instrument_id)),
])

const missingQuoteSymbols = computed(() =>
  positionSymbols.value.filter((symbol) => market.quotesMap.get(symbol) === undefined),
)

const totalMarketValue = computed(() =>
  positionRows.value.reduce((sum, r) => (r.marketValue !== null ? sum + r.marketValue : sum), 0),
)
const totalPnl = computed(() =>
  positionRows.value.reduce((sum, r) => (r.pnl !== null ? sum + r.pnl : sum), 0),
)
const valuationIncomplete = computed(() =>
  positionRows.value.some((r) => !r.hasQuote),
)

/* 持仓标的加入共享轮询池，复用行情控制器，不独立轮询。 */
watch(
  positionSymbols,
  (symbols) => {
    market.setWatchSymbols([...DEFAULT_SYMBOLS, ...symbols])
  },
  { flush: 'post' },
)

async function loadAccount() {
  accountError.value = null
  accountMissing.value = false
  try {
    account.value = await fetchCurrentAccount()
  } catch (error) {
    account.value = null
    if (isDeskApiError(error, 404)) {
      accountMissing.value = true
    } else {
      accountError.value = error instanceof Error ? error.message : String(error)
    }
  }
}

async function refreshHoldings() {
  positionsError.value = null
  ordersError.value = null
  fillsError.value = null
  const [pos, ord, fil] = await Promise.allSettled([
    fetchPortfolio(),
    fetchOrders(),
    fetchFills(),
  ])
  if (pos.status === 'fulfilled') {
    portfolio.value = pos.value
  } else {
    portfolio.value = null
    positionsError.value = failureMessage(pos.reason, '持仓数据加载失败')
  }
  if (ord.status === 'fulfilled') {
    orders.value = Array.isArray(ord.value) ? ord.value : []
  } else {
    ordersError.value = failureMessage(ord.reason, '订单数据加载失败')
  }
  if (fil.status === 'fulfilled') {
    fills.value = Array.isArray(fil.value) ? fil.value : []
  } else {
    fillsError.value = failureMessage(fil.reason, '成交数据加载失败')
  }
}

async function loadData() {
  loading.value = true
  await Promise.all([loadAccount(), refreshHoldings()])
  loading.value = false
}

async function initializeSimulationAccount() {
  if (!Number.isFinite(initialCashRmb.value) || initialCashRmb.value <= 0 || accountCreating.value) {
    return
  }
  accountCreating.value = true
  accountError.value = null
  try {
    accountCreationKey ??= newIdempotencyKey('account')
    account.value = await createSimulationAccount(initialCashRmb.value, accountCreationKey)
    accountMissing.value = false
    await refreshHoldings()
  } catch (error) {
    accountError.value = error instanceof Error ? error.message : String(error)
  } finally {
    accountCreating.value = false
  }
}

async function confirmResetWallet() {
  const current = account.value
  if (!current || accountResetting.value) return
  accountResetting.value = true
  resetError.value = null
  try {
    account.value = await resetSimulationAccount(
      current.account_id,
      DEFAULT_SIMULATION_CASH_RMB,
      newIdempotencyKey('account-reset'),
    )
    resetConfirming.value = false
    await refreshHoldings()
  } catch (error) {
    resetError.value = error instanceof Error ? error.message : String(error)
  } finally {
    accountResetting.value = false
  }
}

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  loadData()
})
onUnmounted(() => market.stopPolling())
</script>

<template>
  <DeskLayout>
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>钱包</span>
          <small>WALLET</small>
        </h2>

        <div v-if="account" class="summary-grid">
          <div class="summary-row">
            <span>余额</span>
            <strong>¥{{ formatRmb(account.cash_total_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>可用资金</span>
            <strong>¥{{ formatRmb(account.cash_available_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>保证金</span>
            <strong>¥{{ formatRmb(account.margin_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>冻结资金</span>
            <strong>¥{{ formatRmb(account.cash_frozen_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>累计费用</span>
            <strong>{{ fillsError ? '暂不可用' : `¥${formatRmb(totalFees)}` }}</strong>
          </div>
          <div class="summary-row">
            <span>账户状态</span>
            <strong>{{ account.status }}</strong>
          </div>
          <div class="summary-row">
            <span>账户编号</span>
            <strong class="mono-id">{{ account.account_id }}</strong>
          </div>
        </div>

        <form
          v-else-if="accountMissing"
          data-test="account-initialization-form"
          class="account-initialization"
          @submit.prevent="initializeSimulationAccount"
        >
          <strong>尚未初始化仿真账户</strong>
          <p>设置初始人民币现金后创建账户。创建成功前，交易台保持不可提交。</p>
          <label>
            <span>初始现金（人民币）</span>
            <input
              v-model.number="initialCashRmb"
              data-test="initial-cash"
              type="number"
              min="1"
              step="1000"
              inputmode="decimal"
            />
          </label>
          <button
            data-test="initialize-account"
            class="primary-button compact"
            :disabled="accountCreating || initialCashRmb <= 0"
          >
            {{ accountCreating ? '正在初始化…' : '初始化仿真账户' }}
          </button>
          <p v-if="accountError" class="form-error" role="alert">{{ accountError }}</p>
        </form>

        <div v-else class="summary-empty" role="alert">
          <strong v-if="accountError" class="down">账户不可用</strong>
          <span>{{ accountError || '加载中...' }}</span>
          <button v-if="accountError" class="secondary-button compact" @click="loadAccount">
            重新加载账户
          </button>
        </div>

        <div v-if="account" class="reset-block">
          <template v-if="!resetConfirming">
            <button
              data-test="reset-wallet"
              type="button"
              class="secondary-button compact"
              :disabled="accountResetting"
              @click="resetError = null; resetConfirming = true"
            >
              重置钱包
            </button>
            <p class="reset-hint">重置将关闭当前账户，并以固定 ¥{{ formatRmb(DEFAULT_SIMULATION_CASH_RMB) }} 现金重建。</p>
          </template>
          <div v-else class="reset-confirm" role="group" aria-label="确认重置钱包">
            <strong>确认重置钱包为 ¥{{ formatRmb(DEFAULT_SIMULATION_CASH_RMB) }}？</strong>
            <span>当前账户将被关闭，持仓与在途订单不再归属新账户。此操作不可撤销。</span>
            <div class="reset-actions">
              <button
                data-test="confirm-reset-wallet"
                type="button"
                class="primary-button compact"
                :disabled="accountResetting"
                @click="confirmResetWallet"
              >
                {{ accountResetting ? '正在重置…' : `确认重置为 ¥${formatRmb(DEFAULT_SIMULATION_CASH_RMB)}` }}
              </button>
              <button type="button" class="text-button" :disabled="accountResetting" @click="resetConfirming = false">
                取消
              </button>
            </div>
          </div>
          <p v-if="resetError" class="form-error" role="alert">{{ resetError }}</p>
        </div>

        <div class="rail-action">
          <button class="secondary-button compact" :disabled="loading" @click="loadData">
            刷新数据
          </button>
        </div>
      </section>
    </template>

    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>资产</span>
          <span>ASSETS</span>
        </div>
        <h1 class="lead-title">
          持仓与资金
          <small>数量与成本来自仿真账户 · 市值按 PandaData 实时行情估算</small>
        </h1>
      </div>

      <div
        v-if="accountError || positionsError || ordersError || fillsError || missingQuoteSymbols.length > 0"
        class="data-warning"
        role="alert"
      >
        <p v-if="accountError"><strong>账户数据加载失败：</strong>{{ accountError }}</p>
        <p v-if="positionsError"><strong>持仓数据加载失败：</strong>{{ positionsError }}。持仓与估值暂不可用。</p>
        <p v-if="ordersError"><strong>订单数据加载失败：</strong>{{ ordersError }}。订单统计暂不可用。</p>
        <p v-if="fillsError"><strong>成交数据加载失败：</strong>{{ fillsError }}。资金流水与费用暂不可用。</p>
        <p v-if="missingQuoteSymbols.length > 0">
          <strong>缺少 PandaData 行情：</strong>{{ missingQuoteSymbols.join('、') }} 暂不可估值；不会使用成交价代替现价。
        </p>
      </div>

      <!-- 持仓明细 -->
      <section class="holdings-section">
        <h2 class="section-heading">持仓明细 <small>POSITIONS</small></h2>
        <div v-if="loading" class="table-state" role="status">加载持仓数据...</div>
        <div v-else-if="positionsError" class="table-state">
          <strong class="down">持仓结果不可用</strong>
          <span>后端持仓 projection 加载失败，无法判断当前是否存在持仓。</span>
        </div>
        <div v-else-if="positionRows.length === 0" class="table-state">暂无持仓。</div>
        <table v-else class="holdings-table">
          <thead>
            <tr>
              <th scope="col">标的</th>
              <th scope="col" class="num">数量</th>
              <th scope="col" class="num">可用</th>
              <th scope="col" class="num">成本单价</th>
              <th scope="col" class="num">成本额</th>
              <th scope="col" class="num">现价</th>
              <th scope="col" class="num">市值</th>
              <th scope="col" class="num">浮动盈亏</th>
              <th scope="col" class="num">已实现盈亏</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in positionRows" :key="row.instrument_id">
              <td class="mono">{{ row.instrument_id }}</td>
              <td class="num">{{ formatQty(row.quantity) }}</td>
              <td class="num">{{ formatQty(row.available) }}</td>
              <td class="num">{{ row.costUnit === null ? '—' : `¥${formatRmb(row.costUnit)}` }}</td>
              <td class="num">¥{{ formatRmb(row.costTotal) }}</td>
              <template v-if="row.hasQuote">
                <td class="num">¥{{ formatRmb(row.price as number) }}</td>
                <td class="num">¥{{ formatRmb(row.marketValue as number) }}</td>
                <td class="num" :class="{ up: (row.pnl as number) > 0, down: (row.pnl as number) < 0 }">
                  {{ (row.pnl as number) > 0 ? '+' : '' }}¥{{ formatRmb(row.pnl as number) }}
                </td>
              </template>
              <template v-else>
                <td class="num muted" colspan="3">暂不可估值</td>
              </template>
              <td class="num" :class="{ up: row.realized > 0, down: row.realized < 0 }">
                {{ row.realized > 0 ? '+' : '' }}¥{{ formatRmb(row.realized) }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 资金流水 -->
      <section class="flow-section">
        <h2 class="section-heading">资金流水 <small>FUND FLOW</small></h2>
        <p class="scope-note">成交产生的现金变动与费用（仿真），按成交时间倒序。</p>
        <div v-if="loading" class="table-state" role="status">正在加载资金流水…</div>
        <div v-else-if="fillsError" class="table-state">
          <strong class="down">资金流水不可用</strong>
          <span>{{ fillsError }}</span>
        </div>
        <div v-else-if="fillRows.length === 0" class="table-state">暂无成交流水。</div>
        <table v-else class="flow-table">
          <thead>
            <tr>
              <th scope="col">时间</th>
              <th scope="col">标的</th>
              <th scope="col">方向</th>
              <th scope="col" class="num">数量</th>
              <th scope="col" class="num">成交价</th>
              <th scope="col" class="num">成交额</th>
              <th scope="col" class="num">费用</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fill in fillRows" :key="fill.fill_id">
              <td>{{ new Date(fill.occurred_at).toLocaleString('zh-CN') }}</td>
              <td class="mono">{{ fill.instrument_id }}</td>
              <td :class="{ up: fill.side === 'buy', down: fill.side === 'sell' }">
                {{ sideLabel(fill.side) }}
              </td>
              <td class="num">{{ formatQty(fill.quantity) }}</td>
              <td class="num">¥{{ formatRmb(fill.price) }}</td>
              <td class="num">¥{{ formatRmb(fill.quantity * fill.price) }}</td>
              <td class="num">¥{{ formatRmb(fill.fee) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>资产统计</span>
          <small>SUMMARY</small>
        </h2>
        <div class="summary-grid">
          <div class="summary-row">
            <span>持仓市值合计</span>
            <strong>{{ positionsError ? '暂不可用' : `¥${formatRmb(totalMarketValue)}` }}</strong>
          </div>
          <div class="summary-row">
            <span>浮动盈亏合计</span>
            <strong
              v-if="!positionsError"
              :class="{ up: totalPnl > 0, down: totalPnl < 0 }"
            >{{ totalPnl > 0 ? '+' : '' }}¥{{ formatRmb(totalPnl) }}</strong>
            <strong v-else>暂不可用</strong>
          </div>
          <div v-if="!positionsError && valuationIncomplete" class="summary-note">
            部分持仓缺少行情，合计不完整。
          </div>
          <div class="summary-row">
            <span>已实现盈亏</span>
            <strong
              v-if="!positionsError"
              :class="{ up: realizedPnlTotal > 0, down: realizedPnlTotal < 0 }"
            >{{ realizedPnlTotal > 0 ? '+' : '' }}¥{{ formatRmb(realizedPnlTotal) }}</strong>
            <strong v-else>暂不可用</strong>
          </div>
          <div class="summary-row">
            <span>持仓数</span>
            <strong>{{ positionsError ? '暂不可用' : positionRows.length }}</strong>
          </div>
          <div class="summary-row">
            <span>成交笔数</span>
            <strong>{{ fillsError ? '暂不可用' : fills.length }}</strong>
          </div>
          <div class="summary-row">
            <span>订单数</span>
            <strong>{{ ordersError ? '暂不可用' : orders.length }}</strong>
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

.rail-action { padding: 14px 18px; }

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
.lead-title small {
  display: block; font-size: 0.42em; font-family: var(--font-numeric);
  font-weight: 700; margin-top: 4px; color: var(--muted-ink);
}

.summary-grid { padding: 14px 18px; }
.summary-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; }
.summary-row strong.mono-id { font-size: 11px; word-break: break-all; text-align: right; }
.summary-note {
  padding: 6px 0; font-size: 12px; color: var(--risk);
}

.summary-empty {
  display: grid; gap: 8px; justify-items: center;
  padding: 28px 18px; color: var(--muted-ink); font-size: 13px; text-align: center;
}
.summary-empty strong { display: block; }

.account-initialization {
  display: grid; gap: 10px; padding: 16px 18px;
}
.account-initialization p, .scope-note { margin: 0; color: var(--muted-ink); font-size: 12px; }
.account-initialization label { display: grid; gap: 5px; }
.account-initialization label span { color: var(--muted-ink); font-size: 12px; }
.account-initialization input { min-height: 36px; }

.reset-block {
  padding: 14px 18px; margin-top: 4px; border-top: 1px solid var(--faint-rule);
  display: grid; gap: 8px;
}
.reset-hint { margin: 0; color: var(--muted-ink); font-size: 12px; }
.reset-confirm { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--risk); }
.reset-confirm strong { font-size: 13px; }
.reset-confirm span { color: var(--muted-ink); font-size: 12px; }
.reset-actions { display: flex; align-items: center; gap: 12px; }

.table-state {
  padding: 32px 20px; color: var(--muted-ink); font-size: 14px; text-align: center;
}
.table-state strong { display: block; margin-bottom: 4px; }

.data-warning {
  margin: 0 20px 12px; padding: 9px 12px; border: 1px solid var(--risk);
  color: var(--risk); font-size: 12px;
}
.data-warning p { margin: 0; }
.data-warning p + p { margin-top: 4px; }

.holdings-section { margin-bottom: 24px; }
.flow-section { margin-top: 8px; }
.section-heading {
  display: flex; align-items: baseline; gap: 10px;
  padding: 14px 20px 6px; font-size: 14px; font-weight: 900;
  letter-spacing: 0.03em; margin: 0; border-bottom: 1px solid var(--rule);
}
.section-heading small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em;
}
.scope-note { padding: 8px 20px 0; }

.holdings-table, .flow-table {
  width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 4px;
}
.holdings-table th, .holdings-table td,
.flow-table th, .flow-table td {
  padding: 9px 20px; border-bottom: 1px solid var(--faint-rule); text-align: left;
}
.holdings-table thead th, .flow-table thead th {
  color: var(--muted-ink); font-size: 11px; font-weight: 700;
  letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}
.holdings-table .num, .flow-table .num {
  text-align: right; font-family: var(--font-numeric); font-weight: 700;
}
.holdings-table .mono, .flow-table .mono { font-family: var(--font-numeric); }
.holdings-table td.muted, .flow-table td.muted {
  color: var(--muted-ink); font-weight: 600; text-align: right;
}
.holdings-table tbody tr:hover, .flow-table tbody tr:hover { background: rgb(143 48 39 / 3%); }

.up { color: var(--positive); }
.down { color: var(--risk); }
</style>
