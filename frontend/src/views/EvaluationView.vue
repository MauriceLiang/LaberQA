<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElButton, ElInput, ElOption, ElSelect } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

import {
  createEvaluationRun,
  getEvaluationCases,
  getEvaluationRun,
  getEvaluationRuns,
  type EvaluationAnswerStyle,
  type EvaluationCase,
  type EvaluationExpectedType,
  type EvaluationJobStatus,
  type EvaluationRunDetail,
  type EvaluationRunSummary,
} from '@/api/evaluations'
import { getErrorMessage } from '@/api/http'
import MarkdownContent from '@/components/chat/MarkdownContent.vue'

const cases = ref<EvaluationCase[]>([])
const casePage = ref(1)
const caseSize = ref(20)
const caseTotal = ref(0)
const casePages = ref(0)
const topicInput = ref('')
const topicFilter = ref('')
const expectedTypeFilter = ref<EvaluationExpectedType | ''>('')
const multiTurnFilter = ref<'' | 'true' | 'false'>('')
const selectedCaseIds = ref(new Set<number>())
const loadingCases = ref(false)
const casesError = ref('')
let caseRequestId = 0

const runs = ref<EvaluationRunSummary[]>([])
const runPage = ref(1)
const runSize = 10
const runTotal = ref(0)
const runPages = ref(0)
const loadingRuns = ref(false)
const runsError = ref('')
const runName = ref('')
const answerStyle = ref<EvaluationAnswerStyle>('plain')
const creatingRun = ref(false)
const createError = ref('')
const selectedRunId = ref<number>()
const runDetail = ref<EvaluationRunDetail>()
const loadingDetail = ref(false)
const detailError = ref('')
const detailRequestIds = new Set<number>()
let selectedRunVersion = 0
let pollTimer: ReturnType<typeof setInterval> | undefined

const selectedPageFully = computed(
  () => cases.value.length > 0 && cases.value.every((item) => selectedCaseIds.value.has(item.id)),
)
const selectedRunSummary = computed(() => runs.value.find((run) => run.id === selectedRunId.value))
const displayedRunName = computed(
  () => runDetail.value?.name ?? selectedRunSummary.value?.name ?? `评测批次 #${selectedRunId.value ?? ''}`,
)
const displayedStatus = computed(
  () => runDetail.value?.status ?? selectedRunSummary.value?.status,
)
const hasUnavailableMetrics = computed(() => {
  const metrics = runDetail.value?.metrics
  return metrics !== null
    && metrics !== undefined
    && Object.values(metrics).some((value) => value === null)
})
const terminalStatus = (status: EvaluationJobStatus | undefined) =>
  status === 'COMPLETED' || status === 'FAILED'

async function loadCases() {
  const requestId = ++caseRequestId
  loadingCases.value = true
  casesError.value = ''
  try {
    const result = await getEvaluationCases({
      page: casePage.value,
      size: caseSize.value,
      topic: topicFilter.value || undefined,
      expected_type: expectedTypeFilter.value || undefined,
      is_multi_turn: multiTurnFilter.value === '' ? undefined : multiTurnFilter.value === 'true',
    })
    if (requestId !== caseRequestId) return
    cases.value = result.items
    caseTotal.value = result.total
    casePages.value = result.pages
  } catch (error) {
    if (requestId === caseRequestId) casesError.value = getErrorMessage(error)
  } finally {
    if (requestId === caseRequestId) loadingCases.value = false
  }
}

function applyCaseFilters() {
  topicFilter.value = topicInput.value.trim()
  casePage.value = 1
  void loadCases()
}

function changeCasePage(nextPage: number) {
  casePage.value = nextPage
  void loadCases()
}

function changeCaseSize(nextSize: number) {
  caseSize.value = nextSize
  casePage.value = 1
  void loadCases()
}

