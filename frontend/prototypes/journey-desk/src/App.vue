<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  CAPABILITY_GAPS,
  JOURNEY_SCENARIOS,
  PHASE_PLANS,
  gapSummary,
  normalizeSymbol,
  quickCommandsFor,
  resolveCommand,
  type DeskSection,
  type JourneyId,
  type SafeActionId,
} from './model'

interface MarketSnapshot {
  symbol: string
  name: string
  last: string | number
  change_percent: string | number | null
  provider_time: string
  frequency: string
  freshness: string
  retrieved_at: string
}

interface SnapshotResponse {
  provider: string
  poll_interval_seconds: number
  alert_threshold: number
  snapshots: MarketSnapshot[]
}

interface Message {
  id: number
  role: 'agent' | 'user'
  text: string
}

interface ActionReceipt {
  id: number
  actionId: SafeActionId
  result: 'applied'
  contextVersion: number
}

interface PrototypeNotice {
  id: string
  title: string
  message: string
  severity: 'info' | 'warning'
  read: boolean
}

type LeftPane = DeskSection | 'plan'

const sections: ReadonlyArray<{ id: LeftPane; label: string; description: string }> = [
  { id: 'information', label: '总览', description: '真实行情与事实' },
  { id: 'portfolio', label: '持仓', description: '仿真账户与仓位' },
  { id: 'watchlist', label: '自选', description: '分组与研究候选' },
  { id: 'trading', label: '交易', description: '草稿、复核与提交' },
  { id: 'plan', label: '规划', description: '缺口矩阵与 Phase' },
]

const section = ref<LeftPane>('plan')
const selectedSymbol = ref('000001.SZ')
const contextVersion = ref(1)
const agentCollapsed = ref(localStorage.getItem('fg:journey-desk:agent-collapsed') === 'true')
const agentWidth = ref(Number(localStorage.getItem('fg:journey-desk:agent-width') ?? '50'))
const snapshots = ref<MarketSnapshot[]>([])
const marketMeta = ref<Omit<SnapshotResponse, 'snapshots'> | null>(null)
const marketLoading = ref(false)
const marketError = ref<string | null>(null)
const quantity = ref<number | null>(null)
const side = ref<'buy' | 'sell'>('buy')
const composer = ref('')
const reminderOpen = ref(false)
const myOpen = ref(false)
const toastVisible = ref(true)
const activeWorkflowIntent = ref<{ key: string; title: string } | null>(null)
const activeJourney = ref<JourneyId>('j1_first_visit')
const selectedPhaseId = ref(PHASE_PLANS[0]!.id)
const messages = ref<Message[]>([
  {
    id: 1,
    role: 'agent',
    text: '左侧「规划」页展示当前后端缺口与 P0–P8 可运行阶段。工作区切换后下方三条快捷指令会跟着变；我只能控制安全的左侧状态，设置与最终订单仍由你本人操作。',
  },
])
const receipts = ref<ActionReceipt[]>([])
const notices = ref<PrototypeNotice[]>([
  {
    id: 'contract-notice',
    title: '重大行情提醒 · 合同示例',
    message: '此记录只展示提醒结构，不代表当前市场。正式提醒必须引用 PandaData observation 与规则版本。',
    severity: 'warning',
    read: false,
  },
])
let sequence = 1

const capabilityGaps = CAPABILITY_GAPS
const phasePlans = PHASE_PLANS
const journeyScenarios = JOURNEY_SCENARIOS
const gapCounts = gapSummary()

