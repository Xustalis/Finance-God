<script setup lang="ts">
/**
 * PortfolioView — 组合页
 * 左栏账户概览 + 主栏持仓明细 + 右栏资产统计
 * 所有数据来自仿真交易后端 API，无 mock
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import {
  fetchCurrentAccount,
  fetchOrders,
  fetchFills,
} from '@/api/desk'
import { formatNumber } from '@/types/desk'
import type { SimulationAccount } from '@/types/desk'

const market = useMarketStore()

/* 仿真账户 */
const account = ref<SimulationAccount | null>(null)
const accountError = ref<string | null>(null)
const loading = ref(true)

/* 订单与成交 */
const orders = ref<any[]>([])
const fills = ref<any[]>([])

/* 从成交记录推导持仓 */
const positions = computed(() => {
  const map = new Map<string, { symbol: string; quantity: number; avgCost: number; totalCost: number }>()
  for (const fill of fills.value) {
    const id = fill.instrument_id || fill.order_id || 'unknown'
    const side = fill.side || 'buy'
    const qty = Number(fill.quantity ?? fill.fill_quantity ?? 0)
    const price = Number(fill.price ?? fill.fill_price ?? 0)
    if (!map.has(id)) {
      map.set(id, { symbol: id, quantity: 0, avgCost: 0, totalCost: 0 })
    }
    const pos = map.get(id)!
    if (side === 'buy') {
      pos.totalCost += qty * price
      pos.quantity += qty
    } else {
      pos.totalCost -= pos.quantity > 0 ? (pos.totalCost / pos.quantity) * qty : 0
      pos.quantity -= qty
    }
    pos.avgCost = pos.quantity > 0 ? pos.totalCost / pos.quantity : 0
  }
  return [...map.values()].filter(p => p.quantity > 0)
})

const totalMarketValue = computed(() => {
  return positions.value.reduce((sum, p) => {
    const quote = market.quotesMap.get(p.symbol)
    const price = quote?.last ?? p.avgCost
    return sum + p.quantity * price
  }, 0)
})

const totalPnL = computed(() => {
  return positions.value.reduce((sum, p) => {
    const quote = market.quotesMap.get(p.symbol)
    const price = quote?.last ?? p.avgCost
    return sum + (price - p.avgCost) * p.quantity
  }, 0)
})