function toggleCase(id: number, checked: boolean) {
  const next = new Set(selectedCaseIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedCaseIds.value = next
}

function toggleCurrentPage() {
  const next = new Set(selectedCaseIds.value)
  if (selectedPageFully.value) cases.value.forEach((item) => next.delete(item.id))
  else cases.value.forEach((item) => next.add(item.id))
  selectedCaseIds.value = next
}

async function loadRuns() {
  loadingRuns.value = true
  runsError.value = ''
  try {
    const result = await getEvaluationRuns({ page: runPage.value, size: runSize })
    runs.value = result.items
    runTotal.value = result.total
    runPages.value = result.pages
    if (selectedRunId.value === undefined && result.items.length) {
      const latest = result.items.find((item) => !terminalStatus(item.status)) ?? result.items[0]
      selectRun(latest)
    }
  } catch (error) {
    runsError.value = getErrorMessage(error)
  } finally {
    loadingRuns.value = false
  }
}

function stopPolling() {
  if (pollTimer !== undefined) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function startPolling(id: number) {
  if (pollTimer !== undefined) return
  pollTimer = setInterval(() => {
    if (!detailRequestIds.has(id) && selectedRunId.value === id) void loadRunDetail(id)
  }, 2000)
}

async function loadRunDetail(id: number, showLoading = false) {
  if (detailRequestIds.has(id)) return
  const version = selectedRunVersion
  detailRequestIds.add(id)
  if (showLoading) loadingDetail.value = true
  detailError.value = ''
  try {
    const result = await getEvaluationRun(id)
    if (version !== selectedRunVersion || selectedRunId.value !== id) return
    runDetail.value = result
    if (terminalStatus(result.status)) stopPolling()
    else startPolling(id)
  } catch (error) {
    if (version === selectedRunVersion && selectedRunId.value === id) detailError.value = getErrorMessage(error)
  } finally {
    detailRequestIds.delete(id)
    if (version === selectedRunVersion && selectedRunId.value === id && showLoading) {
      loadingDetail.value = false
    }
  }
}

function selectRun(run: EvaluationRunSummary) {
  stopPolling()
  selectedRunVersion += 1
  selectedRunId.value = run.id
  runDetail.value = undefined
  detailError.value = ''
  if (!terminalStatus(run.status)) startPolling(run.id)
  void loadRunDetail(run.id, true)
}

async function createRun() {
  const name = runName.value.trim()
  if (!name) {
    createError.value = '请填写评测批次名称'
    return
  }

  creatingRun.value = true
  createError.value = ''
  try {
    const job = await createEvaluationRun({
      name,
      case_ids: selectedCaseIds.value.size ? [...selectedCaseIds.value].sort((a, b) => a - b) : null,
      answer_style: answerStyle.value,
    })
    stopPolling()
    selectedRunVersion += 1
    selectedRunId.value = job.run_id
    runDetail.value = undefined
    detailError.value = ''
    if (!terminalStatus(job.status)) startPolling(job.run_id)
    void loadRunDetail(job.run_id, true)
    await loadRuns()
  } catch (error) {
    createError.value = getErrorMessage(error)
  } finally {
    creatingRun.value = false
  }
}

function changeRunPage(nextPage: number) {
  runPage.value = nextPage
  void loadRuns()
}

function formatStatus(status: EvaluationJobStatus | undefined) {
  if (status === 'PENDING') return '排队中'
  if (status === 'RUNNING') return '运行中'
  if (status === 'COMPLETED') return '已完成'
  if (status === 'FAILED') return '失败'
  return '加载中'
}

function formatRate(value: number | null | undefined) {
  return value === null || value === undefined ? '不适用' : `${(value * 100).toFixed(1)}%`
}

function formatFlag(value: boolean | null) {
  return value === null ? '不适用' : value ? '是' : '否'
}

function formatCaseId(id: number) {
  return `#${String(id).padStart(3, '0')}`
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

function statusClass(status: EvaluationJobStatus | undefined) {
  if (status === 'COMPLETED') return 'evaluation-status-completed'
  if (status === 'FAILED') return 'evaluation-status-failed'
  if (status === 'RUNNING') return 'evaluation-status-running'
  return 'evaluation-status-pending'
}

onMounted(() => {
  void loadCases()
  void loadRuns()
})

onBeforeUnmount(() => {
  stopPolling()
  caseRequestId += 1
  selectedRunVersion += 1
})
</script>

<template>
  <section class="evaluation-page" aria-labelledby="evaluation-title">
    <header class="page-intro documents-page-intro">
      <div>
        <h1 id="evaluation-title">问答测评</h1>
        <p>筛选评测用例，创建后台评测批次，并查看运行结果。</p>
      </div>
      <div class="evaluation-count" aria-label="已选择的评测用例数量">
        <span>已选</span>
        <strong>{{ selectedCaseIds.size }}</strong>
        <span>条用例</span>
      </div>
    </header>

    <section class="evaluation-panel" aria-labelledby="evaluation-cases-title">
      <div class="evaluation-section-heading">
        <div>
          <h2 id="evaluation-cases-title">评测用例</h2>
          <p>不选择用例时，将执行全部 60 条</p>
        </div>
      </div>
      <p v-if="casesError" class="evaluation-error" role="alert">{{ casesError }}</p>
      <form class="evaluation-filters" @submit.prevent="applyCaseFilters">
        <label class="evaluation-filter-control evaluation-filter-search">
          <span class="sr-only">搜索主题或问题</span>
          <ElInput
            v-model="topicInput"
            class="evaluation-filter-input"
            type="search"
            placeholder="搜索主题或问题关键词"
            aria-label="搜索主题或问题"
          >
            <template #prefix><Search aria-hidden="true" /></template>
          </ElInput>
        </label>
        <label class="evaluation-filter-control">
          <span class="sr-only">预期类型</span>
          <ElSelect v-model="expectedTypeFilter" class="evaluation-filter-select" aria-label="预期类型" placeholder="预期类型">
            <ElOption label="应回答" value="ANSWER" />
            <ElOption label="应拒答" value="REJECT" />
          </ElSelect>
        </label>
        <label class="evaluation-filter-control">
          <span class="sr-only">对话轮数</span>
          <ElSelect v-model="multiTurnFilter" class="evaluation-filter-select" aria-label="对话轮数" placeholder="对话轮数">
            <ElOption label="单轮" value="false" />
            <ElOption label="多轮" value="true" />
          </ElSelect>
        </label>
        <ElButton type="primary" native-type="submit" class="evaluation-primary">筛选</ElButton>
      </form>

      <div class="evaluation-table-wrap" :aria-busy="loadingCases">
        <table class="evaluation-table evaluation-case-table">
          <thead>
            <tr>
              <th scope="col" class="evaluation-select-cell">
                <input aria-label="选择本页全部用例" type="checkbox" :checked="selectedPageFully" @change="toggleCurrentPage" />
              </th>
              <th scope="col">ID</th>
              <th scope="col">主题</th>
              <th scope="col">问题</th>
              <th scope="col">问题轮次</th>
              <th scope="col">预期</th>
              <th scope="col">多轮</th>
              <th scope="col">合规提示</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in cases" :key="item.id">
              <td class="evaluation-select-cell">
                <input :aria-label="`选择用例 ${item.id}`" type="checkbox" :checked="selectedCaseIds.has(item.id)" @change="toggleCase(item.id, ($event.target as HTMLInputElement).checked)" />
              </td>
              <td class="evaluation-case-id">{{ formatCaseId(item.id) }}</td>
              <td class="evaluation-case-topic">{{ item.topic }}</td>
              <td class="evaluation-case-question">{{ item.turns.join(' / ') }}</td>
              <td class="evaluation-case-rounds">{{ item.turns.length }}</td>
              <td>{{ item.expected_type === 'ANSWER' ? '应回答' : '应拒答' }}</td>
              <td>{{ item.turns.length > 1 ? '是' : '否' }}</td>
              <td>{{ item.should_show_compliance ? '需要' : '不需要' }}</td>
            </tr>
            <tr v-if="!loadingCases && cases.length === 0">
              <td colspan="8" class="evaluation-empty">暂无符合条件的用例</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="evaluation-pagination">
        <span>共 {{ caseTotal }} 条，第 {{ casePage }} / {{ casePages || 1 }} 页</span>
        <label>
          每页
          <ElSelect
            :model-value="caseSize"
            class="evaluation-page-size"
            aria-label="每页条数"
            @update:model-value="changeCaseSize"
          >
            <ElOption :value="10" label="10" />
            <ElOption :value="20" label="20" />
            <ElOption :value="50" label="50" />
          </ElSelect>
        </label>
        <ElButton native-type="button" :disabled="casePage <= 1 || loadingCases" @click="changeCasePage(casePage - 1)">上一页</ElButton>
        <ElButton native-type="button" :disabled="casePage >= casePages || loadingCases" @click="changeCasePage(casePage + 1)">下一页</ElButton>
      </div>
    </section>

    <section class="evaluation-panel evaluation-create-panel" aria-labelledby="evaluation-create-title">
      <div class="evaluation-create-layout">
        <div class="evaluation-section-heading">
          <div>
            <h2 id="evaluation-create-title">创建评测批次</h2>
            <p>不选用例将运行全部 60 条；仅运行部分用例时，缺少对应类型的指标不适用</p>
          </div>
        </div>
        <form class="evaluation-create-form" @submit.prevent="createRun">
          <label>
            <span>批次名称</span>
            <ElInput
              v-model="runName"
              class="evaluation-create-input"
              maxlength="100"
              placeholder="例如：正式评测-20260915"
              aria-label="批次名称"
            />
          </label>
          <label>
            <span>回答风格</span>
            <ElSelect v-model="answerStyle" class="evaluation-create-select" aria-label="回答风格">
              <ElOption label="通俗版" value="plain" />
              <ElOption label="严谨版" value="legal" />
            </ElSelect>
          </label>
          <ElButton class="evaluation-primary" type="primary" native-type="submit" :loading="creatingRun" :disabled="creatingRun">
            {{ creatingRun ? '创建中…' : '创建批次' }}
          </ElButton>
        </form>
      </div>
      <p v-if="createError" class="evaluation-error" role="alert">{{ createError }}</p>
    </section>

    <section class="evaluation-panel" aria-labelledby="evaluation-runs-title">
      <div class="evaluation-section-heading">
        <div>
          <h2 id="evaluation-runs-title">评测批次</h2>
          <p>选择批次查看进度；运行中的任务每 2 秒更新一次。</p>
        </div>
      </div>
      <p v-if="runsError" class="evaluation-error" role="alert">{{ runsError }}</p>
      <p v-if="detailError" class="evaluation-error" role="alert">{{ detailError }}</p>
      <div class="evaluation-table-wrap" :aria-busy="loadingRuns">
        <table class="evaluation-table evaluation-run-table">
          <thead>
            <tr>
              <th scope="col" class="evaluation-select-cell"><span class="sr-only">选择</span></th>
              <th scope="col">批次</th>
              <th scope="col">状态</th>
              <th scope="col">进度</th>
              <th scope="col">创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in runs"
              :key="run.id"
              :class="{ 'evaluation-run-selected': run.id === selectedRunId }"
              @click="selectRun(run)"
            >
              <td class="evaluation-select-cell">
                <input
                  :aria-label="`选择评测批次 ${run.name}`"
                  type="radio"
                  name="evaluation-run"
                  :checked="run.id === selectedRunId"
                  @click.stop
                  @change="selectRun(run)"
                />
              </td>
              <td><button class="evaluation-link" type="button" @click.stop="selectRun(run)">{{ run.name }}</button></td>
              <td>
                <span class="evaluation-status-inline" :class="statusClass(run.status)">
                  <i aria-hidden="true" />{{ formatStatus(run.status) }}
                </span>
              </td>
              <td>{{ run.progress_current }} / {{ run.progress_total }}</td>
              <td>{{ formatCreatedAt(run.created_at) }}</td>
            </tr>
            <tr v-if="!loadingRuns && runs.length === 0">
              <td colspan="5" class="evaluation-empty">暂无评测批次</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="evaluation-pagination">
        <span>共 {{ runTotal }} 条，第 {{ runPage }} / {{ runPages || 1 }} 页</span>
        <ElButton native-type="button" :disabled="runPage <= 1 || loadingRuns" @click="changeRunPage(runPage - 1)">上一页</ElButton>
        <ElButton native-type="button" :disabled="runPage >= runPages || loadingRuns" @click="changeRunPage(runPage + 1)">下一页</ElButton>
      </div>
    </section>

    <section v-if="selectedRunId !== undefined" class="evaluation-panel evaluation-detail-panel" aria-labelledby="evaluation-detail-title">
      <div class="evaluation-section-heading evaluation-detail-heading">
        <div>
          <h2 id="evaluation-detail-title">批次运行结果</h2>
          <p class="evaluation-detail-run-name">{{ displayedRunName }}</p>
        </div>
        <span class="evaluation-status" :class="statusClass(displayedStatus)">{{ formatStatus(displayedStatus) }}</span>
      </div>
      <p v-if="runDetail?.error_message" class="evaluation-error" role="alert">{{ runDetail.error_message }}</p>
      <p v-if="loadingDetail && !runDetail" class="evaluation-muted">正在读取评测详情…</p>
      <template v-if="runDetail">
        <div class="evaluation-progress" aria-label="评测进度">
          <div class="evaluation-progress-status">
            <span>状态</span>
            <span class="evaluation-status-inline" :class="statusClass(runDetail.status)">
              <i aria-hidden="true" />{{ formatStatus(runDetail.status) }}
            </span>
          </div>
          <div class="evaluation-progress-track">
            <span>进度</span>
            <strong>{{ runDetail.progress_current }} / {{ runDetail.progress_total }} 题</strong>
            <progress :value="runDetail.progress_current" :max="Math.max(runDetail.progress_total, 1)" />
          </div>
          <span class="evaluation-progress-percent">{{ progressPercent(runDetail.progress_current, runDetail.progress_total) }}%</span>
        </div>
        <div v-if="runDetail.metrics" class="evaluation-metrics" aria-label="评测指标">
          <div><span>回答正确率</span><strong>{{ formatRate(runDetail.metrics.accuracy) }}</strong></div>
          <div><span>拒答率</span><strong>{{ formatRate(runDetail.metrics.reject_rate) }}</strong></div>
          <div><span>引用命中率</span><strong>{{ formatRate(runDetail.metrics.citation_hit_rate) }}</strong></div>
          <div><span>多轮通过率</span><strong>{{ formatRate(runDetail.metrics.multi_turn_pass_rate) }}</strong></div>
          <div><span>合规提示命中率</span><strong>{{ formatRate(runDetail.metrics.compliance_hit_rate) }}</strong></div>
        </div>
        <p v-if="hasUnavailableMetrics" class="evaluation-metric-note">
          “不适用”表示本批次没有包含该指标所需的用例；运行全部 60 条可生成完整指标。
        </p>
        <div v-else-if="terminalStatus(runDetail.status)" class="evaluation-muted">此批次没有可计算的指标。</div>

        <div class="evaluation-results">
          <h3>逐题结果（{{ runDetail.results.length }}）</h3>
          <div v-if="runDetail.results.length === 0" class="evaluation-muted">任务完成后会显示逐题回答、引用与判定。</div>
          <article v-for="result in runDetail.results" :key="result.case_id" class="evaluation-result">
            <div class="evaluation-result-heading">
              <span class="evaluation-result-chevron" aria-hidden="true">›</span>
              <strong>用例 #{{ result.case_id }}</strong>
              <span>·</span>
              <span :class="result.status === 'FAILED' ? 'evaluation-failed' : 'evaluation-completed'">
                {{ result.status === 'FAILED' ? '单题失败' : '已评估' }}
              </span>
              <span v-if="result.latency_ms !== null">· {{ result.latency_ms }} ms</span>
            </div>
            <p v-if="result.error_message" class="evaluation-error">{{ result.error_message }}</p>
            <MarkdownContent
              v-if="result.answer"
              class="evaluation-answer"
              :content="result.answer"
            />
            <div class="evaluation-result-flags">
              <span>正确：<b>{{ formatFlag(result.correct) }}</b></span>
              <span>拒答：<b>{{ formatFlag(result.refused) }}</b></span>
              <span>引用命中：<b>{{ formatFlag(result.source_hit) }}</b></span>
              <span>多轮通过：<b>{{ formatFlag(result.multi_turn_correct) }}</b></span>
              <span>合规提示：<b>{{ formatFlag(result.compliance_hit) }}</b></span>
            </div>
            <details v-if="result.citations.length" class="evaluation-citations">
              <summary>引用来源（{{ result.citations.length }}）</summary>
              <ul>
                <li v-for="citation in result.citations" :key="citation.chunk_id">
                  {{ citation.file_name }} · 第 {{ citation.chunk_no }} 段
                  <span>{{ citation.content }}</span>
                </li>
              </ul>
            </details>
          </article>
        </div>
      </template>
    </section>
  </section>
</template>

<style scoped>
.evaluation-page {
  display: grid;
  width: min(100%, 1100px);
  margin: 0 auto;
  gap: 12px;
  color: #263548;
}

.evaluation-count {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding-bottom: 5px;
  color: #526079;
  font-size: 18px;
  white-space: nowrap;
}

.evaluation-count strong {
  color: #155a42;
  font-size: 34px;
  line-height: 1;
}

.evaluation-panel {
  min-width: 0;
  padding: 14px 14px 12px;
  background: #fff;
  border: 1px solid #e1e9e4;
  border-radius: 9px;
}

.evaluation-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 11px;
}

.evaluation-section-heading h2 {
  margin: 0;
  color: #20352d;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
}

.evaluation-section-heading p,
.evaluation-detail-run-name {
  margin: 5px 0 0;
  color: #758195;
  font-size: 12px;
  line-height: 1.45;
}

.evaluation-filters {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 180px 180px 90px;
  gap: 10px;
}

.evaluation-filter-control {
  display: flex;
  min-width: 0;
  min-height: 38px;
  align-items: center;
  gap: 8px;
  padding: 0 11px;
  color: #667286;
  background: #fff;
  border: 1px solid #d8e0da;
  border-radius: 7px;
  font-size: 12px;
}

.evaluation-filter-control svg {
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  color: #34455d;
}

.evaluation-filter-control input,
.evaluation-filter-control select {
  width: 100%;
  min-width: 0;
  min-height: 36px;
  padding: 0;
  color: #354257;
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
}

.evaluation-filter-control input::placeholder {
  color: #9aa5b4;
}

.evaluation-filter-input,
.evaluation-filter-select {
  width: 100%;
  min-width: 0;
}

.evaluation-filter-input :deep(.el-input__wrapper),
.evaluation-filter-select :deep(.el-select__wrapper) {
  min-height: 36px;
  padding: 0;
  background: transparent;
  border: 0;
  box-shadow: none;
  font: inherit;
}

.evaluation-filter-input :deep(.el-input__inner),
.evaluation-filter-select :deep(.el-select__placeholder),
.evaluation-filter-select :deep(.el-select__selected-item) {
  color: #354257;
  font: inherit;
}

.evaluation-filter-input :deep(.el-input__inner::placeholder) {
  color: #9aa5b4;
}

/* Keep the select's hover state visually aligned with the surrounding filter control. */
.evaluation-filter-select:hover :deep(.el-select__wrapper),
.evaluation-filter-select :deep(.el-select__wrapper:hover) {
  border-color: transparent;
  box-shadow: none !important;
}

.evaluation-filter-input :deep(.el-input__prefix-inner) {
  color: #34455d;
}

.evaluation-primary {
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

.evaluation-primary.el-button {
  height: 38px;
  box-shadow: none;
}

.evaluation-primary:hover:not(:disabled) {
  background: #0f523c;
  border-color: #0f523c;
}

.evaluation-primary:disabled {
  cursor: wait;
  opacity: 0.65;
}

.evaluation-table-wrap {
  margin-top: 10px;
  overflow-x: auto;
}

.evaluation-table {
  width: 100%;
  min-width: 900px;
  border-spacing: 0;
  text-align: left;
}

.evaluation-table th,
.evaluation-table td {
  padding: 9px 10px;
  border-bottom: 1px solid #edf0f1;
  vertical-align: middle;
}

.evaluation-table th {
  color: #68758a;
  background: #f4f6f5;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.35;
  white-space: nowrap;
}

.evaluation-table th:first-child {
  border-radius: 6px 0 0 6px;
}

.evaluation-table th:last-child {
  border-radius: 0 6px 6px 0;
}

.evaluation-table td {
  color: #354257;
  font-size: 12px;
  line-height: 1.45;
}

.evaluation-case-table th:nth-child(1),
.evaluation-case-table td:nth-child(1) { width: 42px; }
.evaluation-case-table th:nth-child(2),
.evaluation-case-table td:nth-child(2) { width: 58px; }
.evaluation-case-table th:nth-child(3),
.evaluation-case-table td:nth-child(3) { width: 150px; }
.evaluation-case-table th:nth-child(4),
.evaluation-case-table td:nth-child(4) { width: 27%; }
.evaluation-case-table th:nth-child(5),
.evaluation-case-table td:nth-child(5) { width: 72px; }
.evaluation-case-table th:nth-child(6),
.evaluation-case-table td:nth-child(6) { width: 76px; }
.evaluation-case-table th:nth-child(7),
.evaluation-case-table td:nth-child(7) { width: 62px; }
.evaluation-case-table th:nth-child(8),
.evaluation-case-table td:nth-child(8) { width: 82px; }

.evaluation-select-cell {
  text-align: center;
}

.evaluation-table input[type='checkbox'],
.evaluation-table input[type='radio'] {
  width: 17px;
  height: 17px;
  margin: 0;
  accent-color: #146348;
  cursor: pointer;
}

.evaluation-case-id,
.evaluation-case-rounds {
  color: #536077;
  white-space: nowrap;
}

.evaluation-case-topic {
  font-weight: 600;
}

.evaluation-case-question {
  color: #354257;
  overflow-wrap: anywhere;
}

.evaluation-empty {
  padding: 24px !important;
  color: #8a95a5 !important;
  text-align: center;
}

.evaluation-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 10px;
  color: #758195;
  font-size: 12px;
}

.evaluation-pagination label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.evaluation-pagination select {
  min-height: 30px;
  padding: 0 8px;
  color: #354257;
  background: #fff;
  border: 1px solid #d8e0da;
  border-radius: 6px;
  font: inherit;
}

.evaluation-pagination button {
  min-height: 30px;
  padding: 0 11px;
  color: #536077;
  background: #fff;
  border: 1px solid #d8e0da;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}

.evaluation-pagination button:hover:not(:disabled) {
  color: #185b44;
  border-color: #a9c8b9;
}

.evaluation-pagination button:disabled {
  color: #b4bbc5;
  cursor: default;
}

.evaluation-page-size {
  width: 68px;
}

.evaluation-page-size :deep(.el-select__wrapper) {
  min-height: 30px;
  padding: 0 8px;
  color: #354257;
  border: 1px solid #d8e0da;
  border-radius: 6px;
  box-shadow: none;
  font: inherit;
}

.evaluation-create-layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  align-items: center;
  gap: 14px;
}

.evaluation-create-layout .evaluation-section-heading {
  margin: 0;
}

.evaluation-create-form {
  display: grid;
  grid-template-columns: minmax(190px, 1fr) minmax(150px, 180px) 126px;
  align-items: center;
  gap: 10px;
}

.evaluation-create-form label {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: #758195;
  font-size: 12px;
  white-space: nowrap;
}

.evaluation-create-form input,
.evaluation-create-form select {
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

.evaluation-create-form input::placeholder {
  color: #a0a9b5;
}

.evaluation-create-input,
.evaluation-create-select {
  flex: 1 1 auto;
  min-width: 0;
}

.evaluation-create-input :deep(.el-input__wrapper),
.evaluation-create-select :deep(.el-select__wrapper) {
  min-height: 38px;
  padding: 0 10px;
  color: #354257;
  border: 1px solid #d8e0da;
  border-radius: 7px;
  box-shadow: none;
  font: inherit;
}

.evaluation-create-input :deep(.el-input__inner),
.evaluation-create-select :deep(.el-select__placeholder),
.evaluation-create-select :deep(.el-select__selected-item) {
  color: #354257;
  font: inherit;
}

.evaluation-create-input :deep(.el-input__inner::placeholder) {
  color: #a0a9b5;
}

.evaluation-run-table {
  min-width: 700px;
}

.evaluation-run-table th:nth-child(1),
.evaluation-run-table td:nth-child(1) { width: 42px; }
.evaluation-run-table th:nth-child(2),
.evaluation-run-table td:nth-child(2) { width: 42%; }
.evaluation-run-table th:nth-child(3),
.evaluation-run-table td:nth-child(3) { width: 18%; }
.evaluation-run-table th:nth-child(4),
.evaluation-run-table td:nth-child(4) { width: 18%; }
.evaluation-run-table th:nth-child(5),
.evaluation-run-table td:nth-child(5) { width: 22%; }

.evaluation-run-table tbody tr {
  cursor: pointer;
}

.evaluation-run-table tbody tr:hover,
.evaluation-run-table tbody tr.evaluation-run-selected {
  background: #f0f7f4;
}

.evaluation-link {
  padding: 0;
  color: #185b44;
  background: none;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-weight: 650;
  text-align: left;
}

.evaluation-status-inline {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}

.evaluation-status-inline i {
  display: block;
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}

.evaluation-status-completed,
.evaluation-completed { color: #168052; }
.evaluation-status-running { color: #3175d6; }
.evaluation-status-pending { color: #a47b22; }
.evaluation-status-failed,
.evaluation-failed { color: #c45656; }

.evaluation-detail-panel {
  padding-top: 16px;
}

.evaluation-detail-heading {
  align-items: flex-start;
}

.evaluation-detail-heading .evaluation-status {
  padding-top: 4px;
}

.evaluation-status {
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
}

.evaluation-progress {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 10px 0 13px;
  border-bottom: 1px solid #e7ece9;
  color: #758195;
  font-size: 12px;
}

.evaluation-progress-status,
.evaluation-progress-track {
  display: flex;
  align-items: center;
  gap: 9px;
  white-space: nowrap;
}

.evaluation-progress-track {
  min-width: 0;
}

.evaluation-progress-track progress {
  width: min(100%, 520px);
  min-width: 90px;
  height: 9px;
  margin-left: 3px;
  accent-color: #126047;
}

.evaluation-progress-track strong {
  color: #354257;
  font-weight: 500;
}

.evaluation-progress-percent {
  color: #718096;
  white-space: nowrap;
}

.evaluation-metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin-top: 14px;
}

.evaluation-metrics div {
  display: grid;
  gap: 7px;
  padding: 0 14px;
  border-left: 1px solid #dfe6e2;
  text-align: center;
}

.evaluation-metrics div:first-child {
  border-left: 0;
}

.evaluation-metrics span {
  color: #758195;
  font-size: 11px;
}

.evaluation-metrics strong {
  color: #155a42;
  font-size: 19px;
  line-height: 1.1;
}

.evaluation-metric-note {
  margin: 10px 0 0;
  color: #7d899b;
  font-size: 12px;
  line-height: 1.6;
}

.evaluation-results {
  margin-top: 18px;
}

.evaluation-results h3 {
  margin: 0 0 9px;
  color: #20352d;
  font-size: 15px;
}

.evaluation-result {
  display: grid;
  gap: 9px;
  padding: 10px 10px 11px;
  border: 1px solid #e0e8e3;
  border-radius: 7px;
}

.evaluation-result-heading,
.evaluation-result-flags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px 12px;
  color: #667286;
  font-size: 12px;
}

.evaluation-result-heading strong {
  color: #354257;
  font-size: 12px;
}

.evaluation-result-chevron {
  color: #526079;
  font-size: 21px;
  line-height: 0.7;
}

.evaluation-result-flags b {
  color: #168052;
  font-weight: 650;
}

.evaluation-answer {
  margin: 0;
  color: #4e5a6b;
  font-size: 12px;
  line-height: 1.65;
}

.evaluation-citations {
  color: #185b44;
  font-size: 12px;
}

.evaluation-citations ul {
  display: grid;
  gap: 7px;
  margin: 8px 0 0;
  padding-left: 18px;
  color: #4e5a6b;
}

.evaluation-citations li span {
  display: block;
  margin-top: 3px;
  color: #758195;
  line-height: 1.55;
}

.evaluation-error {
  margin: 9px 0;
  padding: 8px 10px;
  color: #a63c3c;
  background: #fff4f2;
  border: 1px solid #f0d5d1;
  border-radius: 7px;
  font-size: 12px;
  line-height: 1.5;
}

.evaluation-muted {
  margin: 10px 0 0;
  color: #8a95a5;
  font-size: 12px;
}

@media (max-width: 820px) {
  .evaluation-filters {
    grid-template-columns: minmax(220px, 1fr) 1fr 1fr;
  }

  .evaluation-filters .evaluation-primary {
    grid-column: 1 / -1;
    justify-self: end;
    min-width: 100px;
  }

  .evaluation-create-layout {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .evaluation-create-form {
    grid-template-columns: minmax(180px, 1fr) minmax(140px, 1fr) 112px;
  }
}

@media (max-width: 620px) {
  .evaluation-page {
    width: 100%;
    gap: 10px;
  }

  .evaluation-count {
    padding-bottom: 0;
    font-size: 15px;
  }

  .evaluation-count strong {
    font-size: 29px;
  }

  .evaluation-panel {
    padding: 12px 10px 10px;
  }

  .evaluation-filters,
  .evaluation-create-form {
    grid-template-columns: 1fr;
  }

  .evaluation-filters .evaluation-primary {
    width: 100%;
    grid-column: auto;
  }

  .evaluation-create-form label {
    align-items: stretch;
    flex-direction: column;
    gap: 5px;
    white-space: normal;
  }

  .evaluation-create-form .evaluation-primary {
    width: 100%;
  }

  .evaluation-progress {
    grid-template-columns: 1fr auto;
  }

  .evaluation-progress-track {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .evaluation-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 13px 0;
  }

  .evaluation-metrics div:nth-child(odd) {
    border-left: 0;
  }

  .evaluation-results {
    margin-top: 15px;
  }
}
</style>
