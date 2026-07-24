<script setup lang="ts">
export interface OverviewQuote {
  symbol: string
  name: string
  last: number | null
  change: number | null
  change_percent: number | null
  provider_time: string
  frequency: string
  freshness: string
}

export interface MarketFact {
  source: { data_time: string; evidence_ref: string }
  fields: Array<{ name: string; value: string | number | boolean | null }>
}

interface FactBatch {
  symbol: string
  requested_at: string
  facts: MarketFact[]
}

defineProps<{
  quotes: readonly OverviewQuote[]
  selectedSymbol: string
  loading: boolean
  marketError: string | null
  sentimentFacts: FactBatch | null
  sentimentError: string | null
  informationFacts: FactBatch | null
  informationError: string | null
  onSelectSymbol: (symbol: string) => void
  onRefresh: () => void | Promise<void>
}>()

function number(value: number | null): string {
  return value === null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

function signedNumber(value: number): string {
  return `${value >= 0 ? '+' : ''}${number(value)}`
}

function field(value: string | number | boolean | null): string {
  return value === null ? '—' : String(value)
}
</script>

<template>
  <section class="information-workspace" aria-labelledby="overview-title">
    <header class="overview-heading">
      <h1 id="overview-title">总览</h1>
      <button class="refresh-button" type="button" :disabled="loading" @click="onRefresh">
        {{ loading ? '正在刷新' : '刷新' }}
      </button>
    </header>

    <section class="overview-section market-overview" aria-labelledby="market-title">
      <header>
        <h2 id="market-title">大盘指数</h2>
        <small>PandaData · 上游时间与实际频率</small>
      </header>
      <div class="market-table-wrap">
        <table v-if="quotes.length" class="market-table">
          <thead><tr><th scope="col">标的</th><th scope="col" class="numeric">最新价</th><th scope="col" class="numeric">涨跌</th><th scope="col" class="numeric">涨跌幅</th><th scope="col">数据状态</th></tr></thead>
          <tbody>
            <tr v-for="quote in quotes" :key="quote.symbol" :class="{ selected: selectedSymbol === quote.symbol }" @click="onSelectSymbol(quote.symbol)">
              <th scope="row">{{ quote.name }} <small>{{ quote.symbol }}</small></th>
              <td class="numeric">{{ number(quote.last) }}</td>
              <td class="numeric" :class="(quote.change ?? 0) >= 0 ? 'up' : 'down'">{{ quote.change === null ? '—' : signedNumber(quote.change) }}</td>
              <td class="numeric" :class="(quote.change_percent ?? 0) >= 0 ? 'up' : 'down'">{{ quote.change_percent === null ? '—' : `${quote.change_percent >= 0 ? '+' : ''}${quote.change_percent.toFixed(2)}%` }}</td>
              <td><small>{{ quote.provider_time }}</small><small>{{ quote.frequency }} · {{ quote.freshness }}</small></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="marketError" class="data-error" role="alert">真实行情不可用：{{ marketError }}</p>
      <p v-else-if="!quotes.length" class="empty-data">正在读取真实行情；不会显示替代价格。</p>
    </section>

    <section class="overview-section facts-section" aria-labelledby="sentiment-title">
      <header><h2 id="sentiment-title">市场情绪</h2><small>融资余额原始事实，不生成情绪分数</small></header>
      <template v-if="sentimentFacts">
        <p class="fact-meta">{{ sentimentFacts.symbol }} · {{ sentimentFacts.requested_at }}</p>
        <ul class="fact-list compact"><li v-for="fact in sentimentFacts.facts.slice(0, 3)" :key="fact.source.evidence_ref"><strong>{{ fact.source.data_time }}</strong><span v-for="item in fact.fields.slice(0, 2)" :key="item.name">{{ item.name }}：{{ field(item.value) }}</span></li></ul>
      </template>
      <p v-else class="empty-data">{{ sentimentError || '正在读取服务端情绪事实。' }}</p>
    </section>

    <section class="overview-section facts-section" aria-labelledby="information-title">
      <header><h2 id="information-title">市场资讯</h2><small>公司披露原始事实</small></header>
      <template v-if="informationFacts">
        <p class="fact-meta">{{ informationFacts.symbol }} · {{ informationFacts.requested_at }}</p>
        <ul class="fact-list compact"><li v-for="fact in informationFacts.facts.slice(0, 3)" :key="fact.source.evidence_ref"><strong>{{ fact.source.data_time }}</strong><span v-for="item in fact.fields.slice(0, 2)" :key="item.name">{{ item.name }}：{{ field(item.value) }}</span></li></ul>
      </template>
      <p v-else class="empty-data">{{ informationError || '正在读取服务端披露事实。' }}</p>
    </section>
  </section>
</template>
