<script setup lang="ts">
import type { AgentLearningSummary, TradeDecisionSnapshot, TradeEpisode, TradeReview } from '@/services/tradingDesk'

withDefaults(defineProps<{
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
}>(), {
  learningSummary: null,
  learningLoading: false,
  learningError: null,
})

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
    <section class="overview-section" aria-labelledby="episode-list-title">
      <header><h2 id="episode-list-title">交易案例</h2><small>按最近变更排序</small></header>
      <div v-if="!episodes.length && !loading" class="workspace-empty-ledger" role="status">
        <header><strong>暂无交易案例</strong><span>首次模拟买入成交后自动建立</span></header>
        <dl>
          <div><dt>案例起点</dt><dd>模拟买入成交形成持仓周期，并保存当时可用的决策快照。</dd></div>
          <div><dt>周期记录</dt><dd>后续买卖、成交价格、画像版本与已记录的风险证据按时间排列。</dd></div>
          <div><dt>终局复盘</dt><dd>持仓归零后生成收益、执行评价、未知项与下次调整；缺失字段显示"当时未记录"。</dd></div>
        </dl>
      </div>
      <div v-if="!episodes.length && !loading" class="review-guide" aria-label="复盘流程说明">
        <section class="review-guide-block">
          <h3>复盘机制</h3>
          <p>每完成一轮从买入到清仓的持仓周期，系统自动生成终局复盘报告。复盘记录决策质量、收益归因与执行偏离，为画像演化提供事实反馈。</p>
        </section>
        <section class="review-guide-block">
          <h3>如何产生首个案例</h3>
          <ol class="review-guide-steps">
            <li><span class="step-num">1</span><span>在「交易」工作区选择标的，完成一次模拟买入</span></li>
            <li><span class="step-num">2</span><span>持仓期间的买卖操作与决策快照自动归档</span></li>
            <li><span class="step-num">3</span><span>卖出至持仓为零时，系统生成终局复盘</span></li>
          </ol>
        </section>
        <section class="review-guide-block">
          <h3>复盘报告包含</h3>
          <dl class="review-guide-contents">
            <div><dt>收益归因</dt><dd>实际盈亏金额与百分比、持有时长</dd></div>
            <div><dt>预期验证</dt><dd>买入时的交易理由是否成立、预期收益与实际的偏差</dd></div>
            <div><dt>执行评价</dt><dd>入场价格、出场时机、仓位管理的评估</dd></div>
            <div><dt>未知项</dt><dd>因记录不完整而无法评价的决策维度</dd></div>
            <div><dt>下次调整</dt><dd>基于本次复盘生成的改进建议</dd></div>
            <div><dt>画像反馈</dt><dd>复盘结论自动更新投资者画像版本</dd></div>
          </dl>
        </section>
      </div>
      <div v-else class="market-table-wrap">
        <table class="market-table">
          <thead><tr><th scope="col">标的</th><th scope="col">状态</th><th scope="col">开始</th><th scope="col">结束</th><th scope="col" class="numeric">当前数量</th></tr></thead>
          <tbody>
            <tr
              v-for="episode in episodes"
              :key="episode.episode_id"
              :class="{ selected: selected?.episode_id === episode.episode_id }"
              tabindex="0"
              @click="onSelect(episode)"
              @keydown.enter="onSelect(episode)"
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

    <template v-if="selected">
      <section class="overview-section" aria-labelledby="timeline-title">
        <header><h2 id="timeline-title">决策与成交时间线</h2><small>{{ selected.episode_id }}</small></header>
        <ol class="review-timeline">
          <li v-for="decision in decisions" :key="decision.snapshot_id">
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
        <header><h2 id="review-result-title">复盘结果</h2><small>{{ statusText[selected.review_status || ''] || '持仓周期未结束' }}</small></header>
        <p v-if="selected.status === 'open'" class="empty-data">持仓仍在进行，归零后自动生成终局复盘。</p>
        <template v-else-if="review">
          <dl class="market-sheet">
            <div><dt>实际收益</dt><dd>{{ money(review.actual_return_rmb) }}<span v-if="review.actual_return_percent"> · {{ review.actual_return_percent }}%</span></dd></div>
            <div><dt>持有时长</dt><dd>{{ Math.round(review.holding_period_seconds / 3600) }} 小时</dd></div>
            <div><dt>预期判断</dt><dd>{{ review.expected_return_assessment }}</dd></div>
            <div><dt>执行评价</dt><dd>{{ review.execution_assessment }}</dd></div>
          </dl>
          <div class="review-findings">
            <section><h3>证据不足</h3><ul><li v-for="item in review.unknown_points" :key="item">{{ item }}</li></ul></section>
            <section><h3>下次调整</h3><ul><li v-for="item in review.next_adjustments" :key="item">{{ item }}</li></ul></section>
          </div>
        </template>
        <button v-else-if="selected.review_status === 'failed'" class="ink-button" type="button" :disabled="loading" @click="onRetry">重试复盘</button>
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
      <template v-else-if="!learningLoading && !learningError">
        <div class="learning-unavailable-detail">
          <p class="empty-data">持续学习 Worker 尚未产出知识快照。</p>
          <dl class="market-sheet learning-summary">
            <div><dt>学习机制</dt><dd>后台 Worker 周期性从市场数据观察、推理并验证投资知识</dd></div>
            <div><dt>产出形式</dt><dd>经验证的学习结论，附带主题、验证方法与失效条件</dd></div>
            <div><dt>更新频率</dt><dd>默认每 15 分钟执行一个学习周期</dd></div>
          </dl>
          <p class="learning-note">Worker 首次运行并完成观察—推理—验证周期后，此处将展示最近已验证的学习成果。</p>
        </div>
      </template>
      <p v-else-if="learningLoading" class="empty-data">正在读取 Agent 自学习状态。</p>
    </section>
  </section>
</template>