const spreadStyle = computed(() => ({ '--agent-width': `${agentWidth.value}%` }))
const selectedSnapshot = computed(
  () => snapshots.value.find((item) => item.symbol === selectedSymbol.value) ?? null,
)
const agentSection = computed<DeskSection>(() => (
  section.value === 'plan' ? 'information' : section.value
))
const quickCommands = computed(() => quickCommandsFor(agentSection.value))
const sectionLabel = computed(
  () => sections.find((item) => item.id === section.value)?.label ?? '总览',
)
const unreadCount = computed(() => notices.value.filter((item) => !item.read).length)
const selectedPhase = computed(
  () => phasePlans.find((item) => item.id === selectedPhaseId.value) ?? phasePlans[0]!,
)
const selectedJourney = computed(
  () => journeyScenarios.find((item) => item.id === activeJourney.value) ?? journeyScenarios[0]!,
)
const phaseGaps = computed(() => (
  capabilityGaps.filter((item) => item.phase.split('/').includes(selectedPhaseId.value))
))

watch(agentCollapsed, (value) => {
  localStorage.setItem('fg:journey-desk:agent-collapsed', String(value))
})
watch(agentWidth, (value) => {
  localStorage.setItem('fg:journey-desk:agent-width', String(value))
})

function formatNumber(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number)
}

