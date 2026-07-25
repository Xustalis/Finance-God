<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AgentLearningSummary, TradeDecisionSnapshot, TradeEpisode, TradeReview } from '@/services/tradingDesk'

const props = withDefaults(defineProps<{
  episodes: readonly TradeEpisode[]
  selected: TradeEpisode | null
  decisions: readonly TradeDecisionSnapshot[]
  review: TradeReview | null
  loading: boolean
  error: string | null
  learningSummary?: AgentLearningSummary | null
  learningLoading?: boolean
  learningError?: string | null
  onLoad: () => void | Promise<void>
  onRetryLearning: () => void | Promise<void>
  onSelect: (episode: TradeEpisode) => void | Promise<void>
  onRetry: () => void | Promise<void>
  demoMode?: boolean
}>(), {
  learningSummary: null,
  learningLoading: false,
  learningError: null,
  demoMode: false,
})

const mockEpisodes: TradeEpisode[] = [
  {
    episode_id: 'mock-episode-600519',
    owner_id: 'mock-user',
    account_id: 'mock-account',
    instrument_id: '600519.SH',
    status: 'review_completed',
    review_status: 'completed',
    opened_at: '2026-06-18 10:12',
    closed_at: '2026-07-08 14:36',
    opening_quantity: '100',
    current_quantity: '0',
    revision: 3,
    created_at: '2026-06-18T02:12:00Z',
    updated_at: '2026-07-08T06:36:00Z',
  },
  {
    episode_id: 'mock-episode-510300',
    owner_id: 'mock-user',
    account_id: 'mock-account',
    instrument_id: '510300.SH',
    status: 'open',
    review_status: null,
    opened_at: '2026-07-21 09:48',
    closed_at: null,
    opening_quantity: '500',
    current_quantity: '500',
    revision: 1,
    created_at: '2026-07-21T01:48:00Z',
    updated_at: '2026-07-25T07:00:00Z',
  },
]

const mockDecisions: Record<string, TradeDecisionSnapshot[]> = {
  'mock-episode-600519': [
    {
      snapshot_id: 'mock-decision-buy-600519',
      episode_id: 'mock-episode-600519',
      order_id: 'mock-order-buy-600519',
      fill_id: 'mock-fill-buy-600519',
      instrument_id: '600519.SH',
      side: 'buy',
      quantity: '100',
      price: '1418.60',
      fee: '42.56',
      occurred_at: '2026-06-18 10:12',
      market_evidence: {},
      profile_version: 7,
      thesis: { status: 'available', value: '估值回到近三年中枢下沿，现金流质量保持稳定。', unavailable_reason: null },
      expected_return: { status: 'available', value: '目标区间收益 6%—10%。', unavailable_reason: null },
      primary_risks: { status: 'available', value: '消费复苏弱于预期，渠道库存去化速度放缓。', unavailable_reason: null },
      contrary_evidence: { status: 'available', value: '北向资金连续三日净流出，短期价格趋势仍弱。', unavailable_reason: null },
      expected_holding_period: { status: 'available', value: '4—8 周。', unavailable_reason: null },
      confidence: { status: 'available', value: '中等。', unavailable_reason: null },
    },
    {
      snapshot_id: 'mock-decision-sell-600519',
      episode_id: 'mock-episode-600519',
      order_id: 'mock-order-sell-600519',
      fill_id: 'mock-fill-sell-600519',
      instrument_id: '600519.SH',
      side: 'sell',
      quantity: '100',
      price: '1496.20',
      fee: '164.58',
      occurred_at: '2026-07-08 14:36',
      market_evidence: {},
      profile_version: 7,
      thesis: { status: 'available', value: '价格进入原定目标区间，按计划退出。', unavailable_reason: null },
      expected_return: { status: 'unavailable', value: null, unavailable_reason: '平仓时未单独记录' },
      primary_risks: { status: 'available', value: '缩量上涨后回撤概率增加。', unavailable_reason: null },
      contrary_evidence: { status: 'unavailable', value: null, unavailable_reason: '平仓时未单独记录' },
      expected_holding_period: { status: 'unavailable', value: null, unavailable_reason: '平仓时不适用' },
      confidence: { status: 'available', value: '较高。', unavailable_reason: null },
    },
  ],
  'mock-episode-510300': [
    {
      snapshot_id: 'mock-decision-buy-510300',
      episode_id: 'mock-episode-510300',
      order_id: 'mock-order-buy-510300',
      fill_id: 'mock-fill-buy-510300',
      instrument_id: '510300.SH',
      side: 'buy',
      quantity: '500',
      price: '4.126',
      fee: '5.00',
      occurred_at: '2026-07-21 09:48',
      market_evidence: {},
      profile_version: 7,
      thesis: { status: 'available', value: '通过宽基仓位降低单一行业暴露。', unavailable_reason: null },
      expected_return: { status: 'available', value: '跟随基准获取中期市场收益。', unavailable_reason: null },
      primary_risks: { status: 'available', value: '指数可能继续震荡，资金占用时间延长。', unavailable_reason: null },
      contrary_evidence: { status: 'available', value: '成交量尚未确认趋势反转。', unavailable_reason: null },
      expected_holding_period: { status: 'available', value: '3—6 个月。', unavailable_reason: null },
      confidence: { status: 'available', value: '中等。', unavailable_reason: null },
    },
  ],
}

