<script setup lang="ts">
import MarketChart, { type ChartQuote } from './MarketChart.vue'
import type { DeskBar } from '@/services/tradingDesk'
import { computed } from 'vue'

export interface OverviewQuote {
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
  session_alignment?: string
}

export interface MarketFact {
  source?: { data_time: string; evidence_ref: string }
  fields: Array<{ name: string; value: string | number | boolean | null }>
}

interface FactBatch {
  provider?: string
  fact_kind?: 'company_disclosure' | 'margin_balance' | 'market_sentiment' | 'industry_news'
  symbol: string
  requested_at: string
  generated_at?: string
  data_mode?: 'real' | 'mock'
  fallback_reason?: string | null
  facts: MarketFact[]
}

const props = defineProps<{
  quotes: readonly OverviewQuote[]
  bars?: readonly DeskBar[]
  selectedSymbol: string
  loading: boolean
  marketError: string | null
  barsError?: string | null
  marketLoadedAt: string | null
  sentimentFacts: FactBatch | null
  sentimentError: string | null
  sentimentNotice?: string | null
  informationFacts: FactBatch | null
  informationError: string | null
  informationNotice?: string | null
  onSelectSymbol: (symbol: string) => void
  onRefresh: () => void | Promise<void>
  onPeriodChange?: (period: string) => void
}>()

const selectedQuote = computed<ChartQuote | null>(() => {
  const q = props.quotes.find(q => q.symbol === props.selectedSymbol)
  return q ? { ...q } as ChartQuote : null
})
const currentSentimentFacts = computed(() => (
  props.sentimentFacts?.symbol === props.selectedSymbol ? props.sentimentFacts : null
))
const currentInformationFacts = computed(() => (
  props.informationFacts?.symbol === props.selectedSymbol ? props.informationFacts : null
))
const sentimentIsMock = computed(() => currentSentimentFacts.value?.data_mode === 'mock')
const informationIsMock = computed(() => currentInformationFacts.value?.data_mode === 'mock')

function field(value: string | number | boolean | null): string {
  return value === null ? '—' : String(value)
}

/** Map sentiment level to a representative emoji. */
const sentimentEmoji = computed(() => {
  if (!currentSentimentFacts.value?.facts?.length) return ''
  const levelField = currentSentimentFacts.value.facts[0]?.fields?.find(f => f.name === 'level')
  const level = String(levelField?.value ?? '').toLowerCase()
  const scoreField = currentSentimentFacts.value.facts[0]?.fields?.find(f => f.name === 'score')
  const score = Number(scoreField?.value ?? 50)
  if (level === 'bullish' || level === 'very_bullish' || score >= 70) return '😄'
  if (level === 'bearish' || level === 'very_bearish' || score <= 30) return '😢'
  if (level === 'neutral' && score >= 55) return '🙂'
  if (level === 'neutral' && score <= 45) return '😐'
  return '🙂'
})

const sentimentLabel = computed(() => {
  if (!currentSentimentFacts.value?.facts?.length) return ''
  const levelField = currentSentimentFacts.value.facts[0]?.fields?.find(f => f.name === 'level')
  const level = String(levelField?.value ?? '')
  const map: Record<string, string> = { very_bullish: '极度乐观', bullish: '乐观', neutral: '中性', bearish: '悲观', very_bearish: '极度悲观' }
  return map[level] || level
})