function formatPercent(value: string | number | null): string {
  if (value === null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number > 0 ? '+' : ''}${(number * 100).toFixed(2)}%`
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function changeSection(next: LeftPane): void {
  if (section.value === next) return
  section.value = next
  contextVersion.value += 1
}

function selectSymbol(symbol: string): void {
  const normalized = normalizeSymbol(symbol)
  if (normalized === selectedSymbol.value) return
  selectedSymbol.value = normalized
  contextVersion.value += 1
}

function statusLabel(status: 'done' | 'partial' | 'missing'): string {
  if (status === 'done') return '已完成'
  if (status === 'partial') return '部分'
  return '缺失'
}

function applyJourney(journeyId: JourneyId): void {
  const journey = journeyScenarios.find((item) => item.id === journeyId)
  if (!journey) return
  activeJourney.value = journey.id
  section.value = journey.section
  selectedSymbol.value = journey.symbol
  contextVersion.value += 1
  toastVisible.value = true
  notices.value = [
    {
      id: `journey-${journey.id}`,
      title: journey.toastTitle,
      message: journey.toastMessage,
      severity: 'info',
      read: false,
    },
    ...notices.value.filter((item) => !item.id.startsWith('journey-')),
  ]
  sequence += 1
  messages.value.push({
    id: sequence,
    role: 'agent',
    text: journey.intro,
  })
}

async function loadSnapshots(): Promise<void> {
  if (marketLoading.value) return
  marketLoading.value = true
  marketError.value = null
  try {
    const response = await fetch('/api/market/snapshots', {
      headers: { Accept: 'application/json' },
    })
    const payload = await response.json().catch(() => null) as SnapshotResponse | { error?: { message?: string } } | null
    if (!response.ok) {
      const message = payload && 'error' in payload ? payload.error?.message : null
      throw new Error(message || `行情快照请求失败（HTTP ${response.status}）`)
    }
    if (!payload || !('snapshots' in payload) || !Array.isArray(payload.snapshots)) {
      throw new Error('行情快照响应不符合合同。')
    }
    snapshots.value = payload.snapshots
    marketMeta.value = {
      provider: payload.provider,
      poll_interval_seconds: payload.poll_interval_seconds,
      alert_threshold: payload.alert_threshold,
    }
    if (payload.snapshots.length && !payload.snapshots.some((item) => item.symbol === selectedSymbol.value)) {
      selectSymbol(payload.snapshots[0]!.symbol)
    }
  } catch (error) {
    marketError.value = error instanceof Error ? error.message : '行情快照请求失败。'
  } finally {
    marketLoading.value = false
  }
}

function applyAction(actionId: SafeActionId, value?: string | number): void {
  if (actionId === 'navigate_information') changeSection('information')
  if (actionId === 'navigate_portfolio') changeSection('portfolio')
  if (actionId === 'navigate_watchlist') changeSection('watchlist')
  if (actionId === 'navigate_trading') changeSection('trading')
  if (actionId === 'select_symbol' && typeof value === 'string') selectSymbol(value)
  if (actionId === 'fill_order_quantity' && typeof value === 'number') {
    changeSection('trading')
    quantity.value = value
  }
  if (actionId === 'refresh_market') void loadSnapshots()
  receipts.value.unshift({
    id: receipts.value.length + 1,
    actionId,
    result: 'applied',
    contextVersion: contextVersion.value,
  })
}

function submitCommand(raw = composer.value): void {
  const text = raw.trim()
  if (!text) return
  composer.value = ''
  sequence += 1
  messages.value.push({ id: sequence, role: 'user', text })
  const resolved = resolveCommand(text)
  if (resolved.kind === 'action') {
    applyAction(resolved.actionId, resolved.value)
    sequence += 1
    messages.value.push({ id: sequence, role: 'agent', text: resolved.message })
    return
  }
  if (resolved.kind === 'workflow') {
    activeWorkflowIntent.value = { key: resolved.workflowKey, title: resolved.title }
    sequence += 1
    messages.value.push({
      id: sequence,
      role: 'agent',
      text: `已识别为“${resolved.title}”。隔离原型不会伪造 WorkflowRun；生产环境应携带当前上下文版本向服务端创建任务。`,
    })
    return
  }
  sequence += 1
  messages.value.push({ id: sequence, role: 'agent', text: resolved.message })
}

function markNoticeRead(notice: PrototypeNotice): void {
  notice.read = true
  toastVisible.value = false
}

function resetLayout(): void {
  agentWidth.value = 50
  agentCollapsed.value = false
}

onMounted(() => {
  void loadSnapshots()
})
</script>

<template>
  <main class="desk-page" aria-label="Finance God Agent 主控交易台旅程原型">
    <header class="desk-topbar">
      <div class="desk-wordmark">
        <strong>FINANCE GOD</strong>
        <span>金融教父 · 投研与决策档案</span>
      </div>
      <div class="topbar-actions">
        <button type="button" class="topbar-button" @click="reminderOpen = !reminderOpen">
          提醒
          <sup v-if="unreadCount">{{ unreadCount }}</sup>
        </button>
        <span aria-hidden="true"></span>
        <button type="button" class="topbar-button" @click="myOpen = !myOpen">我的</button>
      </div>
    </header>

    <section
      class="desk-spread"
      :class="{ 'agent-collapsed': agentCollapsed }"
      :style="spreadStyle"
    >
      <section class="desk-left" aria-label="信息与交易工作区">
        <div class="workspace-bar">
          <nav class="workspace-tabs" aria-label="交易台工作区">
            <button
              v-for="item in sections"
              :key="item.id"
              type="button"
              :class="{ active: section === item.id }"
              :aria-current="section === item.id ? 'page' : undefined"
              @click="changeSection(item.id)"
            >
              {{ item.label }}
            </button>
          </nav>
          <details class="layout-menu">
            <summary>布局</summary>
            <div>
              <label>
                <span>Agent 宽度</span>
                <output>{{ agentWidth }}%</output>
                <input v-model.number="agentWidth" type="range" min="32" max="60" step="1">
              </label>
              <button type="button" @click="agentCollapsed = !agentCollapsed">
                {{ agentCollapsed ? '展开 Agent' : '收起 Agent' }}
              </button>
              <button type="button" @click="resetLayout">恢复 1:1</button>
            </div>
          </details>
        </div>

        <div class="workspace-content">
          <section v-if="section === 'plan'" class="workspace-page plan-page">
            <header class="page-heading">
              <div>
                <span class="eyebrow">GAP MATRIX · PHASE BOARD</span>
                <h1>需求缺口与分阶段计划</h1>
                <p>
                  对照 Agent 主控交易台愿景与当前后端：已完成 {{ gapCounts.done }} ·
                  部分 {{ gapCounts.partial }} · 缺失 {{ gapCounts.missing }}。
                  本页是规划板，不伪造行情、账户或 Workflow 进度。
                </p>
              </div>
            </header>

            <section class="fact-strip" aria-label="缺口摘要">
              <div><span>已完成</span><strong>{{ gapCounts.done }}</strong></div>
              <div><span>部分实现</span><strong>{{ gapCounts.partial }}</strong></div>
              <div><span>完全缺失</span><strong>{{ gapCounts.missing }}</strong></div>
            </section>

            <section class="editorial-section">
              <header>
                <h2>用户旅程场景</h2>
                <small>切换后同步左侧工作区与 Agent 文案</small>
              </header>
              <div class="journey-row">
                <button
                  v-for="journey in journeyScenarios"
                  :key="journey.id"
                  type="button"
                  :class="{ active: activeJourney === journey.id }"
                  @click="applyJourney(journey.id)"
                >
                  {{ journey.label }}
                </button>
              </div>
              <p class="boundary-note">{{ selectedJourney.intro }}</p>
            </section>

            <section class="editorial-section">
              <header>
                <h2>能力缺口矩阵</h2>
                <small>status 基于代码审计，非口头承诺</small>
              </header>
              <div class="table-wrap">
                <table class="market-table gap-table">
                  <thead>
                    <tr>
                      <th>领域</th>
                      <th>要求</th>
                      <th>现状</th>
                      <th>状态</th>
                      <th>阶段</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="gap in capabilityGaps" :key="gap.id">
                      <th scope="row">
                        <strong>{{ gap.area }}</strong>
                        <small>{{ gap.evidence }}</small>
                      </th>
                      <td class="left-text">{{ gap.requirement }}</td>
                      <td class="left-text">{{ gap.current }}</td>
                      <td>
                        <span :class="['status-pill', gap.status]">{{ statusLabel(gap.status) }}</span>
                      </td>
                      <td>{{ gap.phase }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section class="editorial-section">
              <header>
                <h2>Phase 看板</h2>
                <small>每阶段可运行、可观测、有门禁</small>
              </header>
              <div class="phase-row">
                <button
                  v-for="phase in phasePlans"
                  :key="phase.id"
                  type="button"
                  :class="{ active: selectedPhaseId === phase.id }"
                  @click="selectedPhaseId = phase.id"
                >
                  {{ phase.id }}
                </button>
              </div>
              <dl class="object-sheet phase-sheet">
                <div><dt>标题</dt><dd>{{ selectedPhase.title }}</dd></div>
                <div><dt>可运行定义</dt><dd>{{ selectedPhase.runnable }}</dd></div>
                <div><dt>交付物</dt><dd>{{ selectedPhase.deliverables.join(' · ') }}</dd></div>
                <div><dt>可观测量</dt><dd>{{ selectedPhase.observables.join(' · ') }}</dd></div>
                <div class="full-width"><dt>门禁</dt><dd>{{ selectedPhase.gate }}</dd></div>
              </dl>
              <p v-if="phaseGaps.length" class="boundary-note">
                本阶段关联缺口：{{ phaseGaps.map((item) => item.area).join('、') }}
              </p>
              <p v-else class="boundary-note">本阶段主要是基线/发布，不对应单一缺口行。</p>
            </section>

            <section class="editorial-section">
              <header>
                <h2>需求纠偏（已吸收）</h2>
                <small>避免不合理表述进入实现</small>
              </header>
              <ol class="correction-list">
                <li>「推荐购入」→「可研究候选」；Agent 不生成买入指令。</li>
                <li>右侧不是悬浮聊天气泡；三条快捷指令无卡片/阴影，贴合页面底色。</li>
                <li>Agent 不通过 DOM/坐标控制左侧；仅语义 UiActionDescriptor。</li>
                <li>「钱包」→「仿真资金」；始终标明仿真。</li>
                <li>Toast 自动隐藏 ≠ 已读/已处理；P0/P1 提醒不得静默消失。</li>
                <li>订单提交/撤单/划转永远需要用户本人确认；Agent 最高到草稿。</li>
              </ol>
            </section>
          </section>

          <section v-else-if="section === 'information'" class="workspace-page">
            <header class="page-heading">
              <div>
                <span class="eyebrow">MARKET OVERVIEW</span>
                <h1>行情总览</h1>
                <p>服务端快照；显示实际频率、上游时间与 freshness。</p>
              </div>
              <button type="button" class="text-action" :disabled="marketLoading" @click="loadSnapshots">
                {{ marketLoading ? '刷新中' : '刷新' }}
              </button>
            </header>

            <section class="fact-strip" aria-label="行情服务状态">
              <div><span>来源</span><strong>{{ marketMeta?.provider ?? '等待服务端' }}</strong></div>
              <div><span>配置轮询</span><strong>{{ marketMeta ? `${marketMeta.poll_interval_seconds}s` : '未知' }}</strong></div>
              <div><span>当前标的</span><strong>{{ selectedSymbol }}</strong></div>
            </section>

            <p v-if="marketError" class="data-error" role="alert">
              <strong>行情不可用</strong>
              {{ marketError }} 未使用演示价格回退。
            </p>
            <p v-else-if="!marketLoading && !snapshots.length" class="empty-state">
              服务端尚未保存行情快照。页面不会用占位数字替代真实行情。
            </p>
            <div v-else class="table-wrap">
              <table class="market-table">
                <thead>
                  <tr>
                    <th>标的</th>
                    <th>最新价</th>
                    <th>涨跌幅</th>
                    <th>上游时间</th>
                    <th>频率 / 新鲜度</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in snapshots"
                    :key="item.symbol"
                    :class="{ selected: item.symbol === selectedSymbol }"
                    @click="selectSymbol(item.symbol)"
                  >
                    <th scope="row"><strong>{{ item.symbol }}</strong><small>{{ item.name }}</small></th>
                    <td>{{ formatNumber(item.last) }}</td>
                    <td :class="Number(item.change_percent) >= 0 ? 'positive' : 'risk'">
                      {{ formatPercent(item.change_percent) }}
                    </td>
                    <td>{{ formatTime(item.provider_time) }}</td>
                    <td>{{ item.frequency }} / {{ item.freshness }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <section class="editorial-section">
              <header><h2>当前对象</h2><small>context v{{ contextVersion }}</small></header>
              <dl v-if="selectedSnapshot" class="object-sheet">
                <div><dt>标的</dt><dd>{{ selectedSnapshot.name }} · {{ selectedSnapshot.symbol }}</dd></div>
                <div><dt>上游时间</dt><dd>{{ formatTime(selectedSnapshot.provider_time) }}</dd></div>
                <div><dt>摄取时间</dt><dd>{{ formatTime(selectedSnapshot.retrieved_at) }}</dd></div>
                <div><dt>数据状态</dt><dd>{{ selectedSnapshot.freshness }}</dd></div>
              </dl>
              <p v-else class="empty-state compact">选择标的后在此绑定左右上下文。</p>
            </section>
          </section>

          <section v-else-if="section === 'portfolio'" class="workspace-page">
            <header class="page-heading">
              <div><span class="eyebrow">SIMULATION PORTFOLIO</span><h1>仿真持仓</h1><p>账户与持仓是仿真事实；估值必须引用真实行情。</p></div>
            </header>
            <div class="simulation-banner">仿真账户 · 当前原型不连接账户事实</div>
            <section class="editorial-section">
              <header><h2>账户摘要</h2><small>等待 Desk Bootstrap</small></header>
              <dl class="object-sheet">
                <div><dt>可用现金</dt><dd>尚未加载</dd></div>
                <div><dt>冻结资金</dt><dd>尚未加载</dd></div>
                <div><dt>组合市值</dt><dd>行情不可用时不得估算</dd></div>
              </dl>
            </section>
            <section class="editorial-section">
              <header><h2>持仓明细</h2><small>仿真</small></header>
              <p class="empty-state compact">没有服务端组合投影；不在浏览器构造示例仓位。</p>
            </section>
          </section>

          <section v-else-if="section === 'watchlist'" class="workspace-page">
            <header class="page-heading">
              <div><span class="eyebrow">WATCHLIST & RESEARCH</span><h1>自选与研究</h1><p>候选是研究对象，不是买入指令。</p></div>
            </header>
            <section class="editorial-section">
              <header><h2>当前观察对象</h2><small>上下文 v{{ contextVersion }}</small></header>
              <div class="watch-row">
                <button type="button" :class="{ active: selectedSymbol === '000001.SZ' }" @click="selectSymbol('000001.SZ')">000001.SZ</button>
                <button type="button" :class="{ active: selectedSymbol === '600519.SH' }" @click="selectSymbol('600519.SH')">600519.SH</button>
                <button type="button" :class="{ active: selectedSymbol === '300750.SZ' }" @click="selectSymbol('300750.SZ')">300750.SZ</button>
              </div>
              <p class="boundary-note">这些标的仅用于验证上下文切换；价格仍只来自服务端行情快照。</p>
            </section>
            <section class="editorial-section">
              <header><h2>可研究候选</h2><small>需要画像投影 + 行情版本 + 反方证据</small></header>
              <p class="empty-state compact">尚未创建候选工作流。右侧可发起研究意图，但原型不会伪造结果。</p>
            </section>
          </section>

          <section v-else class="workspace-page">
            <header class="page-heading">
              <div><span class="eyebrow">SIMULATION ORDER DRAFT</span><h1>仿真交易</h1><p>Agent 可填写草稿；复核、风险确认和提交由本人完成。</p></div>
            </header>
            <div class="simulation-banner">未提交草稿 · 不构成订单事实</div>
            <form class="trade-form" @submit.prevent>
              <label><span>标的</span><input :value="selectedSymbol" readonly></label>
              <fieldset>
                <legend>方向</legend>
                <button type="button" :class="{ active: side === 'buy' }" @click="side = 'buy'">买入</button>
                <button type="button" :class="{ active: side === 'sell' }" @click="side = 'sell'">卖出</button>
              </fieldset>
              <label><span>数量</span><input v-model.number="quantity" type="number" min="1" placeholder="由本人或 Agent 填写"></label>
              <label><span>引用价</span><input value="等待有效服务端行情版本" readonly></label>
              <footer>
                <button type="button" class="ink-button" disabled>复核后由本人提交</button>
                <small>隔离原型不创建、提交或撤销订单。</small>
              </footer>
            </form>
          </section>
        </div>
      </section>

      <aside class="desk-agent" :class="{ collapsed: agentCollapsed }" aria-label="交易 Agent">
        <button v-if="agentCollapsed" type="button" class="agent-rail" @click="agentCollapsed = false">
          <strong>AI AGENT</strong><span>{{ sectionLabel }} · {{ selectedSymbol }}</span>
        </button>
        <div v-else class="agent-expanded">
          <header class="agent-heading">
            <div><span class="eyebrow">CONTEXTUAL CONTROL</span><h2>AI AGENT</h2><p>{{ sectionLabel }} · {{ selectedSymbol }} · context v{{ contextVersion }}</p></div>
            <button type="button" class="text-action" @click="agentCollapsed = true">收起</button>
          </header>

          <section class="agent-thread" aria-live="polite">
            <article v-for="message in messages" :key="message.id" :class="['message', message.role]">
              <small>{{ message.role === 'agent' ? 'AGENT' : 'YOU' }}</small>
              <p>{{ message.text }}</p>
            </article>

            <section v-if="activeWorkflowIntent" class="workflow-request">
              <header><span>当前任务请求</span><strong>未创建</strong></header>
              <p>{{ activeWorkflowIntent.title }} · {{ activeWorkflowIntent.key }}</p>
              <small>生产实现应 POST /api/workflows，并以服务端回执替换此状态。</small>
            </section>

            <details class="workflow-contract">
              <summary>
                <span><i aria-hidden="true"></i>完成态展示合同</span>
                <small>completed · 默认折叠</small>
              </summary>
              <ol>
                <li><span>读取版本化输入</span><b>completed</b></li>
                <li><span>执行研究节点</span><b>completed</b></li>
                <li><span>保存证据产物</span><b>completed</b></li>
              </ol>
              <p>静态合同示意，不代表本次浏览器会话已运行工作流。</p>
            </details>

            <section v-if="receipts.length" class="action-audit">
              <header><span>最近动作回执</span><small>descriptor desk-actions/v1</small></header>
              <p v-for="receipt in receipts.slice(0, 3)" :key="receipt.id">
                {{ receipt.actionId }} · {{ receipt.result }} · context v{{ receipt.contextVersion }}
              </p>
            </section>
          </section>

          <form class="agent-composer" @submit.prevent="submitCommand()">
            <div class="quick-commands" aria-label="上下文快捷指令">
              <button v-for="command in quickCommands" :key="command" type="button" @click="submitCommand(command)">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M20 11.5a7.5 7.5 0 0 1-8 7.48 8.2 8.2 0 0 1-3.2-.72L4 20l1.3-4.1A7.5 7.5 0 1 1 20 11.5Z"/>
                </svg>
                <span>{{ command }}</span>
              </button>
            </div>
            <div class="composer-row">
              <textarea v-model="composer" rows="2" aria-label="向 Agent 输入指令" placeholder="例如：打开交易并把数量填写成 200 股"></textarea>
              <button type="submit" class="send-button" aria-label="发送指令">发送</button>
            </div>
            <p>Agent 可见：工作区、标的、版本。不可见：设置、凭据、原始问卷、最终提交。</p>
          </form>
        </div>
      </aside>
    </section>

    <aside v-if="reminderOpen" class="floating-panel reminder-panel" aria-label="提醒记录">
      <header><div><span class="eyebrow">NOTIFICATION HISTORY</span><h2>提醒记录</h2></div><button type="button" @click="reminderOpen = false">关闭</button></header>
      <ol>
        <li v-for="notice in notices" :key="notice.id" :class="{ unread: !notice.read }">
          <strong>{{ notice.title }}</strong>
          <p>{{ notice.message }}</p>
          <small>{{ notice.severity }} · 状态 {{ notice.read ? '已读' : '未读' }}</small>
          <button v-if="!notice.read" type="button" @click="markNoticeRead(notice)">标记已读</button>
        </li>
      </ol>
    </aside>

    <aside v-if="myOpen" class="floating-panel my-panel" aria-label="我的">
      <header><div><span class="eyebrow">PERSONAL CONTROL PLANE</span><h2>我的</h2></div><button type="button" @click="myOpen = false">关闭</button></header>
      <nav aria-label="我的功能"><button type="button">用户画像</button><button type="button">仿真资金</button><button type="button">交易记录</button><button type="button" class="active">设置</button></nav>
      <section>
        <h3>用户本人设置</h3>
        <p>此区域不会发布到 Agent capability、上下文或动作目录。服务端只可按获准用途生成最小画像投影。</p>
        <label><span>提醒声音</span><input type="checkbox"></label>
        <label><span>交易前二次确认</span><input type="checkbox" checked></label>
        <button type="button" class="ink-button">保存原型偏好</button>
      </section>
    </aside>

    <aside v-if="toastVisible && notices[0] && !reminderOpen" class="alert-toast" role="status">
      <strong>{{ notices[0].title }}</strong>
      <p>{{ notices[0].message }}</p>
      <div><button type="button" @click="reminderOpen = true">查看记录</button><button type="button" @click="toastVisible = false">仅关闭浮层</button></div>
    </aside>
  </main>
</template>
