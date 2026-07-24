<script setup lang="ts">
/**
 * DataView — 数据目录页
 * 左栏数据集列表 + 主栏数据集详情 + 右栏数据质量
 * 调用 /api/market/catalog 获取 PandaData 真实数据目录
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import { fetchCatalog } from '@/api/desk'
import type { CatalogResponse } from '@/types/desk'

const market = useMarketStore()

const catalog = ref<CatalogResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const selectedName = ref<string | null>(null)
const searchQuery = ref('')

const filteredDatasets = computed(() => {
  if (!catalog.value) return []
  const ds = catalog.value.datasets
  if (!searchQuery.value.trim()) return ds
  const q = searchQuery.value.toLowerCase()
  return ds.filter(d =>
    d.name.toLowerCase().includes(q) ||
    (d.description || '').toLowerCase().includes(q) ||
    (d.frequency || '').toLowerCase().includes(q) ||
    (d.market || '').toLowerCase().includes(q)
  )
})

const selectedDataset = computed(() => {
  if (!selectedName.value || !catalog.value) return null
  return catalog.value.datasets.find(d => d.name === selectedName.value) ?? null
})

const summaryEntries = computed(() => {
  if (!catalog.value?.summary) return []
  return Object.entries(catalog.value.summary).map(([key, value]) => ({
    label: key,
    value: typeof value === 'object' ? JSON.stringify(value) : String(value),
  }))
})

async function loadData() {
  loading.value = true
  error.value = null
  try {
    catalog.value = await fetchCatalog() as CatalogResponse
    if (catalog.value.datasets.length > 0) {
      selectedName.value = catalog.value.datasets[0].name
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function selectDataset(name: string) {
  selectedName.value = name
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
          <span>数据集</span>
          <small>DATASETS</small>
        </h2>
        <div class="search-box">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索数据集..."
            aria-label="搜索数据集"
          />
        </div>
        <div v-if="loading" class="summary-empty">加载数据目录...</div>
        <div v-else-if="filteredDatasets.length === 0" class="summary-empty">
          <span>{{ searchQuery ? '没有匹配的数据集' : '暂无数据' }}</span>
        </div>
        <div v-else class="dataset-list">
          <button
            v-for="ds in filteredDatasets"
            :key="ds.name"
            class="dataset-item"
            :class="{ active: selectedName === ds.name }"
            @click="selectDataset(ds.name)"
          >
            <strong>{{ ds.name }}</strong>
            <span>{{ ds.frequency || '—' }} · {{ ds.market || '—' }}</span>
          </button>
        </div>
        <div class="rail-action">
          <button class="secondary-button" :disabled="loading" @click="loadData">刷新目录</button>
        </div>
      </section>
    </template>

    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>数据目录</span>
          <span>DATA CATALOG</span>
        </div>
        <h1 class="lead-title">
          PandaData 数据集
          <small v-if="catalog">共 {{ catalog.datasets.length }} 个数据集</small>
        </h1>
      </div>

      <div v-if="loading" class="table-state">加载数据目录...</div>
      <div v-else-if="error" class="table-state">
        <strong class="down">目录加载失败</strong>
        <span>{{ error }}</span>
        <button class="secondary-button" style="margin-top:10px" @click="loadData">重试</button>
      </div>

      <template v-else>
        <!-- 选中数据集详情 -->
        <div v-if="selectedDataset" class="dataset-detail">
          <h2 class="dataset-name">{{ selectedDataset.name }}</h2>
          <p v-if="selectedDataset.description" class="dataset-desc">{{ selectedDataset.description }}</p>

          <div class="meta-grid">
            <div class="meta-item" v-if="selectedDataset.frequency">
              <span>频率</span>
              <strong>{{ selectedDataset.frequency }}</strong>
            </div>
            <div class="meta-item" v-if="selectedDataset.market">
              <span>市场</span>
              <strong>{{ selectedDataset.market }}</strong>
            </div>
            <div
              class="meta-item"
              v-for="(value, key) in selectedDataset"
              :key="String(key)"
            >
              <template v-if="!['name','description','frequency','market'].includes(String(key))">
                <span>{{ String(key) }}</span>
                <strong>{{ typeof value === 'object' ? JSON.stringify(value) : String(value) }}</strong>
              </template>
            </div>
          </div>
        </div>
        <div v-else class="table-state">
          <span>从左侧选择数据集查看详情</span>
        </div>

        <!-- 全量数据集表格 -->
        <div class="catalog-section">
          <h2 class="section-heading">全部数据集 <small>ALL DATASETS</small></h2>
          <div class="catalog-table">
            <div class="ctable-header">
              <span class="col-name">名称</span>
              <span class="col-meta">频率</span>
              <span class="col-meta">市场</span>
              <span class="col-desc">说明</span>
            </div>
            <button
              v-for="ds in filteredDatasets"
              :key="'t-' + ds.name"
              class="ctable-row"
              :class="{ active: selectedName === ds.name }"
              @click="selectDataset(ds.name)"
            >
              <strong class="col-name">{{ ds.name }}</strong>
              <span class="col-meta">{{ ds.frequency || '—' }}</span>
              <span class="col-meta">{{ ds.market || '—' }}</span>
              <span class="col-desc">{{ ds.description || '—' }}</span>
            </button>
          </div>
        </div>
      </template>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>数据源</span>
          <small>PROVIDER</small>
        </h2>
        <div v-if="catalog" class="summary-grid">
          <div class="summary-row">
            <span>提供商</span>
            <strong>{{ catalog.provider }}</strong>
          </div>
          <div class="summary-row">
            <span>数据集数</span>
            <strong>{{ catalog.datasets.length }}</strong>
          </div>
        </div>

        <div v-if="summaryEntries.length > 0" class="summary-grid">
          <div class="summary-row" v-for="entry in summaryEntries" :key="entry.label">
            <span>{{ entry.label }}</span>
            <strong>{{ entry.value }}</strong>
          </div>
        </div>
        <div v-else class="summary-empty">
          <span>暂无摘要信息</span>
        </div>

        <div class="summary-grid" v-if="market.health">
          <div class="summary-row">
            <span>行情状态</span>
            <strong>{{ market.health.readiness === 'ready' ? '就绪' : '未就绪' }}</strong>
          </div>
          <div class="summary-row">
            <span>账户模式</span>
            <strong>{{ market.health.account_mode }}</strong>
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

.search-box { padding: 10px 18px; }
.search-box input { min-height: 36px; font-size: 13px; }

.dataset-list { max-height: 55vh; overflow-y: auto; scrollbar-width: thin; }
.dataset-item {
  display: grid; gap: 2px; width: 100%;
  padding: 8px 18px; border: 0;
  border-bottom: 1px solid var(--faint-rule); background: transparent;
  text-align: left; cursor: pointer; transition: background 0.15s;
}
.dataset-item:hover { background: var(--faint-rule); }
.dataset-item.active { background: rgb(45 34 22 / 10%); border-left: 3px solid var(--risk); padding-left: 15px; }
.dataset-item strong {
  font-family: var(--font-numeric); font-size: 13px; font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dataset-item span { font-size: 11px; color: var(--muted-ink); }

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

.table-state { padding: 40px 20px; color: var(--muted-ink); font-size: 14px; text-align: center; }
.table-state strong { display: block; margin-bottom: 4px; }

.dataset-detail {
  padding: 0 0 20px; border-bottom: 1px solid var(--rule); margin-bottom: 20px;
}
.dataset-name {
  font-family: var(--font-numeric); font-size: 1.4rem; font-weight: 700;
  margin: 0 0 6px; letter-spacing: 0;
}
.dataset-desc { color: var(--muted-ink); font-size: 14px; margin: 0 0 14px; line-height: 1.6; }

.meta-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 0;
  border-top: 1px solid var(--rule);
}
.meta-item {
  padding: 8px 0; border-bottom: 1px solid var(--faint-rule);
}
.meta-item:nth-child(2n+1) { padding-right: 12px; border-right: 1px solid var(--faint-rule); }
.meta-item:nth-child(2n) { padding-left: 12px; }
.meta-item span { display: block; color: var(--muted-ink); font-size: 11px; }
.meta-item strong { font-family: var(--font-numeric); font-size: 13px; font-weight: 700; word-break: break-all; }

.catalog-section { margin-top: 20px; }
.section-heading {
  display: flex; align-items: baseline; gap: 10px;
  padding: 10px 20px 6px; font-size: 14px; font-weight: 900;
  letter-spacing: 0.03em; margin: 0; border-bottom: 1px solid var(--rule);
}
.section-heading small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em;
}

.catalog-table { border-top: 1px solid var(--rule); }
.ctable-header {
  display: grid; grid-template-columns: minmax(0,1fr) 80px 80px minmax(0,1.5fr); gap: 6px;
  padding: 8px 20px 6px; font-size: 11px; font-weight: 900;
  color: var(--muted-ink); letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}

.ctable-row {
  display: grid; grid-template-columns: minmax(0,1fr) 80px 80px minmax(0,1.5fr); gap: 6px;
  width: 100%; padding: 8px 20px; border: 0;
  border-bottom: 1px solid var(--faint-rule); background: transparent;
  font-size: 13px; text-align: left; cursor: pointer; transition: background 0.15s;
}
.ctable-row:hover { background: var(--faint-rule); }
.ctable-row.active { background: rgb(45 34 22 / 10%); }
.ctable-row .col-name {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ctable-row .col-meta {
  font-family: var(--font-numeric); font-size: 12px; color: var(--muted-ink);
}
.ctable-row .col-desc {
  font-size: 12px; color: var(--muted-ink);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.summary-grid { padding: 14px 18px; }
.summary-grid + .summary-grid { border-top: 1px solid var(--rule); }
.summary-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; }

.summary-empty { padding: 28px 18px; color: var(--muted-ink); font-size: 13px; text-align: center; }
</style>
