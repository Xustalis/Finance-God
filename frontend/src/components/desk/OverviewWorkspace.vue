<script setup lang="ts">
import MarketChart, { type ChartQuote } from './MarketChart.vue'
import type { DeskBar, DeskMarketNewsBatch } from '@/services/tradingDesk'
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



const props = withDefaults(defineProps<{
  quotes: readonly OverviewQuote[]
  bars?: readonly DeskBar[]
  selectedSymbol: string
  loading: boolean
  marketError: string | null
  barsError?: string | null
  minutePeriodsAvailable?: boolean
  marketLoadedAt: string | null

  marketNews?: DeskMarketNewsBatch | null
  marketNewsError?: string | null
  marketNewsNotice?: string | null
  onSelectSymbol: (symbol: string) => void
  onRefresh: () => void | Promise<void>
  onPeriodChange?: (period: string) => void
}>(), {
  minutePeriodsAvailable: true,
})

const selectedQuote = computed<ChartQuote | null>(() => {
  const q = props.quotes.find(q => q.symbol === props.selectedSymbol)
  return q ? { ...q } as ChartQuote : null
})


function safeNewsUrl(raw: string | null): string | null {
  if (!raw) return null
  try {
    const parsed = new URL(raw)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : null
  } catch {
    return null
  }
}

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
        :minute-periods-available="minutePeriodsAvailable"
        :on-period-change="onPeriodChange"
      />
      <p v-if="marketError" class="data-error" role="alert">
        {{ quotes.length ? '部分行情未显示' : '真实行情刷新失败' }}：{{ marketError }}
        <small v-if="marketLoadedAt">当前保留数据最后成功读取于 {{ time(marketLoadedAt) }}。</small>
      </p>
      <p v-else-if="marketLoadedAt" class="data-footnote">客户端最后成功读取于 {{ time(marketLoadedAt) }}。</p>
    </section>



    <section class="overview-section facts-section" aria-labelledby="market-news-title">
      <header>
        <h2 id="market-news-title">市场资讯</h2>
        <small>服务端公开资讯爬虫 · 非交易参考</small>
      </header>
      <template v-if="marketNews">
        <p v-if="marketNews.freshness.status === 'stale'" class="data-error" role="status">
          当前展示上次成功抓取的真实资讯；抓取于 {{ time(marketNews.fetched_at) }}。
          {{ marketNews.warnings.join('；') }}
        </p>
        <ul v-if="marketNews.items.length" class="news-list">
          <li v-for="item in marketNews.items" :key="item.id" class="news-item">
            <a
              v-if="safeNewsUrl(item.url)"
              class="news-link"
              :href="safeNewsUrl(item.url) ?? undefined"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span class="news-sector">{{ item.publish_time ? time(item.publish_time) : '时间未知' }}</span>
              <span class="news-title">{{ item.title }}</span>
              <small class="news-source">{{ item.source }}</small>
            </a>
            <div v-else class="news-link">
              <span class="news-sector">{{ item.publish_time ? time(item.publish_time) : '时间未知' }}</span>
              <span class="news-title">{{ item.title }}</span>
              <small class="news-source">{{ item.source }}</small>
            </div>
          </li>
        </ul>
        <p v-else class="empty-data" role="status">当前抓取范围没有可展示的公开资讯。</p>
        <p class="data-footnote">
          抓取于 {{ time(marketNews.fetched_at) }}；来源：{{ marketNews.provider }}；资讯不参与定价或下单。
        </p>
      </template>
      <p v-else-if="marketNewsError" class="data-error" role="alert">市场资讯抓取失败：{{ marketNewsError }}</p>
      <p v-else-if="marketNewsNotice" class="empty-data" role="status">{{ marketNewsNotice }}</p>
      <p v-else class="empty-data">正在读取服务端公开资讯。</p>
    </section>
  </section>
</template>
