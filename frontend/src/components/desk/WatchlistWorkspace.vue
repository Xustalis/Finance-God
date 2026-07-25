<script setup lang="ts">
import { computed, ref, watch } from 'vue'

export interface WatchlistInstrument { instrument_id: string; added_at?: string }
export interface WatchlistGroup { group_id: string; name: string; description: string | null; revision: number; instruments: readonly WatchlistInstrument[] }
export interface ResearchDimension { dimension: string; label: string; rating: string; detail: string; missing_fields: readonly string[] }
export interface ResearchCandidate {
  instrument_id: string
  symbol: string
  name: string | null
  direction_label: string
  purpose: string
  dimensions: readonly ResearchDimension[]
  exclusions: readonly { reason_code: string; detail: string }[]
  ignored: boolean
  ignore_reason: string | null
  tradable?: boolean
  as_of: string | null
  provider: string | null
}

const props = defineProps<{
  groups: readonly WatchlistGroup[]
  candidates: readonly ResearchCandidate[]
  candidateMeta?: {
    generated_at: string
    rule_version: string
    profile_version: number | null
    directions: readonly string[]
    unavailable_reason: string | null
  } | null
  loading: boolean
  watchlistError: string | null
  candidateError: string | null
  candidateNotice?: string | null
  planError?: string | null
  onLoad: () => void | Promise<void>
  onCreateGroup: (input: { name: string; description: string | null }) => void | Promise<void>
  onRenameGroup: (input: { groupId: string; name: string; description: string | null; expectedRevision: number }) => void | Promise<void>
  onDeleteGroup: (input: { groupId: string; expectedRevision: number }) => void | Promise<void>
  onAddInstrument: (input: { groupId: string; instrumentId: string }) => void | Promise<void>
  onRemoveInstrument: (input: { groupId: string; instrumentId: string }) => void | Promise<void>
  onIgnoreCandidate: (input: { instrumentId: string; reason: 'not_now' | 'already_covered' | 'disagree' | 'data_error'; note: string | null }) => void | Promise<void>
  onCreateTradePlan?: (instrumentId: string) => void | Promise<void>
}>()

const selectedGroupId = ref<string | null>(null)
const selectedGroup = computed(() => props.groups.find((item) => item.group_id === selectedGroupId.value) ?? props.groups[0] ?? null)
const newGroupName = ref('')
const newGroupDescription = ref('')
const groupName = ref('')
const groupDescription = ref('')
const instrumentId = ref('')
const candidateUnavailableText = computed(() => {
  const reason = props.candidateMeta?.unavailable_reason
  if (!reason) return null
  return {
    PROFILE_REQUIRED: '需要先完成投资画像，当前没有生成股票候选。',
    PROFILE_DIRECTIONS_REQUIRED: '画像没有可用的选定或推荐方向。',
    NO_SUPPORTED_DIRECTION_CANDIDATES: '当前画像方向在股票候选池中没有受支持标的。',
    MARKET_DATA_UNAVAILABLE: 'PandaData 行情不可用，候选暂不能进入交易计划。',
  }[reason] ?? `候选生成不可用：${reason}`
})

function selectGroup(group: WatchlistGroup) { selectedGroupId.value = group.group_id; groupName.value = group.name; groupDescription.value = group.description ?? '' }
async function createGroup() { if (!newGroupName.value.trim()) return; await props.onCreateGroup({ name: newGroupName.value.trim(), description: newGroupDescription.value.trim() || null }); newGroupName.value = ''; newGroupDescription.value = '' }
async function renameGroup() { if (!selectedGroup.value || !groupName.value.trim()) return; await props.onRenameGroup({ groupId: selectedGroup.value.group_id, name: groupName.value.trim(), description: groupDescription.value.trim() || null, expectedRevision: selectedGroup.value.revision }) }
async function addInstrument() { if (!selectedGroup.value || !instrumentId.value.trim()) return; await props.onAddInstrument({ groupId: selectedGroup.value.group_id, instrumentId: instrumentId.value.trim() }); instrumentId.value = '' }

watch(
  () => [selectedGroup.value?.group_id, selectedGroup.value?.revision] as const,
  () => {
    if (!selectedGroup.value) {
      groupName.value = ''
      groupDescription.value = ''
      return
    }
    selectedGroupId.value = selectedGroup.value.group_id
    groupName.value = selectedGroup.value.name
    groupDescription.value = selectedGroup.value.description ?? ''
  },
  { immediate: true },
)
</script>