const mockReviews: Record<string, TradeReview> = {
  'mock-episode-600519': {
    review_id: 'mock-review-600519',
    episode_id: 'mock-episode-600519',
    status: 'completed',
    kind: 'final',
    expected_return_assessment: '实际收益落在原定目标区间内，核心判断基本成立。',
    actual_return_rmb: '7552.86',
    actual_return_percent: '5.32',
    holding_period_seconds: 1_746_240,
    execution_assessment: '买入分两档报价但一次成交；退出遵守目标区间，未追求最高点。',
    established_points: ['估值修复逻辑得到价格验证'],
    failed_points: ['预期收益下沿判断略偏乐观'],
    unknown_points: ['未记录同期渠道库存的可比口径', '无法区分估值修复与市场风格贡献'],
    next_adjustments: ['建仓前保存同业估值分位', '退出时补记反方证据与机会成本'],
    evidence_references: [],
    profile_feedback_id: 'mock-profile-feedback-7',
    error: null,
    completed_at: '2026-07-08T06:38:00Z',
  },
}

const mockSelectedId = ref(mockEpisodes[0].episode_id)
const showMock = computed(() => props.demoMode && !props.loading && !props.error && props.episodes.length === 0)
const visibleEpisodes = computed(() => showMock.value ? mockEpisodes : props.episodes)
const visibleSelected = computed(() => {
  if (!showMock.value) return props.selected
  return mockEpisodes.find((episode) => episode.episode_id === mockSelectedId.value) ?? mockEpisodes[0]
})
const visibleDecisions = computed(() => {
  if (!showMock.value) return props.decisions
  return mockDecisions[visibleSelected.value?.episode_id ?? ''] ?? []
})
const visibleReview = computed(() => {
  if (!showMock.value) return props.review
  return mockReviews[visibleSelected.value?.episode_id ?? ''] ?? null
})

function selectEpisode(episode: TradeEpisode): void | Promise<void> {
  if (showMock.value) {
    mockSelectedId.value = episode.episode_id
    return
  }
  return props.onSelect(episode)
}

const statusText: Record<string, string> = {
  open: '持仓周期进行中',
  closed_pending_review: '待复盘',
  review_completed: '复盘完成',
  review_failed: '复盘失败',
  pending: '待生成',
  completed: '已完成',
  failed: '失败',
}

const learningStatusText: Record<AgentLearningSummary['status'], string> = {
  healthy: '正常运行',
  stale: '数据陈旧',
  unavailable: '尚未运行',
  error: '运行异常',
}

