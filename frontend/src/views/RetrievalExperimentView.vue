<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  createExperiment,
  getExperiment,
  getExperiments,
  type ExperimentConfig,
  type ExperimentConfigResult,
  type ExperimentDetail,
  type ExperimentStatus,
  type ExperimentSummary,
} from '@/api/experiments'
import { getErrorMessage } from '@/api/http'

const experimentGroups: Array<{ label: string; config: ExperimentConfig }> = [
  { label: 'A', config: { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 } },
  { label: 'B', config: { chunk_size: 400, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 } },
  { label: 'C', config: { chunk_size: 800, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 } },
  { label: 'D', config: { chunk_size: 600, chunk_overlap: 100, top_k: 3, rerank_enabled: false, rerank_top_n: 3, score_threshold: 0.35 } },
  { label: 'E', config: { chunk_size: 600, chunk_overlap: 100, top_k: 8, rerank_enabled: false, rerank_top_n: 8, score_threshold: 0.35 } },
  { label: 'F', config: { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: true, rerank_top_n: 5, score_threshold: 0.35 } },
]

const experiments = ref<ExperimentSummary[]>([])
const page = ref(1)
const pageSize = 10
const total = ref(0)
const pages = ref(0)
const loadingList = ref(false)
const listError = ref('')
const experimentName = ref('')
const answerStyle = ref<'' | 'plain' | 'legal'>('')
const creating = ref(false)
const createError = ref('')
const selectedId = ref<number>()
const detail = ref<ExperimentDetail>()
const loadingDetail = ref(false)
const detailError = ref('')
const expandedConfigIndex = ref<number>()
const detailRequests = new Set<number>()
let selectionVersion = 0
let pollTimer: ReturnType<typeof setInterval> | undefined

const status = computed(() => detail.value?.status ?? experiments.value.find((item) => item.id === selectedId.value)?.status)
const selectedName = computed(() => detail.value?.name ?? experiments.value.find((item) => item.id === selectedId.value)?.name ?? '')
const isTerminal = (value: ExperimentStatus | undefined) => value === 'COMPLETED' || value === 'FAILED'
const configResults = computed(() => new Map((detail.value?.config_results ?? []).map((item) => [item.config_index, item])))
const selectedConfigResults = computed(() => detail.value?.results.filter((item) => item.config_index === expandedConfigIndex.value) ?? [])