const sentimentScore = computed(() => {
  if (!currentSentimentFacts.value?.facts?.length) return null
  const scoreField = currentSentimentFacts.value.facts[0]?.fields?.find(f => f.name === 'score')
  return scoreField?.value ?? null
})
function time(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
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
      <header class="market-header-row">
        <h2 id="market-title">大盘指数</h2>
        <div v-if="currentSentimentFacts" class="sentiment-badge" :class="sentimentLabel">
          <span class="sentiment-emoji">{{ sentimentEmoji }}</span>
          <span class="sentiment-text">{{ sentimentLabel }}</span>
          <span v-if="sentimentScore !== null" class="sentiment-score">{{ sentimentScore }}</span>
        </div>
      </header>
      <!-- Index switcher: always visible -->
      <div class="index-switcher">
        <button
          v-for="q in (quotes.length ? quotes : [{symbol: '000001.SH', name: '上证指数'}, {symbol: '399001.SZ', name: '深证成指'}, {symbol: '000300.SH', name: '沪深300'}])" :key="q.symbol"
          class="index-tab"
          :class="{ active: selectedSymbol === q.symbol }"
          @click="onSelectSymbol(q.symbol)"
        >
          {{ q.name || q.symbol }}
        </button>
      </div>
      <!-- Chart -->
      <MarketChart
        :quote="selectedQuote"
        :bars="bars ?? []"
        :loading="loading"
        :error="barsError ?? null"
        :on-period-change="onPeriodChange"
      />
      <p v-if="marketError" class="data-error" role="alert">
        {{ quotes.length ? '部分行情未显示' : '真实行情刷新失败' }}：{{ marketError }}
        <small v-if="marketLoadedAt">当前保留数据最后成功读取于 {{ time(marketLoadedAt) }}。</small>
      </p>
      <p v-else-if="marketLoadedAt" class="data-footnote">客户端最后成功读取于 {{ time(marketLoadedAt) }}。</p>
    </section>

    <!-- Sentiment details below chart -->
    <div v-if="currentSentimentFacts" class="sentiment-detail-strip">
      <span v-for="item in currentSentimentFacts.facts[0]?.fields?.slice(0, 4)" :key="item.name" class="sentiment-detail-item">
        <span class="sentiment-detail-label">{{ item.name }}</span>
        <span class="sentiment-detail-value">{{ field(item.value) }}</span>
      </span>
    </div>
    <p v-if="sentimentIsMock && currentSentimentFacts" class="mock-data-disclosure" role="status">
      <strong>模拟数据</strong>
      {{ currentSentimentFacts.fallback_reason }}
      生成于 {{ time(currentSentimentFacts.generated_at || currentSentimentFacts.requested_at) }}；
      来源：{{ currentSentimentFacts.provider || 'Finance-God Mock' }}。刷新可重试真实数据。
    </p>
    <p v-if="sentimentError" class="data-error" role="alert">市场情绪事实刷新失败：{{ sentimentError }}</p>
    <p v-else-if="sentimentNotice" class="empty-data" role="status">{{ sentimentNotice }}</p>

    <section class="overview-section facts-section" aria-labelledby="information-title">
      <header>
        <h2 id="information-title">市场资讯 <span v-if="informationIsMock" class="mock-data-label">模拟数据</span></h2>
        <small>{{ informationIsMock ? 'Finance-God 模拟参考内容' : '爬虫实时财经要闻与研报（东方财富）' }}</small>
      </header>
      <template v-if="currentInformationFacts">
        <p v-if="informationIsMock" class="mock-data-disclosure" role="status">
          {{ currentInformationFacts.fallback_reason }}
          生成于 {{ time(currentInformationFacts.generated_at || currentInformationFacts.requested_at) }}；
          来源：{{ currentInformationFacts.provider || 'Finance-God Mock' }}。刷新可重试真实数据。
        </p>
        <ul class="news-list">
          <li v-for="(fact, idx) in currentInformationFacts.facts.slice(0, 8)" :key="idx" class="news-item">
            <a
              v-if="fact.fields.find(f => f.name === 'url')?.value"
              :href="String(fact.fields.find(f => f.name === 'url')?.value || '#')"
              target="_blank"
              rel="noopener noreferrer"
              class="news-link"
            >
              <span class="news-sector">{{ fact.fields.find(f => f.name === 'sector')?.value || '综合' }}</span>
              <span class="news-title">{{ fact.fields.find(f => f.name === 'title')?.value }}</span>
              <small class="news-source">{{ fact.fields.find(f => f.name === 'source')?.value }}</small>
            </a>
            <div v-else class="news-link">
              <span class="news-sector">{{ fact.fields.find(f => f.name === 'sector')?.value || '综合' }}</span>
              <span class="news-title">{{ fact.fields.find(f => f.name === 'title')?.value }}</span>
              <small class="news-source">{{ fact.fields.find(f => f.name === 'source')?.value }}</small>
            </div>
          </li>
        </ul>
      </template>
      <p v-else-if="informationError" class="data-error" role="alert">市场资讯刷新失败：{{ informationError }}</p>
      <p v-else-if="informationNotice" class="empty-data" role="status">{{ informationNotice }}</p>
      <p v-else class="empty-data">正在读取服务端市场资讯。</p>
    </section>
  </section>
</template>
