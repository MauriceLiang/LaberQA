<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

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
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
}

function formatFlag(value: boolean | null) {
  return value === null ? '—' : value ? '是' : '否'
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
    <div class="page-intro">
      <div>
        <p class="eyebrow">QUALITY EVALUATION</p>
        <h2 id="evaluation-title">问答评测</h2>
        <p>筛选评测用例，按指定范围创建后台评测批次，并查看运行进度与逐题结果。</p>
      </div>
      <span class="evaluation-count">已选 {{ selectedCaseIds.size }} 条用例</span>
    </div>

    <section class="evaluation-panel" aria-labelledby="evaluation-cases-title">
      <div class="evaluation-section-heading">
        <div>
          <h3 id="evaluation-cases-title">评测用例</h3>
          <p>不选择用例时，批次将执行全部 60 条。</p>
        </div>
      </div>
      <p v-if="casesError" class="evaluation-error" role="alert">{{ casesError }}</p>
      <form class="evaluation-filters" @submit.prevent="applyCaseFilters">
        <label>
          主题
          <input v-model="topicInput" type="search" placeholder="输入主题筛选" />
        </label>
        <label>
          预期类型
          <select v-model="expectedTypeFilter">
            <option value="">全部</option>
            <option value="ANSWER">应回答</option>
            <option value="REJECT">应拒答</option>
          </select>
        </label>
        <label>
          对话轮数
          <select v-model="multiTurnFilter">
            <option value="">全部</option>
            <option value="false">单轮</option>
            <option value="true">多轮</option>
          </select>
        </label>
        <button type="submit" class="evaluation-primary">筛选</button>
      </form>

      <div class="evaluation-table-wrap" :aria-busy="loadingCases">
        <table class="evaluation-table">
          <thead>
            <tr>
              <th><input aria-label="选择本页全部用例" type="checkbox" :checked="selectedPageFully" @change="toggleCurrentPage" /></th>
              <th>ID</th>
              <th>主题</th>
              <th>问题轮次</th>
              <th>预期</th>
              <th>多轮</th>
              <th>合规提示</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in cases" :key="item.id">
              <td><input :aria-label="`选择用例 ${item.id}`" type="checkbox" :checked="selectedCaseIds.has(item.id)" @change="toggleCase(item.id, ($event.target as HTMLInputElement).checked)" /></td>
              <td>{{ item.id }}</td>
              <td>{{ item.topic }}</td>
              <td class="evaluation-turns">{{ item.turns.join(' → ') }}</td>
              <td>{{ item.expected_type === 'ANSWER' ? '应回答' : '应拒答' }}</td>
              <td>{{ item.turns.length > 1 ? '是' : '否' }}</td>
              <td>{{ item.should_show_compliance ? '需要' : '不需要' }}</td>
            </tr>
            <tr v-if="!loadingCases && cases.length === 0">
              <td colspan="7" class="evaluation-empty">暂无符合条件的用例</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="evaluation-pagination">
        <span>共 {{ caseTotal }} 条，第 {{ casePage }} / {{ casePages || 1 }} 页</span>
        <label>每页
          <select :value="caseSize" @change="caseSize = Number(($event.target as HTMLSelectElement).value); casePage = 1; void loadCases()">
            <option :value="10">10</option>
            <option :value="20">20</option>
            <option :value="50">50</option>
          </select>
        </label>
        <button :disabled="casePage <= 1 || loadingCases" @click="changeCasePage(casePage - 1)">上一页</button>
        <button :disabled="casePage >= casePages || loadingCases" @click="changeCasePage(casePage + 1)">下一页</button>
      </div>
    </section>

    <section class="evaluation-panel" aria-labelledby="evaluation-create-title">
      <div class="evaluation-section-heading">
        <div>
          <h3 id="evaluation-create-title">创建评测批次</h3>
          <p>选择用例后仅运行所选项；未选择时运行全量用例。</p>
        </div>
      </div>
      <form class="evaluation-create-form" @submit.prevent="createRun">
        <label>
          批次名称
          <input v-model="runName" maxlength="100" placeholder="例如：正式评测-20260915" />
        </label>
        <label>
          回答风格
          <select v-model="answerStyle">
            <option value="plain">通俗版</option>
            <option value="legal">严谨版</option>
          </select>
        </label>
        <button class="evaluation-primary" type="submit" :disabled="creatingRun">
          {{ creatingRun ? '创建中…' : '创建批次' }}
        </button>
      </form>
      <p v-if="createError" class="evaluation-error" role="alert">{{ createError }}</p>
    </section>

    <section class="evaluation-panel" aria-labelledby="evaluation-runs-title">
      <div class="evaluation-section-heading">
        <div>
          <h3 id="evaluation-runs-title">评测批次</h3>
          <p>选择批次查看进度；运行中的任务每 2 秒更新一次。</p>
        </div>
      </div>
      <p v-if="runsError" class="evaluation-error" role="alert">{{ runsError }}</p>
      <p v-if="detailError" class="evaluation-error" role="alert">{{ detailError }}</p>
      <div class="evaluation-table-wrap" :aria-busy="loadingRuns">
        <table class="evaluation-table evaluation-run-table">
          <thead><tr><th>批次</th><th>状态</th><th>进度</th><th>创建时间</th></tr></thead>
          <tbody>
            <tr
              v-for="run in runs"
              :key="run.id"
              :class="{ 'evaluation-run-selected': run.id === selectedRunId }"
              @click="selectRun(run)"
            >
              <td><button class="evaluation-link" type="button" @click.stop="selectRun(run)">{{ run.name }}</button></td>
              <td>{{ formatStatus(run.status) }}</td>
              <td>{{ run.progress_current }} / {{ run.progress_total }}</td>
              <td>{{ new Date(run.created_at).toLocaleString() }}</td>
            </tr>
            <tr v-if="!loadingRuns && runs.length === 0">
              <td colspan="4" class="evaluation-empty">暂无评测批次</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="evaluation-pagination">
        <span>共 {{ runTotal }} 条，第 {{ runPage }} / {{ runPages || 1 }} 页</span>
        <button :disabled="runPage <= 1 || loadingRuns" @click="changeRunPage(runPage - 1)">上一页</button>
        <button :disabled="runPage >= runPages || loadingRuns" @click="changeRunPage(runPage + 1)">下一页</button>
      </div>
    </section>

    <section v-if="selectedRunId !== undefined" class="evaluation-panel" aria-labelledby="evaluation-detail-title">
      <div class="evaluation-section-heading">
        <div>
          <p class="eyebrow">RUN DETAIL</p>
          <h3 id="evaluation-detail-title">{{ displayedRunName }}</h3>
        </div>
        <span class="evaluation-status">{{ formatStatus(displayedStatus) }}</span>
      </div>
      <p v-if="runDetail?.error_message" class="evaluation-error" role="alert">{{ runDetail.error_message }}</p>
      <p v-if="loadingDetail && !runDetail" class="evaluation-muted">正在读取评测详情…</p>
      <template v-if="runDetail">
        <div class="evaluation-progress" aria-label="评测进度">
          <span>{{ runDetail.progress_current }} / {{ runDetail.progress_total }} 题</span>
          <progress :value="runDetail.progress_current" :max="Math.max(runDetail.progress_total, 1)" />
        </div>
        <div v-if="runDetail.metrics" class="evaluation-metrics" aria-label="评测指标">
          <div><span>回答正确率</span><strong>{{ formatRate(runDetail.metrics.accuracy) }}</strong></div>
          <div><span>拒答率</span><strong>{{ formatRate(runDetail.metrics.reject_rate) }}</strong></div>
          <div><span>引用命中率</span><strong>{{ formatRate(runDetail.metrics.citation_hit_rate) }}</strong></div>
          <div><span>多轮通过率</span><strong>{{ formatRate(runDetail.metrics.multi_turn_pass_rate) }}</strong></div>
          <div><span>合规提示命中率</span><strong>{{ formatRate(runDetail.metrics.compliance_hit_rate) }}</strong></div>
        </div>
        <div v-else-if="terminalStatus(runDetail.status)" class="evaluation-muted">此批次没有可计算的指标。</div>

        <div class="evaluation-results">
          <h4>逐题结果（{{ runDetail.results.length }}）</h4>
          <div v-if="runDetail.results.length === 0" class="evaluation-muted">任务完成后会显示逐题回答、引用与判定。</div>
          <article v-for="result in runDetail.results" :key="result.case_id" class="evaluation-result">
            <div class="evaluation-result-heading">
              <strong>用例 #{{ result.case_id }}</strong>
              <span :class="result.status === 'FAILED' ? 'evaluation-failed' : 'evaluation-completed'">
                {{ result.status === 'FAILED' ? '单题失败' : '已评估' }}
              </span>
              <span v-if="result.latency_ms !== null">耗时 {{ result.latency_ms }} ms</span>
            </div>
            <p v-if="result.error_message" class="evaluation-error">{{ result.error_message }}</p>
            <p v-if="result.answer" class="evaluation-answer">{{ result.answer }}</p>
            <div class="evaluation-result-flags">
              <span>正确：{{ formatFlag(result.correct) }}</span>
              <span>拒答：{{ formatFlag(result.refused) }}</span>
              <span>引用命中：{{ formatFlag(result.source_hit) }}</span>
              <span>多轮通过：{{ formatFlag(result.multi_turn_correct) }}</span>
              <span>合规提示：{{ formatFlag(result.compliance_hit) }}</span>
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
.evaluation-page { display: grid; gap: 20px; }
.evaluation-count { color: #26705d; font-size: 13px; font-weight: 650; white-space: nowrap; }
.evaluation-panel { padding: 22px; background: #fff; border: 1px solid #e8edf3; border-radius: 16px; }
.evaluation-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 14px; }
.evaluation-section-heading h3 { margin: 0; font-size: 17px; }
.evaluation-section-heading p:not(.eyebrow) { margin: 6px 0 0; color: #758195; font-size: 13px; }
.evaluation-filters, .evaluation-create-form { display: flex; align-items: end; flex-wrap: wrap; gap: 12px; }
.evaluation-filters label, .evaluation-create-form label, .evaluation-pagination label { display: grid; gap: 6px; color: #667286; font-size: 13px; }
.evaluation-filters input, .evaluation-filters select, .evaluation-create-form input, .evaluation-create-form select, .evaluation-pagination select { min-height: 36px; padding: 7px 9px; color: #202938; background: #fff; border: 1px solid #d8dee8; border-radius: 7px; font: inherit; }
.evaluation-filters input { min-width: 190px; }
.evaluation-create-form input { min-width: 270px; }
.evaluation-primary { min-height: 36px; padding: 0 14px; color: #fff; background: #26705d; border: 0; border-radius: 7px; cursor: pointer; }
.evaluation-primary:disabled { opacity: .6; cursor: default; }
.evaluation-table-wrap { margin-top: 16px; overflow-x: auto; }
.evaluation-table { width: 100%; border-collapse: collapse; text-align: left; }
.evaluation-table th, .evaluation-table td { padding: 11px 9px; border-bottom: 1px solid #edf0f4; vertical-align: top; }
.evaluation-table th { color: #758195; font-size: 12px; font-weight: 650; white-space: nowrap; }
.evaluation-table td { color: #4e5a6b; font-size: 13px; }
.evaluation-table input[type='checkbox'] { accent-color: #26705d; }
.evaluation-turns { min-width: 260px; max-width: 440px; }
.evaluation-empty { padding: 26px !important; color: #8a95a5 !important; text-align: center; }
.evaluation-pagination { display: flex; justify-content: flex-end; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 16px; color: #758195; font-size: 13px; }
.evaluation-pagination button { min-height: 34px; padding: 0 10px; color: #4e5a6b; background: #fff; border: 1px solid #d8dee8; border-radius: 7px; cursor: pointer; }
.evaluation-pagination button:disabled { color: #b4bbc5; cursor: default; }
.evaluation-run-table tbody tr { cursor: pointer; }
.evaluation-run-table tbody tr:hover, .evaluation-run-table tbody tr.evaluation-run-selected { background: #f0f7f4; }
.evaluation-link { padding: 0; color: #26705d; font: inherit; font-weight: 650; text-align: left; background: none; border: 0; cursor: pointer; }
.evaluation-status { padding: 5px 10px; color: #26705d; background: #edf7f3; border-radius: 999px; font-size: 12px; font-weight: 650; }
.evaluation-progress { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 12px; color: #667286; font-size: 13px; }
.evaluation-progress progress { width: 100%; height: 10px; accent-color: #26705d; }
.evaluation-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-top: 18px; }
.evaluation-metrics div { display: grid; gap: 8px; padding: 14px; background: #f5f8f7; border-radius: 10px; }
.evaluation-metrics span { color: #758195; font-size: 12px; }
.evaluation-metrics strong { color: #26705d; font-size: 20px; }
.evaluation-results { margin-top: 22px; }
.evaluation-results h4 { margin: 0 0 12px; font-size: 15px; }
.evaluation-result { display: grid; gap: 10px; padding: 14px 0; border-top: 1px solid #edf0f4; }
.evaluation-result-heading, .evaluation-result-flags { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; color: #667286; font-size: 12px; }
.evaluation-result-heading strong { color: #202938; font-size: 13px; }
.evaluation-completed { color: #26705d; }
.evaluation-failed { color: #c45656; }
.evaluation-answer { margin: 0; color: #4e5a6b; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.evaluation-citations { color: #26705d; font-size: 12px; }
.evaluation-citations ul { display: grid; gap: 8px; padding-left: 18px; color: #4e5a6b; }
.evaluation-citations li span { display: block; margin-top: 4px; color: #758195; line-height: 1.6; }
.evaluation-error { margin: 10px 0; padding: 10px 12px; color: #a63c3c; background: #fff1f0; border: 1px solid #f3d0ce; border-radius: 8px; font-size: 13px; }
.evaluation-muted { margin: 12px 0 0; color: #8a95a5; font-size: 13px; }
@media (max-width: 700px) { .evaluation-panel { padding: 16px; } .evaluation-filters, .evaluation-create-form { align-items: stretch; } .evaluation-filters label, .evaluation-create-form label { flex: 1 1 100%; } }
</style>