function stopPolling() {
  if (pollTimer !== undefined) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function startPolling(id: number) {
  if (pollTimer !== undefined) return
  pollTimer = setInterval(() => {
    if (selectedId.value === id && !detailRequests.has(id)) void loadDetail(id)
  }, 2000)
}

async function loadDetail(id: number, showLoading = false) {
  if (detailRequests.has(id)) return
  const version = selectionVersion
  detailRequests.add(id)
  if (showLoading) loadingDetail.value = true
  detailError.value = ''
  try {
    const result = await getExperiment(id)
    if (version !== selectionVersion || selectedId.value !== id) return
    detail.value = result
    const summary = experiments.value.find((item) => item.id === id)
    if (summary) {
      summary.status = result.status
      summary.progress_current = result.progress_current
      summary.progress_total = result.progress_total
      summary.error_message = result.error_message
    }
    if (isTerminal(result.status)) stopPolling()
    else startPolling(id)
  } catch (error) {
    if (version === selectionVersion && selectedId.value === id) detailError.value = getErrorMessage(error)
  } finally {
    detailRequests.delete(id)
    if (version === selectionVersion && selectedId.value === id && showLoading) loadingDetail.value = false
  }
}

function selectExperiment(item: ExperimentSummary) {
  stopPolling()
  selectionVersion += 1
  selectedId.value = item.id
  detail.value = undefined
  detailError.value = ''
  expandedConfigIndex.value = undefined
  if (!isTerminal(item.status)) startPolling(item.id)
  void loadDetail(item.id, true)
}

async function loadExperiments() {
  loadingList.value = true
  listError.value = ''
  try {
    const result = await getExperiments({ page: page.value, size: pageSize })
    experiments.value = result.items
    total.value = result.total
    pages.value = result.pages
    if (selectedId.value === undefined && result.items.length > 0) {
      const latest = result.items.find((item) => !isTerminal(item.status)) ?? result.items[0]
      selectExperiment(latest)
    }
  } catch (error) {
    listError.value = getErrorMessage(error)
  } finally {
    loadingList.value = false
  }
}

async function submitExperiment() {
  const name = experimentName.value.trim()
  if (!name) {
    createError.value = '请填写实验名称'
    return
  }

  creating.value = true
  createError.value = ''
  try {
    const job = await createExperiment({
      name,
      case_ids: null,
      answer_style: answerStyle.value || 'plain',
      configs: experimentGroups.map((group) => group.config),
    })
    stopPolling()
    selectionVersion += 1
    selectedId.value = job.experiment_id
    detail.value = undefined
    expandedConfigIndex.value = undefined
    if (!isTerminal(job.status)) startPolling(job.experiment_id)
    void loadDetail(job.experiment_id, true)
    await loadExperiments()
  } catch (error) {
    createError.value = getErrorMessage(error)
  } finally {
    creating.value = false
  }
}

function changePage(nextPage: number) {
  page.value = nextPage
  void loadExperiments()
}

function formatStatus(value: ExperimentStatus | undefined) {
  if (value === 'PENDING') return '排队中'
  if (value === 'RUNNING') return '运行中'
  if (value === 'COMPLETED') return '已完成'
  if (value === 'FAILED') return '失败'
  return '加载中'
}

function formatRate(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : (value * 100).toFixed(1) + '%'
}

function formatDuration(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : value.toFixed(1) + ' ms'
}

function formatCreatedAt(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function progressPercent(current: number, total: number) {
  if (total <= 0) return 0
  return Math.min(100, Math.round((current / total) * 100))
}

function statusClass(value: ExperimentStatus | undefined) {
  if (value === 'COMPLETED') return 'experiment-status-completed'
  if (value === 'FAILED') return 'experiment-status-failed'
  if (value === 'RUNNING') return 'experiment-status-running'
  return 'experiment-status-pending'
}

function configResult(index: number): ExperimentConfigResult | undefined {
  return configResults.value.get(index)
}

function configStatus(index: number) {
  const completedCases = detail.value?.results.filter((item) => item.config_index === index).length ?? 0
  const expectedCases = detail.value && detail.value.config_results.length > 0
    ? detail.value.progress_total / detail.value.config_results.length
    : 0
  if (detail.value?.status === 'COMPLETED') return '已完成'
  if (detail.value?.status === 'FAILED') return completedCases ? '部分完成' : '未开始'
  if (expectedCases > 0 && completedCases >= expectedCases) return '已完成'
  return completedCases ? '运行中' : formatStatus(detail.value?.status)
}

function chooseConfig(index: number) {
  expandedConfigIndex.value = expandedConfigIndex.value === index ? undefined : index
}

onMounted(() => void loadExperiments())

onBeforeUnmount(() => {
  stopPolling()
  selectionVersion += 1
})
</script>

<template>
  <section class="experiment-page" aria-labelledby="experiment-title">
    <header class="page-intro documents-page-intro">
      <div>
        <h1 id="experiment-title">检索策略实验</h1>
        <p>使用同一批 60 条评测用例，对比六种固定检索配置及命中结果。</p>
      </div>
      <span class="experiment-count">固定对比 A–F · 共 {{ experimentGroups.length }} 组</span>
    </header>

    <section class="experiment-panel" aria-labelledby="experiment-config-title">
      <div class="experiment-heading">
        <div>
          <h2 id="experiment-config-title">固定实验配置</h2>
          <p>每组 overlap 100 · 阈值 0.35 · 独立构建实验索引</p>
        </div>
      </div>
      <div class="experiment-table-wrap">
        <table class="experiment-table experiment-config-table">
          <thead>
            <tr>
              <th scope="col">组别</th>
              <th scope="col">Chunk Size</th>
              <th scope="col">Overlap</th>
              <th scope="col">Top-k</th>
              <th scope="col">Rerank</th>
              <th scope="col">Rerank Top-N</th>
              <th scope="col">阈值</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="group in experimentGroups" :key="group.label">
              <th scope="row">{{ group.label }}</th>
              <td>{{ group.config.chunk_size }}</td>
              <td>{{ group.config.chunk_overlap }}</td>
              <td>{{ group.config.top_k }}</td>
              <td>{{ group.config.rerank_enabled ? '开启' : '关闭' }}</td>
              <td>{{ group.config.rerank_top_n }}</td>
              <td>{{ group.config.score_threshold.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="experiment-panel experiment-create-panel" aria-labelledby="experiment-create-title">
      <div class="experiment-create-layout">
        <div class="experiment-heading">
          <div>
            <h2 id="experiment-create-title">创建实验</h2>
            <p>每次实验运行全部 60 条用例</p>
          </div>
        </div>
        <form class="experiment-create-form" @submit.prevent="submitExperiment">
          <label>
            <span>实验名称</span>
            <input v-model="experimentName" maxlength="100" required placeholder="例如：检索参数对比-20260915" />
          </label>
          <label>
            <span>回答风格</span>
            <select v-model="answerStyle">
              <option value="">使用默认值</option>
              <option value="plain">通俗版</option>
              <option value="legal">严谨版</option>
            </select>
          </label>
          <button class="experiment-primary" type="submit" :disabled="creating">
            {{ creating ? '创建中…' : '创建实验' }}
          </button>
        </form>
      </div>
      <p v-if="createError" class="experiment-error" role="alert">{{ createError }}</p>
    </section>

    <section class="experiment-panel" aria-labelledby="experiment-list-title">
      <div class="experiment-heading">
        <div>
          <h2 id="experiment-list-title">实验记录</h2>
          <p>选择实验查看进度；运行中的任务每 2 秒更新一次。</p>
        </div>
      </div>
      <p v-if="listError" class="experiment-error" role="alert">{{ listError }}</p>
      <div class="experiment-table-wrap" :aria-busy="loadingList">
        <table class="experiment-table experiment-list-table">
          <thead>
            <tr>
              <th scope="col" class="experiment-select-cell"><span class="sr-only">选择</span></th>
              <th scope="col">实验名称</th>
              <th scope="col">状态</th>
              <th scope="col">进度</th>
              <th scope="col">创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in experiments"
              :key="item.id"
              :class="{ 'experiment-row-selected': item.id === selectedId }"
              @click="selectExperiment(item)"
            >
              <td class="experiment-select-cell">
                <input
                  :aria-label="`选择实验 ${item.name}`"
                  type="radio"
                  name="retrieval-experiment"
                  :checked="item.id === selectedId"
                  @click.stop
                  @change="selectExperiment(item)"
                />
              </td>
              <td><button class="experiment-link" type="button" @click.stop="selectExperiment(item)">{{ item.name }}</button></td>
              <td>
                <span class="experiment-status-inline" :class="statusClass(item.status)">
                  <i aria-hidden="true" />{{ formatStatus(item.status) }}
                </span>
              </td>
              <td>{{ item.progress_current }} / {{ item.progress_total }}</td>
              <td>{{ formatCreatedAt(item.created_at) }}</td>
            </tr>
            <tr v-if="!loadingList && experiments.length === 0">
              <td colspan="5" class="experiment-empty">暂无检索实验</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="experiment-pagination">
        <span>共 {{ total }} 条，第 {{ page }} / {{ pages || 1 }} 页</span>
        <button :disabled="page <= 1 || loadingList" @click="changePage(page - 1)">上一页</button>
        <button :disabled="page >= pages || loadingList" @click="changePage(page + 1)">下一页</button>
      </div>
    </section>

    <section v-if="selectedId !== undefined" class="experiment-panel experiment-detail-panel" aria-labelledby="experiment-detail-title">
      <div class="experiment-heading experiment-detail-heading">
        <div>
          <h2 id="experiment-detail-title">{{ selectedName || '检索实验 #' + selectedId }}</h2>
          <p v-if="detail" class="experiment-signature">
            Embedding 快照：{{ detail.embedding_signature.embedding_provider }} · {{ detail.embedding_signature.embedding_model }} · {{ detail.embedding_signature.embedding_dimension }} 维
          </p>
        </div>
        <span class="experiment-status" :class="statusClass(status)">{{ formatStatus(status) }}</span>
      </div>
      <p v-if="detailError" class="experiment-error" role="alert">{{ detailError }}</p>
      <p v-if="detail?.error_message" class="experiment-error" role="alert">{{ detail.error_message }}</p>
      <p v-if="loadingDetail && !detail" class="experiment-muted">正在读取实验详情…</p>
      <template v-if="detail">
        <div class="experiment-summary-row">
          <div class="experiment-progress" aria-label="实验进度">
            <span>进度</span>
            <progress :value="detail.progress_current" :max="Math.max(detail.progress_total, 1)" />
            <strong>{{ detail.progress_current }} / {{ detail.progress_total }} 题次</strong>
            <span class="experiment-progress-percent">{{ progressPercent(detail.progress_current, detail.progress_total) }}%</span>
          </div>
          <p v-if="detail.best_config_index !== null" class="experiment-best" role="status">
            当前最优配置：<strong>{{ experimentGroups[detail.best_config_index]?.label ?? '#' + detail.best_config_index }}</strong>
          </p>
        </div>
        <p v-if="detail.best_config_index === null && detail.status === 'COMPLETED'" class="experiment-muted">没有可比较的完整配置结果。</p>

        <div class="experiment-table-wrap">
          <table class="experiment-table experiment-results-table">
            <thead>
              <tr>
                <th scope="col">配置</th>
                <th scope="col">Chunk / Top-k / Rerank</th>
                <th scope="col">引用命中率</th>
                <th scope="col">正确率</th>
                <th scope="col">拒答率</th>
                <th scope="col">平均检索耗时</th>
                <th scope="col">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(group, index) in experimentGroups"
                :key="group.label"
                :class="{
                  'experiment-row-selected': index === expandedConfigIndex,
                  'experiment-row-best': index === detail.best_config_index,
                }"
                @click="chooseConfig(index)"
              >
                <th scope="row">
                  <button class="experiment-link" type="button" :aria-expanded="index === expandedConfigIndex" @click.stop="chooseConfig(index)">
                    {{ group.label }}{{ index === detail.best_config_index ? ' · 最优' : '' }}
                  </button>
                </th>
                <td>{{ group.config.chunk_size }} / {{ group.config.top_k }} / {{ group.config.rerank_enabled ? '开启' : '关闭' }}</td>
                <td>{{ formatRate(configResult(index)?.citation_hit_rate) }}</td>
                <td>{{ formatRate(configResult(index)?.accuracy) }}</td>
                <td>{{ formatRate(configResult(index)?.reject_rate) }}</td>
                <td>{{ formatDuration(configResult(index)?.avg_retrieval_ms) }}</td>
                <td>
                  <span class="experiment-status-inline" :class="statusClass(detail.status)">
                    <i aria-hidden="true" />{{ configStatus(index) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="expandedConfigIndex !== undefined" class="experiment-cases">
          <h3>{{ experimentGroups[expandedConfigIndex]?.label }} 组逐题检索结果（{{ selectedConfigResults.length }}）</h3>
          <p class="experiment-muted">以下段号来自该组重新切分后的实验 Chunk，不对应原评测集中的来源段号。</p>
          <p v-if="selectedConfigResults.length === 0" class="experiment-muted">此配置尚无逐题结果。</p>
          <details v-for="(result, resultIndex) in selectedConfigResults" :key="result.case_id" class="experiment-case" :open="resultIndex === 0">
            <summary class="experiment-case-summary">
              <span class="experiment-case-chevron" aria-hidden="true">⌄</span>
              <strong>{{ experimentGroups[expandedConfigIndex]?.label }} 组逐题结果</strong>
              <span>（{{ selectedConfigResults.length }}）</span>
              <span>· 用例 #{{ result.case_id }}</span>
              <span>· 引用命中：<b>{{ result.source_hit === null ? '—' : result.source_hit ? '是' : '否' }}</b></span>
              <span>· 正确：<b>{{ result.correct === null ? '—' : result.correct ? '是' : '否' }}</b></span>
            </summary>
            <div class="experiment-case-body">
              <div class="experiment-case-heading">
                <span :class="result.status === 'FAILED' ? 'experiment-failed' : 'experiment-completed'">{{ result.status === 'FAILED' ? '单题失败' : '已完成' }}</span>
                <span>拒答：{{ result.refused === null ? '—' : result.refused ? '是' : '否' }}</span>
                <span>{{ formatDuration(result.retrieval_ms) }}</span>
              </div>
              <p v-if="result.error_message" class="experiment-error">{{ result.error_message }}</p>
              <p v-if="result.retrieved_sources.length === 0" class="experiment-muted">没有命中来源。</p>
              <ul v-else class="experiment-sources">
                <li v-for="source in result.retrieved_sources" :key="source.chunk_id">
                  <strong>{{ source.file_name }} · 实验分块第 {{ source.chunk_no }} 段</strong>
                  <span>排序 {{ source.rank_no }} · 检索分 {{ source.retrieval_score.toFixed(3) }}<template v-if="source.rerank_score !== null"> · 重排分 {{ source.rerank_score.toFixed(3) }}</template></span>
                  <p>{{ source.content }}</p>
                </li>
              </ul>
            </div>
          </details>
        </div>
      </template>
    </section>
  </section>
</template>

<style scoped>
.experiment-page {
  display: grid;
  width: min(100%, 1100px);
  margin: 0 auto;
  gap: 12px;
  color: #263548;
}

.experiment-count {
  padding: 8px 15px;
  color: #185b44;
  background: #f0f7f4;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
}

.experiment-panel {
  min-width: 0;
  padding: 14px 14px 12px;
  background: #fff;
  border: 1px solid #e1e9e4;
  border-radius: 9px;
}

.experiment-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 11px;
}

.experiment-heading h2 {
  margin: 0;
  color: #20352d;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
}

.experiment-heading p {
  margin: 5px 0 0;
  color: #758195;
  font-size: 12px;
  line-height: 1.45;
}

.experiment-table-wrap {
  margin-top: 10px;
  overflow-x: auto;
}

.experiment-table {
  width: 100%;
  min-width: 900px;
  border-spacing: 0;
  text-align: left;
}

.experiment-table th,
.experiment-table td {
  padding: 7px 10px;
  border-bottom: 1px solid #edf0f1;
  vertical-align: middle;
}

.experiment-table th {
  color: #68758a;
  background: #f4f6f5;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.35;
  white-space: nowrap;
}

.experiment-table th:first-child {
  border-radius: 6px 0 0 6px;
}

.experiment-table th:last-child {
  border-radius: 0 6px 6px 0;
}

.experiment-table td {
  color: #354257;
  font-size: 12px;
  line-height: 1.45;
}

.experiment-config-table {
  table-layout: fixed;
  text-align: center;
}

.experiment-config-table th,
.experiment-config-table td {
  text-align: center;
}

.experiment-config-table th:first-child,
.experiment-config-table td:first-child { width: 9%; }
.experiment-config-table th:nth-child(2),
.experiment-config-table td:nth-child(2) { width: 17%; }
.experiment-config-table th:nth-child(3),
.experiment-config-table td:nth-child(3) { width: 15%; }
.experiment-config-table th:nth-child(4),
.experiment-config-table td:nth-child(4) { width: 15%; }
.experiment-config-table th:nth-child(5),
.experiment-config-table td:nth-child(5) { width: 15%; }
.experiment-config-table th:nth-child(6),
.experiment-config-table td:nth-child(6) { width: 17%; }
.experiment-config-table th:nth-child(7),
.experiment-config-table td:nth-child(7) { width: 12%; }

.experiment-config-table tbody th {
  color: #354257;
  background: #fff;
  font-size: 12px;
}

.experiment-primary {
  min-height: 38px;
  padding: 0 16px;
  color: #fff;
  background: #126047;
  border: 1px solid #126047;
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.experiment-primary:hover:not(:disabled) {
  background: #0f523c;
  border-color: #0f523c;
}

.experiment-primary:disabled {
  cursor: wait;
  opacity: 0.65;
}

.experiment-create-layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  align-items: center;
  gap: 14px;
}

.experiment-create-layout .experiment-heading {
  margin: 0;
}

.experiment-create-form {
  display: grid;
  grid-template-columns: minmax(190px, 1fr) minmax(150px, 180px) 126px;
  align-items: center;
  gap: 10px;
}

.experiment-create-form label {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: #758195;
  font-size: 12px;
  white-space: nowrap;
}

.experiment-create-form input,
.experiment-create-form select {
  width: 100%;
  min-width: 0;
  min-height: 38px;
  padding: 0 10px;
  color: #354257;
  background: #fff;
  border: 1px solid #d8e0da;
  border-radius: 7px;
  outline: 0;
  font: inherit;
}

.experiment-create-form input::placeholder {
  color: #a0a9b5;
}

.experiment-list-table {
  min-width: 700px;
  table-layout: fixed;
}

.experiment-list-table th:nth-child(1),
.experiment-list-table td:nth-child(1) { width: 42px; }
.experiment-list-table th:nth-child(2),
.experiment-list-table td:nth-child(2) { width: 42%; }
.experiment-list-table th:nth-child(3),
.experiment-list-table td:nth-child(3) { width: 18%; }
.experiment-list-table th:nth-child(4),
.experiment-list-table td:nth-child(4) { width: 18%; }
.experiment-list-table th:nth-child(5),
.experiment-list-table td:nth-child(5) { width: 22%; }

.experiment-select-cell {
  text-align: center;
}

.experiment-table input[type='radio'] {
  width: 17px;
  height: 17px;
  margin: 0;
  accent-color: #146348;
  cursor: pointer;
}

.experiment-list-table tbody tr {
  cursor: pointer;
}

.experiment-list-table tbody tr:hover,
.experiment-row-selected {
  background: #f0f7f4;
}

.experiment-link {
  padding: 0;
  color: #185b44;
  background: none;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-weight: 650;
  text-align: left;
}

.experiment-status-inline {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}

.experiment-status-inline i {
  display: block;
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}

.experiment-status-completed,
.experiment-completed { color: #168052; }
.experiment-status-running { color: #3175d6; }
.experiment-status-pending { color: #a47b22; }
.experiment-status-failed,
.experiment-failed { color: #c45656; }

.experiment-status {
  padding-top: 4px;
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
}

.experiment-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 10px;
  color: #758195;
  font-size: 12px;
}

.experiment-pagination button {
  min-height: 30px;
  padding: 0 11px;
  color: #536077;
  background: #fff;
  border: 1px solid #d8e0da;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}

.experiment-pagination button:hover:not(:disabled) {
  color: #185b44;
  border-color: #a9c8b9;
}

.experiment-pagination button:disabled {
  color: #b4bbc5;
  cursor: default;
}

.experiment-detail-panel {
  padding-top: 16px;
}

.experiment-detail-heading {
  align-items: flex-start;
}

.experiment-signature,
.experiment-muted {
  margin: 5px 0 0;
  color: #8a95a5;
  font-size: 12px;
  line-height: 1.6;
}

.experiment-summary-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  padding: 9px 0 12px;
  border-bottom: 1px solid #e7ece9;
}

.experiment-progress {
  display: grid;
  grid-template-columns: auto minmax(120px, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: #758195;
  font-size: 12px;
}

.experiment-progress progress {
  width: 100%;
  min-width: 90px;
  height: 9px;
  accent-color: #126047;
}

.experiment-progress strong {
  color: #354257;
  font-weight: 500;
  white-space: nowrap;
}

.experiment-progress-percent {
  color: #718096;
  white-space: nowrap;
}

.experiment-best {
  margin: 0;
  padding: 8px 13px;
  color: #26705d;
  background: #f0f7f4;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.experiment-best strong {
  color: #155a42;
  font-size: 14px;
}

.experiment-results-table {
  min-width: 900px;
  table-layout: fixed;
}

.experiment-results-table th:nth-child(1),
.experiment-results-table td:nth-child(1) { width: 11%; }
.experiment-results-table th:nth-child(2),
.experiment-results-table td:nth-child(2) { width: 22%; }
.experiment-results-table th:nth-child(3),
.experiment-results-table td:nth-child(3) { width: 14%; }
.experiment-results-table th:nth-child(4),
.experiment-results-table td:nth-child(4) { width: 12%; }
.experiment-results-table th:nth-child(5),
.experiment-results-table td:nth-child(5) { width: 12%; }
.experiment-results-table th:nth-child(6),
.experiment-results-table td:nth-child(6) { width: 17%; }
.experiment-results-table th:nth-child(7),
.experiment-results-table td:nth-child(7) { width: 12%; }

.experiment-results-table tbody tr {
  cursor: pointer;
}

.experiment-results-table tbody tr:hover,
.experiment-results-table tbody tr.experiment-row-selected,
.experiment-results-table tbody tr.experiment-row-best {
  background: #f0f7f4;
}

.experiment-results-table tbody tr.experiment-row-selected.experiment-row-best {
  background: #e8f3ed;
}

.experiment-cases {
  margin-top: 17px;
}

.experiment-cases h3 {
  margin: 0 0 7px;
  color: #20352d;
  font-size: 15px;
}

.experiment-case {
  margin-top: 8px;
  border: 1px solid #e0e8e3;
  border-radius: 7px;
  overflow: hidden;
}

.experiment-case-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px;
  color: #536077;
  cursor: pointer;
  font-size: 12px;
  list-style: none;
}

.experiment-case-summary::-webkit-details-marker {
  display: none;
}

.experiment-case-summary strong {
  color: #354257;
}

.experiment-case-summary b {
  color: #168052;
  font-weight: 650;
}

.experiment-case-chevron {
  color: #185b44;
  font-size: 18px;
  line-height: 0.7;
  transition: transform 0.15s ease;
}

.experiment-case:not([open]) .experiment-case-chevron {
  transform: rotate(-90deg);
}

.experiment-case-body {
  display: grid;
  gap: 9px;
  padding: 0 12px 12px;
  border-top: 1px solid #edf0f1;
}

.experiment-case-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px 12px;
  padding-top: 9px;
  color: #667286;
  font-size: 12px;
}

.experiment-sources {
  display: grid;
  gap: 10px;
  margin: 0;
  padding-left: 18px;
  color: #4e5a6b;
  font-size: 12px;
}

.experiment-sources li {
  display: grid;
  gap: 4px;
}

.experiment-sources li > span {
  color: #758195;
  font-size: 11px;
}

.experiment-sources p {
  margin: 0;
  line-height: 1.6;
  white-space: pre-wrap;
}

.experiment-error {
  margin: 9px 0;
  padding: 8px 10px;
  color: #a63c3c;
  background: #fff4f2;
  border: 1px solid #f0d5d1;
  border-radius: 7px;
  font-size: 12px;
  line-height: 1.5;
}

.experiment-empty {
  padding: 24px !important;
  color: #8a95a5 !important;
  text-align: center;
}

@media (max-width: 820px) {
  .experiment-create-layout {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .experiment-create-form {
    grid-template-columns: minmax(180px, 1fr) minmax(140px, 1fr) 112px;
  }

  .experiment-summary-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .experiment-best {
    justify-self: start;
  }
}

@media (max-width: 620px) {
  .experiment-page {
    width: 100%;
    gap: 10px;
  }

  .experiment-count {
    padding: 7px 12px;
    font-size: 12px;
  }

  .experiment-panel {
    padding: 12px 10px 10px;
  }

  .experiment-create-form {
    grid-template-columns: 1fr;
  }

  .experiment-create-form label {
    align-items: stretch;
    flex-direction: column;
    gap: 5px;
    white-space: normal;
  }

  .experiment-create-form .experiment-primary {
    width: 100%;
  }

  .experiment-progress {
    grid-template-columns: auto 1fr auto;
  }

  .experiment-progress progress {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .experiment-progress strong {
    grid-column: 2;
  }

  .experiment-progress-percent {
    grid-column: 3;
    grid-row: 1;
  }
}
</style>