function localTime(value: string | null | undefined): string {
  if (!value) return '尚无完成记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

function money(value: string | null | undefined): string {
  if (value == null) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function decisionText(field: { status: string; value: string | null; unavailable_reason: string | null }): string {
  return field.status === 'available' && field.value ? field.value : '当时未记录'
}
</script>

<template>
  <section class="information-workspace review-workspace" aria-labelledby="review-title">
    <header class="overview-heading">
      <div><p class="chapter">模拟交易 · 决策档案</p><h1 id="review-title">交易复盘</h1></div>
      <button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '读取中' : '刷新' }}</button>
    </header>

    <p v-if="error" class="data-error" role="alert">{{ error }}</p>
    <p v-if="showMock" class="empty-data mock-disclosure" role="status">演示数据 · 以下案例用于本地界面预览，不代表真实账户、成交或 Agent 结论。</p>
    <section class="overview-section" aria-labelledby="episode-list-title">
      <header><h2 id="episode-list-title">交易案例</h2><small>按最近变更排序</small></header>
      <p v-if="!visibleEpisodes.length && !loading" class="empty-data">暂无交易案例。首次模拟买入成交后自动建立。</p>
      <div v-else class="market-table-wrap">
        <table class="market-table">
          <thead><tr><th scope="col">标的</th><th scope="col">状态</th><th scope="col">开始</th><th scope="col">结束</th><th scope="col" class="numeric">当前数量</th></tr></thead>
          <tbody>
            <tr
              v-for="episode in visibleEpisodes"
              :key="episode.episode_id"
              :class="{ selected: visibleSelected?.episode_id === episode.episode_id }"
              tabindex="0"
              @click="selectEpisode(episode)"
              @keydown.enter="selectEpisode(episode)"
            >
              <th scope="row">{{ episode.instrument_id }}</th>
              <td>{{ statusText[episode.status] || episode.status }}</td>
              <td>{{ episode.opened_at }}</td>
              <td>{{ episode.closed_at || '—' }}</td>
              <td class="numeric">{{ episode.current_quantity }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <template v-if="visibleSelected">
      <section class="overview-section" aria-labelledby="timeline-title">
        <header><h2 id="timeline-title">决策与成交时间线</h2><small>{{ visibleSelected.episode_id }}</small></header>
        <ol class="review-timeline">
          <li v-for="decision in visibleDecisions" :key="decision.snapshot_id">
            <header><strong>{{ decision.side === 'buy' ? '买入' : '卖出' }} {{ decision.quantity }} 股</strong><time>{{ decision.occurred_at }}</time></header>
            <dl class="market-sheet">
              <div><dt>成交价</dt><dd>{{ money(decision.price) }}</dd></div>
              <div><dt>画像版本</dt><dd>{{ decision.profile_version == null ? '当时未记录' : `v${decision.profile_version}` }}</dd></div>
              <div><dt>为什么交易</dt><dd>{{ decisionText(decision.thesis) }}</dd></div>
              <div><dt>预期收益</dt><dd>{{ decisionText(decision.expected_return) }}</dd></div>
              <div><dt>主要风险</dt><dd>{{ decisionText(decision.primary_risks) }}</dd></div>
              <div><dt>反方证据</dt><dd>{{ decisionText(decision.contrary_evidence) }}</dd></div>
              <div><dt>预计持有周期</dt><dd>{{ decisionText(decision.expected_holding_period) }}</dd></div>
              <div><dt>信心程度</dt><dd>{{ decisionText(decision.confidence) }}</dd></div>
            </dl>
          </li>
        </ol>
      </section>

      <section class="overview-section" aria-labelledby="review-result-title">
        <header><h2 id="review-result-title">复盘结果</h2><small>{{ statusText[visibleSelected.review_status || ''] || '持仓周期未结束' }}</small></header>
        <p v-if="visibleSelected.status === 'open'" class="empty-data">持仓仍在进行，归零后自动生成终局复盘。</p>
        <template v-else-if="visibleReview">
          <dl class="market-sheet">
            <div><dt>实际收益</dt><dd>{{ money(visibleReview.actual_return_rmb) }}<span v-if="visibleReview.actual_return_percent"> · {{ visibleReview.actual_return_percent }}%</span></dd></div>
            <div><dt>持有时长</dt><dd>{{ Math.round(visibleReview.holding_period_seconds / 3600) }} 小时</dd></div>
            <div><dt>预期判断</dt><dd>{{ visibleReview.expected_return_assessment }}</dd></div>
            <div><dt>执行评价</dt><dd>{{ visibleReview.execution_assessment }}</dd></div>
          </dl>
          <div class="review-findings">
            <section><h3>证据不足</h3><ul><li v-for="item in visibleReview.unknown_points" :key="item">{{ item }}</li></ul></section>
            <section><h3>下次调整</h3><ul><li v-for="item in visibleReview.next_adjustments" :key="item">{{ item }}</li></ul></section>
          </div>
        </template>
        <button v-else-if="visibleSelected.review_status === 'failed'" class="ink-button" type="button" :disabled="loading" @click="onRetry">重试复盘</button>
        <p v-else class="empty-data">复盘正在生成。</p>
      </section>
    </template>

    <section class="overview-section agent-learning-section" aria-labelledby="agent-learning-title">
      <header>
        <div>
          <h2 id="agent-learning-title">Agent 自学习</h2>
          <p class="learning-scope">系统级研究知识，与当前选中的单笔交易案例无直接归属关系。</p>
        </div>
        <small v-if="learningSummary">{{ learningStatusText[learningSummary.status] }} · {{ localTime(learningSummary.last_cycle?.completed_at) }}</small>
        <small v-else>{{ learningLoading ? '读取中' : '状态未知' }}</small>
      </header>

      <p v-if="learningError" class="data-error" role="alert">{{ learningError }}</p>
      <button v-if="learningError" class="ink-button learning-retry" type="button" :disabled="learningLoading" @click="onRetryLearning">
        {{ learningLoading ? '重试中' : '重试自学习状态' }}
      </button>

      <template v-else-if="learningSummary">
        <p v-if="learningSummary.message" :class="learningSummary.status === 'error' ? 'data-error' : 'empty-data'">{{ learningSummary.message }}</p>
        <dl v-if="learningSummary.snapshot" class="market-sheet learning-summary">
          <div><dt>运行状态</dt><dd>{{ learningStatusText[learningSummary.status] }}</dd></div>
          <div><dt>知识版本</dt><dd>v{{ learningSummary.snapshot.version }}</dd></div>
          <div><dt>累计学习成果</dt><dd>{{ learningSummary.snapshot.total_lessons }}</dd></div>
        </dl>
        <p v-if="!learningSummary.recent_verified_lessons.length" class="empty-data">
          {{ learningSummary.status === 'healthy' || learningSummary.status === 'stale'
            ? '后端已运行，当前暂无通过验证的学习结论。'
            : '当前暂无通过验证的学习结论。' }}
        </p>
        <ol v-else class="learning-lessons">
          <li v-for="lesson in learningSummary.recent_verified_lessons" :key="lesson.lesson_id">
            <p>{{ lesson.statement }}</p>
            <small>{{ lesson.topic }} · 周期 {{ lesson.cycle }} · {{ lesson.validation_method || '验证方法未记录' }}</small>
            <p v-if="lesson.tags.length" class="learning-meta">标签：{{ lesson.tags.join('、') }}</p>
            <p v-if="lesson.invalidation_conditions.length" class="learning-meta">失效条件：{{ lesson.invalidation_conditions.join('；') }}</p>
          </li>
        </ol>
      </template>
      <p v-else-if="learningLoading" class="empty-data">正在读取 Agent 自学习状态。</p>
    </section>
  </section>
</template>