<template>
  <section class="information-workspace" aria-labelledby="watchlist-title">
    <header class="overview-heading"><h1 id="watchlist-title">自选</h1><button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新' }}</button></header>
    <section class="overview-section" aria-labelledby="group-title">
      <header><h2 id="group-title">自选分组</h2><small>每项修改均由服务端修订版本校验</small></header>
      <div class="quote-strip" role="list" aria-label="自选分组"><button v-for="group in groups" :key="group.group_id" type="button" :class="{ selected: selectedGroup?.group_id === group.group_id }" @click="selectGroup(group)"><strong>{{ group.name }}</strong><span>{{ group.instruments.length }} 个标的 · 修订 {{ group.revision }}</span></button></div>
      <form class="form-workspace" @submit.prevent="createGroup"><label>新分组名称<input v-model="newGroupName" maxlength="100" required></label><label>说明（可选）<input v-model="newGroupDescription" maxlength="500"></label><button class="ink-button" type="submit">创建分组</button></form>
      <template v-if="selectedGroup">
        <form class="form-workspace" @submit.prevent="renameGroup"><label>当前分组名称<input v-model="groupName" maxlength="100" required></label><label>说明（可选）<input v-model="groupDescription" maxlength="500"></label><button class="refresh-button" type="submit">保存分组</button><button class="refresh-button" type="button" @click="onDeleteGroup({ groupId: selectedGroup!.group_id, expectedRevision: selectedGroup!.revision })">删除分组</button></form>
        <div class="market-table-wrap"><table class="market-table"><thead><tr><th scope="col">标的</th><th scope="col">加入时间</th><th scope="col">操作</th></tr></thead><tbody><tr v-for="instrument in selectedGroup.instruments" :key="instrument.instrument_id"><th scope="row">{{ instrument.instrument_id }}</th><td>{{ instrument.added_at ?? '—' }}</td><td><button class="refresh-button" type="button" @click="onRemoveInstrument({ groupId: selectedGroup!.group_id, instrumentId: instrument.instrument_id })">移除</button></td></tr></tbody></table></div>
        <form class="form-workspace" @submit.prevent="addInstrument"><label>标的代码<input v-model="instrumentId" placeholder="例如：000001.SZ" required></label><button class="ink-button" type="submit">加入当前分组</button></form>
      </template>
      <p v-else class="empty-data">尚无自选分组，请先创建一个分组。</p>
      <p v-if="watchlistError" class="data-error" role="alert">自选读取失败：{{ watchlistError }}</p>
    </section>
    <section class="overview-section" aria-labelledby="candidate-title">
      <header>
        <h2 id="candidate-title">可研究候选</h2>
        <small v-if="candidateMeta">
          画像 v{{ candidateMeta.profile_version ?? '—' }} ·
          {{ candidateMeta.directions.join('、') || '方向未就绪' }} ·
          {{ candidateMeta.generated_at }}
        </small>
        <small v-else>画像投影与市场事实的研究入口</small>
      </header>
      <div v-if="candidates.length" class="market-table-wrap candidate-table"><table class="market-table"><thead><tr><th scope="col">标的</th><th scope="col">用途</th><th scope="col">五项解释维度</th><th scope="col">反方证据 / 未知项</th><th scope="col">操作</th></tr></thead><tbody><tr v-for="candidate in candidates" :key="candidate.instrument_id"><th scope="row">{{ candidate.name || candidate.symbol }}<small>{{ candidate.symbol }} · {{ candidate.direction_label }}</small></th><td>{{ candidate.purpose }}<small>{{ candidate.provider || '—' }} · {{ candidate.as_of || '—' }}</small></td><td><ul class="fact-list"><li v-for="dimension in candidate.dimensions.slice(0, 5)" :key="dimension.dimension"><strong>{{ dimension.label }} · {{ dimension.rating }}</strong><span>{{ dimension.detail }}</span></li></ul></td><td><p v-for="exclusion in candidate.exclusions" :key="exclusion.reason_code">{{ exclusion.detail }}</p><p v-for="dimension in candidate.dimensions.filter((item) => item.missing_fields.length)" :key="`${dimension.dimension}-missing`">未知：{{ dimension.missing_fields.join('、') }}</p><span v-if="!candidate.exclusions.length && !candidate.dimensions.some((item) => item.missing_fields.length)">未返回反方证据或未知项。</span></td><td class="candidate-actions"><template v-if="candidate.ignored"><small>已忽略：{{ candidate.ignore_reason || '—' }}</small></template><template v-else><button class="refresh-button" type="button" @click="onIgnoreCandidate({ instrumentId: candidate.instrument_id, reason: 'not_now', note: null })">暂不研究</button><button v-if="onCreateTradePlan" class="refresh-button" type="button" :disabled="candidate.tradable === false" :title="candidate.tradable === false ? '服务端判定该候选暂不可生成交易计划' : '向服务端申请研究型交易计划，不是直接下单'" @click="onCreateTradePlan(candidate.instrument_id)">申请交易计划</button></template></td></tr></tbody></table></div>
      <p v-else-if="candidateUnavailableText" class="data-error" role="status">{{ candidateUnavailableText }}</p>
      <p v-else-if="candidateNotice" class="empty-data" role="status">{{ candidateNotice }}</p>
      <p v-else-if="!candidateError" class="empty-data">暂无可研究候选。</p>
      <p v-if="candidateError" class="data-error" role="alert">候选读取失败：{{ candidateError }}</p>
      <p v-if="planError" class="data-error" role="alert">交易计划：{{ planError }}</p>
    </section>
  </section>
</template>