async function loadData() {
  loading.value = true
  accountError.value = null
  try {
    const [acc, ord, fil] = await Promise.allSettled([
      fetchCurrentAccount(),
      fetchOrders(),
      fetchFills(),
    ])
    if (acc.status === 'fulfilled') account.value = acc.value as SimulationAccount
    else accountError.value = acc.reason?.message || '账户加载失败'
    if (ord.status === 'fulfilled') orders.value = Array.isArray(ord.value) ? ord.value : []
    if (fil.status === 'fulfilled') fills.value = Array.isArray(fil.value) ? fil.value : []
  } catch (e) {
    accountError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
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
          <span>账户概览</span>
          <small>ACCOUNT</small>
        </h2>
        <div v-if="account" class="summary-grid">
          <div class="summary-row">
            <span>总资产</span>
            <strong>{{ formatNumber(account.cash_total_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>可用资金</span>
            <strong>{{ formatNumber(account.cash_available_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>冻结资金</span>
            <strong>{{ formatNumber(account.cash_frozen_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>保证金</span>
            <strong>{{ formatNumber(account.margin_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>账户状态</span>
            <strong>{{ account.status }}</strong>
          </div>
          <div class="summary-row">
            <span>版本</span>
            <strong>{{ account.revision }}</strong>
          </div>
        </div>
        <div v-else class="summary-empty">
          <strong v-if="accountError" class="down">账户不可用</strong>
          <span>{{ accountError || '加载中...' }}</span>
        </div>
        <div class="rail-action">
          <button class="secondary-button" :disabled="loading" @click="loadData">
            刷新数据
          </button>
        </div>
      </section>
    </template>

    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>组合</span>
          <span>PORTFOLIO</span>
        </div>
        <h1 class="lead-title">
          持仓明细
          <small v-if="positions.length > 0" :class="totalPnL >= 0 ? 'up' : 'down'">
            市值 {{ formatNumber(totalMarketValue) }}
            盈亏 {{ totalPnL >= 0 ? '+' : '' }}{{ formatNumber(totalPnL) }}
          </small>
        </h1>
      </div>

      <div v-if="loading" class="table-state">加载持仓数据...</div>
      <div v-else-if="positions.length === 0" class="table-state">
        <span>暂无持仓，通过交易台下单后这里会显示持仓明细。</span>
        <router-link to="/desk" class="secondary-button" style="margin-top: 12px; display: inline-flex;">
          前往交易台
        </router-link>
      </div>
      <div v-else class="positions-table">
        <div class="ptable-header">
          <span class="col-sym">标的</span>
          <span class="col-num">数量</span>
          <span class="col-num">均价</span>
          <span class="col-num">现价</span>
          <span class="col-num">盈亏</span>
        </div>
        <div v-for="pos in positions" :key="pos.symbol" class="ptable-row">
          <strong class="col-sym">{{ pos.symbol }}</strong>
          <span class="col-num">{{ pos.quantity.toFixed(0) }}</span>
          <span class="col-num">{{ formatNumber(pos.avgCost) }}</span>
          <span class="col-num">{{ formatNumber(market.quotesMap.get(pos.symbol)?.last ?? pos.avgCost) }}</span>
          <span class="col-num" :class="((market.quotesMap.get(pos.symbol)?.last ?? pos.avgCost) - pos.avgCost) >= 0 ? 'up' : 'down'">
            {{ formatNumber(((market.quotesMap.get(pos.symbol)?.last ?? pos.avgCost) - pos.avgCost) * pos.quantity) }}
          </span>
        </div>
      </div>

      <!-- 近期成交 -->
      <div v-if="fills.length > 0" class="fills-section">
        <h2 class="section-heading">近期成交 <small>FILLS</small></h2>
        <div class="fills-table">
          <div class="ftable-header">
            <span class="col-sym">标的</span>
            <span class="col-num">方向</span>
            <span class="col-num">数量</span>
            <span class="col-num">价格</span>
          </div>
          <div v-for="fill in fills.slice(0, 10)" :key="fill.fill_id || fill.order_id" class="ftable-row">
            <strong class="col-sym">{{ fill.instrument_id || '—' }}</strong>
            <span class="col-num" :class="fill.side === 'buy' ? 'up' : 'down'">{{ fill.side || '—' }}</span>
            <span class="col-num">{{ fill.quantity ?? fill.fill_quantity ?? '—' }}</span>
            <span class="col-num">{{ formatNumber(fill.price ?? fill.fill_price) }}</span>
          </div>
        </div>
      </div>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>资产统计</span>
          <small>SUMMARY</small>
        </h2>
        <div class="summary-grid">
          <div class="summary-row">
            <span>持仓市值</span>
            <strong>{{ formatNumber(totalMarketValue) }}</strong>
          </div>
          <div class="summary-row">
            <span>浮动盈亏</span>
            <strong :class="totalPnL >= 0 ? 'up' : 'down'">
              {{ totalPnL >= 0 ? '+' : '' }}{{ formatNumber(totalPnL) }}
            </strong>
          </div>
          <div class="summary-row">
            <span>持仓数</span>
            <strong>{{ positions.length }}</strong>
          </div>
          <div class="summary-row">
            <span>成交笔数</span>
            <strong>{{ fills.length }}</strong>
          </div>
          <div class="summary-row">
            <span>订单数</span>
            <strong>{{ orders.length }}</strong>
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
  display: block; font-size: 0.5em; font-family: var(--font-numeric);
  font-weight: 700; margin-top: 4px;
}

.summary-grid { padding: 14px 18px; }
.summary-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; }

.summary-empty {
  padding: 28px 18px; color: var(--muted-ink); font-size: 13px; text-align: center;
}
.summary-empty strong { display: block; margin-bottom: 4px; }

.table-state {
  padding: 40px 20px; color: var(--muted-ink); font-size: 14px; text-align: center;
}

.positions-table, .fills-table { border-top: 1px solid var(--rule); }
.ptable-header, .ftable-header {
  display: grid; grid-template-columns: minmax(0,1fr) 80px 90px 90px 90px; gap: 4px;
  padding: 8px 20px 6px; font-size: 11px; font-weight: 900;
  color: var(--muted-ink); letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}
.ftable-header { grid-template-columns: minmax(0,1fr) 60px 70px 90px; }
.ptable-header .col-num, .ftable-header .col-num { text-align: right; }

.ptable-row, .ftable-row {
  display: grid; grid-template-columns: minmax(0,1fr) 80px 90px 90px 90px; gap: 4px;
  padding: 10px 20px; border-bottom: 1px solid var(--faint-rule); font-size: 14px;
}
.ftable-row { grid-template-columns: minmax(0,1fr) 60px 70px 90px; }
.ptable-row .col-num, .ftable-row .col-num {
  text-align: right; font-family: var(--font-numeric); font-size: 13px;
}
.ptable-row .col-sym, .ftable-row .col-sym {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.fills-section { margin-top: 24px; }
.section-heading {
  display: flex; align-items: baseline; gap: 10px;
  padding: 14px 20px 6px; font-size: 14px; font-weight: 900;
  letter-spacing: 0.03em; margin: 0; border-bottom: 1px solid var(--rule);
}
.section-heading small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em;
}
</style>
