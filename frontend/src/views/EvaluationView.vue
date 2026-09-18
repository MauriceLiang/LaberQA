<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ElButton,
  ElDialog,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElSwitch,
} from 'element-plus'
import { ArrowRight, Search } from '@element-plus/icons-vue'

import {
  createEvaluationCase,
  createEvaluationRun,
  deleteEvaluationCase,
  deleteEvaluationRun,
  getEvaluationCases,
  getEvaluationRun,
  getEvaluationRuns,
  updateEvaluationCase,
  type EvaluationAnswerStyle,
  type EvaluationCase,
  type EvaluationCaseInput,
  type EvaluationCaseOrigin,
  type EvaluationCaseScope,
  type EvaluationCaseStatus,
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
const caseOriginFilter = ref<EvaluationCaseOrigin | ''>('')
const caseStatusFilter = ref<EvaluationCaseStatus | ''>('')
const selectedCaseIds = ref(new Set<number>())
const loadingCases = ref(false)
const casesError = ref('')
let caseRequestId = 0

type CaseForm = EvaluationCaseInput

const emptyCaseForm = (): CaseForm => ({
  topic: '',
  expected_type: 'ANSWER',
  turns: [''],
  expected_points: [''],
  expected_sources: [],
  should_show_compliance: false,
})

const caseDialogVisible = ref(false)
const editingCase = ref<EvaluationCase>()
const caseForm = ref<CaseForm>(emptyCaseForm())
const caseFormError = ref('')
const savingCase = ref(false)
const deletingCaseId = ref<number>()
const caseScope = ref<EvaluationCaseScope>('BUILTIN_BASELINE')

const runs = ref<EvaluationRunSummary[]>([])
const runPage = ref(1)
const runSize = 10
const runTotal = ref(0)
const runPages = ref(0)
const loadingRuns = ref(false)
const deletingRunId = ref<number>()
const runsError = ref('')
const runName = ref('')
const answerStyle = ref<EvaluationAnswerStyle>('plain')
const creatingRun = ref(false)
const createError = ref('')
const selectedRunId = ref<number>()
const runDetail = ref<EvaluationRunDetail>()
const loadingDetail = ref(false)
const detailError = ref('')
const detailRequestVersions = new Map<number, number>()
let selectedRunVersion = 0
let pollTimer: ReturnType<typeof setInterval> | undefined

const selectedPageFully = computed(
  () => {
    const activeCases = cases.value.filter((item) => item.status === 'ACTIVE')
    return activeCases.length > 0 && activeCases.every((item) => selectedCaseIds.value.has(item.id))
  },
)
const selectedRunSummary = computed(() => runs.value.find((run) => run.id === selectedRunId.value))
const allActiveCaseLabel = computed(() => {
  const isUnfilteredActiveList = !topicFilter.value
    && !expectedTypeFilter.value
    && !multiTurnFilter.value
    && !caseOriginFilter.value
    && !caseStatusFilter.value
  return isUnfilteredActiveList ? `全部活动用例（${caseTotal.value} 条）` : '全部活动用例'
})
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
      origin: caseOriginFilter.value || undefined,
      status: caseStatusFilter.value || undefined,
      include_archived: caseStatusFilter.value === 'ARCHIVED',
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

function openCreateCase() {
  editingCase.value = undefined
  caseForm.value = emptyCaseForm()
  caseFormError.value = ''
  caseDialogVisible.value = true
}

function openEditCase(item: EvaluationCase) {
  if (item.status !== 'ACTIVE') return
  editingCase.value = item
  caseForm.value = {
    topic: item.topic,
    expected_type: item.expected_type,
    turns: [...item.turns],
    expected_points: [...item.expected_points],
    expected_sources: item.expected_sources.map((source) => ({ ...source })),
    should_show_compliance: item.should_show_compliance,
  }
  caseFormError.value = ''
  caseDialogVisible.value = true
}

function addCaseTurn() {
  if (caseForm.value.turns.length < 10) caseForm.value.turns.push('')
}

function removeCaseTurn(index: number) {
  if (caseForm.value.turns.length <= 1) return
  caseForm.value.turns.splice(index, 1)
}

function addExpectedPoint() {
  if (caseForm.value.expected_points.length < 20) caseForm.value.expected_points.push('')
}

function removeExpectedPoint(index: number) {
  caseForm.value.expected_points.splice(index, 1)
}

function addExpectedSource() {
  if (caseForm.value.expected_sources.length < 20) {
    caseForm.value.expected_sources.push({ file_name: '', chunk_no: null })
  }
}

function removeExpectedSource(index: number) {
  caseForm.value.expected_sources.splice(index, 1)
}

function validateCaseForm(): string | undefined {
  caseForm.value.topic = caseForm.value.topic.trim()
  if (!caseForm.value.topic) return '请填写用例主题'
  const turns = caseForm.value.turns.map((turn) => turn.trim())
  if (turns.some((turn) => !turn)) return '每轮问题都不能为空'
  caseForm.value.turns = turns
  const points = caseForm.value.expected_points.map((point) => point.trim()).filter(Boolean)
  if (caseForm.value.expected_type === 'ANSWER' && points.length === 0) {
    return '应回答用例至少需要一个预期要点'
  }
  caseForm.value.expected_points = points
  const sources = caseForm.value.expected_sources.map((source) => ({
    file_name: source.file_name.trim(),
    chunk_no: source.chunk_no === null || source.chunk_no === undefined || Number.isNaN(Number(source.chunk_no))
      ? null
      : Number(source.chunk_no),
  }))
  if (sources.some((source) => !source.file_name || (source.chunk_no !== null && source.chunk_no < 1))) {
    return '引用来源需要填写文件名，分块号必须为正整数'
  }
  caseForm.value.expected_sources = sources
  return undefined
}

async function saveCase() {
  const validationError = validateCaseForm()
  if (validationError) {
    caseFormError.value = validationError
    return
  }
  savingCase.value = true
  caseFormError.value = ''
  try {
    if (editingCase.value) {
      await updateEvaluationCase(editingCase.value.id, {
        ...caseForm.value,
        version: editingCase.value.version,
      })
      ElMessage.success('评测用例已更新')
    } else {
      await createEvaluationCase(caseForm.value)
      ElMessage.success('评测用例已创建')
    }
    caseDialogVisible.value = false
    await loadCases()
  } catch (error) {
    caseFormError.value = getErrorMessage(error)
  } finally {
    savingCase.value = false
  }
}

async function archiveCase(item: EvaluationCase) {
  if (item.origin === 'BUILTIN' || item.status !== 'ACTIVE' || deletingCaseId.value !== undefined) return
  try {
    await ElMessageBox.confirm(
      '删除后，该用例将从新的评测选择列表中移除；已有评测批次和结果不会被删除。',
      `确定删除评测用例“${item.topic}”吗？`,
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        closeOnClickModal: false,
      },
    )
  } catch {
    return
  }
  deletingCaseId.value = item.id
  casesError.value = ''
  try {
    await deleteEvaluationCase(item.id)
    const next = new Set(selectedCaseIds.value)
    next.delete(item.id)
    selectedCaseIds.value = next
    ElMessage.success('评测用例已删除')
    if (cases.value.length === 1 && casePage.value > 1) casePage.value -= 1
    await loadCases()
  } catch (error) {
    casesError.value = `删除评测用例失败：${getErrorMessage(error)}`
  } finally {
    deletingCaseId.value = undefined
  }
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
  const activeCases = cases.value.filter((item) => item.status === 'ACTIVE')
  if (selectedPageFully.value) activeCases.forEach((item) => next.delete(item.id))
  else activeCases.forEach((item) => next.add(item.id))
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
  } catch (error) {
    runsError.value = getErrorMessage(error)
  } finally {
    loadingRuns.value = false
  }
}

function syncRunSummary(detail: EvaluationRunDetail) {
  const index = runs.value.findIndex((run) => run.id === detail.id)
  if (index === -1) return

  runs.value[index] = {
    ...runs.value[index],
    name: detail.name,
    status: detail.status,
    progress_current: detail.progress_current,
    progress_total: detail.progress_total,
    error_message: detail.error_message,
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
    if (!detailRequestVersions.has(id) && selectedRunId.value === id) void loadRunDetail(id)
  }, 2000)
}

async function loadRunDetail(id: number, showLoading = false) {
  const version = selectedRunVersion
  if (detailRequestVersions.get(id) === version) return
  detailRequestVersions.set(id, version)
  if (showLoading) loadingDetail.value = true
  detailError.value = ''
  try {
    const result = await getEvaluationRun(id)
    if (version !== selectedRunVersion || selectedRunId.value !== id) return
    runDetail.value = result
    syncRunSummary(result)
    if (terminalStatus(result.status)) stopPolling()
    else startPolling(id)
  } catch (error) {
    if (version === selectedRunVersion && selectedRunId.value === id) detailError.value = getErrorMessage(error)
  } finally {
    if (detailRequestVersions.get(id) === version) detailRequestVersions.delete(id)
    if (version === selectedRunVersion && selectedRunId.value === id && showLoading) {
      loadingDetail.value = false
    }
  }
}

function toggleRun(run: EvaluationRunSummary) {
  stopPolling()
  selectedRunVersion += 1
  if (selectedRunId.value === run.id) {
    selectedRunId.value = undefined
    runDetail.value = undefined
    loadingDetail.value = false
    detailError.value = ''
    return
  }
  selectedRunId.value = run.id
  runDetail.value = undefined
  detailError.value = ''
  if (!terminalStatus(run.status)) startPolling(run.id)
  void loadRunDetail(run.id, true)
}

async function deleteRun(run: EvaluationRunSummary) {
  if (!terminalStatus(run.status) || deletingRunId.value !== undefined) return
  try {
    await ElMessageBox.confirm(
      '将同时删除该批次的逐题结果、指标和用例关联，删除后不可恢复。',
      `确定删除评测批次“${run.name}”吗？`,
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        closeOnClickModal: false,
      },
    )
  } catch {
    return
  }

  deletingRunId.value = run.id
  runsError.value = ''
  try {
    await deleteEvaluationRun(run.id)
    if (selectedRunId.value === run.id) {
      stopPolling()
      selectedRunVersion += 1
      selectedRunId.value = undefined
      runDetail.value = undefined
      loadingDetail.value = false
      detailError.value = ''
    }
    if (runs.value.length === 1 && runPage.value > 1) runPage.value -= 1
    await loadRuns()
  } catch (error) {
    runsError.value = `删除评测批次失败：${getErrorMessage(error)}`
  } finally {
    deletingRunId.value = undefined
  }
}

async function createRun() {
  const name = runName.value.trim()
  if (!name) {
    createError.value = '请填写评测批次名称'
    return
  }
  if (caseScope.value === 'SELECTED' && selectedCaseIds.value.size === 0) {
    createError.value = '选择“已选用例”时，至少勾选一条用例'
    return
  }

  creatingRun.value = true
  createError.value = ''
  try {
    const job = await createEvaluationRun({
      name,
      case_ids: caseScope.value === 'SELECTED'
        ? [...selectedCaseIds.value].sort((a, b) => a - b)
        : null,
      answer_style: answerStyle.value,
      case_scope: caseScope.value,
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
          <p>内置基线和自定义用例均可编辑；自定义用例可删除</p>
        </div>
        <ElButton type="primary" class="evaluation-primary" @click="openCreateCase">新建用例</ElButton>
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
        <label class="evaluation-filter-control">
          <span class="sr-only">用例来源</span>
          <ElSelect v-model="caseOriginFilter" class="evaluation-filter-select" aria-label="用例来源" placeholder="用例来源">
            <ElOption label="内置基线" value="BUILTIN" />
            <ElOption label="自定义" value="CUSTOM" />
          </ElSelect>
        </label>
        <label class="evaluation-filter-control">
          <span class="sr-only">用例状态</span>
          <ElSelect v-model="caseStatusFilter" class="evaluation-filter-select" aria-label="用例状态" placeholder="活动用例">
            <ElOption label="活动用例" value="ACTIVE" />
            <ElOption label="已归档" value="ARCHIVED" />
          </ElSelect>
        </label>
        <ElButton type="primary" native-type="submit" class="evaluation-primary">筛选</ElButton>
      </form>

      <div class="evaluation-table-wrap" :aria-busy="loadingCases">
        <table class="evaluation-table evaluation-case-table">
          <thead>
            <tr>
              <th scope="col" class="evaluation-select-cell">
                <input aria-label="选择本页全部用例" type="checkbox" :disabled="!cases.some((item) => item.status === 'ACTIVE')" :checked="selectedPageFully" @change="toggleCurrentPage" />
              </th>
              <th scope="col">ID</th>
              <th scope="col">主题</th>
              <th scope="col">问题</th>
              <th scope="col">问题轮次</th>
              <th scope="col">预期</th>
              <th scope="col">多轮</th>
              <th scope="col">合规提示</th>
              <th scope="col">来源</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in cases" :key="item.id">
              <td class="evaluation-select-cell">
                <input :aria-label="`选择用例 ${item.id}`" type="checkbox" :disabled="item.status !== 'ACTIVE'" :checked="selectedCaseIds.has(item.id)" @change="toggleCase(item.id, ($event.target as HTMLInputElement).checked)" />
              </td>
              <td class="evaluation-case-id">{{ formatCaseId(item.id) }}</td>
              <td class="evaluation-case-topic">{{ item.topic }}</td>
              <td class="evaluation-case-question">{{ item.turns.join(' / ') }}</td>
              <td class="evaluation-case-rounds">{{ item.turns.length }}</td>
              <td>{{ item.expected_type === 'ANSWER' ? '应回答' : '应拒答' }}</td>
              <td>{{ item.turns.length > 1 ? '是' : '否' }}</td>
              <td>{{ item.should_show_compliance ? '需要' : '不需要' }}</td>
              <td>{{ item.origin === 'BUILTIN' ? '内置基线' : '自定义' }}</td>
              <td class="evaluation-case-actions">
                <template v-if="item.status === 'ACTIVE'">
                  <ElButton text size="small" @click.stop="openEditCase(item)">编辑</ElButton>
                  <ElButton v-if="item.origin === 'CUSTOM'" text type="danger" size="small" :loading="deletingCaseId === item.id" @click.stop="archiveCase(item)">删除</ElButton>
                </template>
                <span v-else class="evaluation-muted">已归档</span>
              </td>
            </tr>
            <tr v-if="!loadingCases && cases.length === 0">
              <td colspan="10" class="evaluation-empty">暂无符合条件的用例</td>
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

    <ElDialog
      v-model="caseDialogVisible"
      class="evaluation-case-dialog"
      modal-class="evaluation-case-overlay"
      :title="editingCase ? '编辑评测用例' : '新建评测用例'"
      width="min(720px, calc(100vw - 32px))"
      destroy-on-close
    >
      <form class="evaluation-case-form" @submit.prevent="saveCase">
        <label class="evaluation-case-field">
          <span>主题</span>
          <ElInput v-model="caseForm.topic" maxlength="50" show-word-limit placeholder="例如：劳动合同签订期限" />
        </label>
        <label class="evaluation-case-field">
          <span>预期类型</span>
          <ElSelect v-model="caseForm.expected_type" placeholder="选择预期类型">
            <ElOption label="应回答" value="ANSWER" />
            <ElOption label="应拒答" value="REJECT" />
          </ElSelect>
        </label>

        <div class="evaluation-form-array evaluation-form-section">
          <div class="evaluation-form-array-heading">
            <span>问题轮次</span>
            <ElButton text type="primary" :disabled="caseForm.turns.length >= 10" @click="addCaseTurn">新增轮次</ElButton>
          </div>
          <div v-for="(turn, index) in caseForm.turns" :key="`turn-${index}`" class="evaluation-form-array-row">
            <ElInput v-model="caseForm.turns[index]" type="textarea" :rows="2" maxlength="2000" show-word-limit :placeholder="`第 ${index + 1} 轮问题`" />
            <ElButton text type="danger" :disabled="caseForm.turns.length <= 1" @click="removeCaseTurn(index)">删除</ElButton>
          </div>
        </div>

        <div class="evaluation-form-array evaluation-form-section">
          <div class="evaluation-form-array-heading">
            <span>预期要点</span>
            <ElButton text type="primary" :disabled="caseForm.expected_points.length >= 20" @click="addExpectedPoint">新增要点</ElButton>
          </div>
          <div v-for="(point, index) in caseForm.expected_points" :key="`point-${index}`" class="evaluation-form-array-row">
            <ElInput v-model="caseForm.expected_points[index]" maxlength="500" placeholder="回答应包含的关键点" />
            <ElButton text type="danger" @click="removeExpectedPoint(index)">删除</ElButton>
          </div>
        </div>

        <div class="evaluation-form-array evaluation-form-section">
          <div class="evaluation-form-array-heading">
            <span>预期引用来源（可选）</span>
            <ElButton text type="primary" :disabled="caseForm.expected_sources.length >= 20" @click="addExpectedSource">新增来源</ElButton>
          </div>
          <div v-for="(source, index) in caseForm.expected_sources" :key="`source-${index}`" class="evaluation-form-array-row evaluation-source-row">
            <ElInput v-model="source.file_name" placeholder="文件名" />
            <ElInput v-model="source.chunk_no" type="number" min="1" placeholder="分块号（可选）" />
            <ElButton text type="danger" @click="removeExpectedSource(index)">删除</ElButton>
          </div>
        </div>

        <label class="evaluation-switch-row">
          <span>需要合规提示</span>
          <ElSwitch v-model="caseForm.should_show_compliance" />
        </label>
        <p v-if="caseFormError" class="evaluation-error" role="alert">{{ caseFormError }}</p>
        <div class="evaluation-dialog-actions">
          <ElButton native-type="button" @click="caseDialogVisible = false">取消</ElButton>
          <ElButton type="primary" native-type="submit" :loading="savingCase">保存</ElButton>
        </div>
      </form>
    </ElDialog>

    <section class="evaluation-panel evaluation-create-panel" aria-labelledby="evaluation-create-title">
      <div class="evaluation-create-layout">
        <div class="evaluation-section-heading">
          <div>
            <h2 id="evaluation-create-title">创建评测批次</h2>
            <p>选择执行范围后创建后台评测批次；历史批次保留执行时的用例版本</p>
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
          <label>
            <span>执行范围</span>
            <ElSelect v-model="caseScope" class="evaluation-create-select" aria-label="执行范围">
              <ElOption label="官方基线（60 条）" value="BUILTIN_BASELINE" />
              <ElOption :label="allActiveCaseLabel" value="ALL_ACTIVE" />
              <ElOption :label="`已选用例（${selectedCaseIds.size} 条）`" value="SELECTED" />
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
          <p>点击批次展开详情，再次点击收起；展开的运行中任务每 2 秒更新一次。</p>
        </div>
      </div>
      <p v-if="runsError" class="evaluation-error" role="alert">{{ runsError }}</p>
      <p v-if="detailError" class="evaluation-error" role="alert">{{ detailError }}</p>
      <div class="evaluation-table-wrap" :aria-busy="loadingRuns">
        <table class="evaluation-table evaluation-run-table">
          <thead>
            <tr>
              <th scope="col" class="evaluation-select-cell"><span class="sr-only">展开状态</span></th>
              <th scope="col">批次</th>
              <th scope="col">状态</th>
              <th scope="col">进度</th>
              <th scope="col">创建时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in runs"
              :key="run.id"
              :class="{ 'evaluation-run-selected': run.id === selectedRunId }"
              @click="toggleRun(run)"
            >
              <td class="evaluation-select-cell">
                <ElButton
                  class="evaluation-run-toggle"
                  text
                  circle
                  :aria-label="`${run.id === selectedRunId ? '收起' : '展开'}评测批次 ${run.name}`"
                  :aria-expanded="run.id === selectedRunId"
                  aria-controls="evaluation-run-detail"
                  @click.stop="toggleRun(run)"
                >
                  <ArrowRight aria-hidden="true" />
                </ElButton>
              </td>
              <td>
                <button
                  class="evaluation-link"
                  type="button"
                  :aria-expanded="run.id === selectedRunId"
                  aria-controls="evaluation-run-detail"
                  @click.stop="toggleRun(run)"
                >
                  {{ run.name }}
                </button>
              </td>
              <td>
                <span class="evaluation-status-inline" :class="statusClass(run.status)">
                  <i aria-hidden="true" />{{ formatStatus(run.status) }}
                </span>
              </td>
              <td>{{ run.progress_current }} / {{ run.progress_total }}</td>
              <td>{{ formatCreatedAt(run.created_at) }}</td>
              <td>
                <ElButton
                  class="evaluation-run-delete"
                  type="danger"
                  text
                  :loading="deletingRunId === run.id"
                  :disabled="!terminalStatus(run.status) || deletingRunId !== undefined"
                  :title="terminalStatus(run.status) ? '删除评测批次' : '排队中或运行中的批次不能删除'"
                  :aria-label="`删除评测批次 ${run.name}`"
                  @click.stop="deleteRun(run)"
                >
                  删除
                </ElButton>
              </td>
            </tr>
            <tr v-if="!loadingRuns && runs.length === 0">
              <td colspan="6" class="evaluation-empty">暂无评测批次</td>
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

    <section
      v-if="selectedRunId !== undefined"
      id="evaluation-run-detail"
      class="evaluation-panel evaluation-detail-panel"
      aria-labelledby="evaluation-detail-title"
    >
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
          <div><span title="应拒答用例中正确拒答的比例">应拒答命中率</span><strong>{{ formatRate(runDetail.metrics.reject_rate) }}</strong></div>
          <div><span title="全部已完成用例中实际触发拒答的比例">实际拒答率</span><strong>{{ formatRate(runDetail.metrics.refusal_rate) }}</strong></div>
          <div><span>引用命中率</span><strong>{{ formatRate(runDetail.metrics.citation_hit_rate) }}</strong></div>
          <div><span>多轮通过率</span><strong>{{ formatRate(runDetail.metrics.multi_turn_pass_rate) }}</strong></div>
          <div><span>合规提示命中率</span><strong>{{ formatRate(runDetail.metrics.compliance_hit_rate) }}</strong></div>
        </div>
        <div v-else-if="terminalStatus(runDetail.status)" class="evaluation-muted">此批次没有可计算的指标。</div>
        <p v-if="hasUnavailableMetrics" class="evaluation-metric-note">
          “不适用”表示本批次没有包含该指标所需的用例；同时包含对应类型的用例才会生成完整指标。
        </p>

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
  grid-template-columns: minmax(210px, 1.5fr) repeat(4, minmax(120px, 1fr)) 90px;
  gap: 8px;
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

/* Keep the section action aligned with the filter submit action at every breakpoint. */
.evaluation-section-heading .evaluation-primary {
  width: 90px;
  min-width: 90px;
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
.evaluation-case-table th:nth-child(9),
.evaluation-case-table td:nth-child(9) { width: 82px; }
.evaluation-case-table th:nth-child(10),
.evaluation-case-table td:nth-child(10) { width: 125px; }

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

.evaluation-case-actions {
  white-space: nowrap;
}

.evaluation-case-actions .el-button {
  padding: 4px 5px;
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
  grid-template-columns: minmax(170px, 1fr) minmax(140px, 170px) minmax(180px, 210px) 126px;
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

.evaluation-case-form {
  display: grid;
  gap: 18px;
}

.evaluation-case-form > label,
.evaluation-switch-row {
  display: grid;
  gap: 6px;
  color: #3d5c4d;
  font-size: 13px;
}

.evaluation-case-form > label > span,
.evaluation-switch-row > span {
  color: #315b4b;
  font-size: 14px;
  font-weight: 700;
}

.evaluation-case-form .el-select,
.evaluation-case-form .el-input {
  width: 100%;
}

:deep(.evaluation-case-dialog.el-dialog) {
  width: min(780px, calc(100vw - 32px)) !important;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 48px);
  margin-top: 24px;
  overflow: hidden;
  border: 1px solid #dbe9e1;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 24px 64px rgb(31 68 54 / 18%), 0 3px 12px rgb(31 68 54 / 8%);
}

:global(.evaluation-case-overlay) {
  background: rgb(31 68 54 / 42%);
}

:deep(.evaluation-case-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 22px 28px 15px;
  background: #fbfdfc;
  border-bottom: 1px solid #edf3ef;
}

:deep(.evaluation-case-dialog .el-dialog__title) {
  color: #155a42;
  font-family: "Songti SC", "STSong", "Noto Serif CJK SC", serif;
  font-size: 25px;
  font-weight: 700;
  letter-spacing: -0.03em;
}

:deep(.evaluation-case-dialog .el-dialog__headerbtn) {
  top: 18px;
  right: 20px;
  width: 34px;
  height: 34px;
  border-radius: 8px;
}

:deep(.evaluation-case-dialog .el-dialog__headerbtn:hover) {
  background: #edf7f1;
}

:deep(.evaluation-case-dialog .el-dialog__close) {
  color: #72857b;
}

:deep(.evaluation-case-dialog .el-dialog__headerbtn:hover .el-dialog__close) {
  color: #185b44;
}

:deep(.evaluation-case-dialog .el-dialog__body) {
  max-height: calc(100vh - 155px);
  padding: 22px 28px 26px;
  overflow-y: auto;
  scrollbar-color: #b8d3c4 transparent;
  scrollbar-width: thin;
}

.evaluation-case-form :deep(.el-input__wrapper),
.evaluation-case-form :deep(.el-select__wrapper) {
  min-height: 44px;
  padding: 2px 13px;
  background: #fbfdfc;
  border-radius: 9px;
  box-shadow: 0 0 0 1px #d8e5de inset;
  transition: box-shadow 160ms ease, background-color 160ms ease;
}

.evaluation-case-form :deep(.el-input__wrapper:hover),
.evaluation-case-form :deep(.el-select__wrapper:hover) {
  background: #fff;
  box-shadow: 0 0 0 1px #a9c8b9 inset;
}

.evaluation-case-form :deep(.el-input__wrapper.is-focus),
.evaluation-case-form :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: 0 0 0 2px #b9d9c8 inset !important;
}

.evaluation-case-form :deep(.el-input__inner),
.evaluation-case-form :deep(.el-select__selected-item),
.evaluation-case-form :deep(.el-select__placeholder) {
  color: #354257;
  font-size: 14px;
}

.evaluation-case-form :deep(.el-input__inner::placeholder),
.evaluation-case-form :deep(.el-textarea__inner::placeholder) {
  color: #9aa9a1;
}

.evaluation-case-form :deep(.el-textarea__inner) {
  min-height: 86px;
  padding: 12px 13px;
  color: #354257;
  background: #fbfdfc;
  border: 0;
  border-radius: 9px;
  box-shadow: 0 0 0 1px #d8e5de inset;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  transition: box-shadow 160ms ease, background-color 160ms ease;
}

.evaluation-case-form :deep(.el-textarea__inner:hover) {
  background: #fff;
  box-shadow: 0 0 0 1px #a9c8b9 inset;
}

.evaluation-case-form :deep(.el-textarea__inner:focus) {
  background: #fff;
  box-shadow: 0 0 0 2px #b9d9c8 inset;
}

.evaluation-case-form :deep(.el-input__count),
.evaluation-case-form :deep(.el-input__count-inner) {
  color: #93a39a;
  background: transparent;
}

.evaluation-form-array {
  display: grid;
  gap: 8px;
}

.evaluation-form-section {
  gap: 10px;
  padding: 14px 16px 16px;
  background: #f8fbf9;
  border: 1px solid #e2eee7;
  border-radius: 10px;
}

.evaluation-form-array-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 7px;
  color: #28654e;
  border-bottom: 1px solid #e5efe9;
  font-size: 14px;
  font-weight: 700;
}

.evaluation-form-array-heading .el-button {
  height: 30px;
  padding: 0 9px;
  color: #1c6b50;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 650;
}

.evaluation-form-array-heading .el-button:hover:not(.is-disabled) {
  color: #155a42;
  background: #eaf5ef;
}

.evaluation-form-array-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px;
}

.evaluation-source-row {
  grid-template-columns: minmax(0, 1fr) 140px auto;
}

.evaluation-form-array-row > .el-button {
  min-width: 44px;
  margin-top: 8px;
  padding: 4px 7px;
  color: #a8615a;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 650;
}

.evaluation-form-array-row > .el-button:hover:not(.is-disabled) {
  color: #914a44;
  background: #fff0ee;
}

.evaluation-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 52px;
  padding: 9px 16px;
  background: #f8fbf9;
  border: 1px solid #e2eee7;
  border-radius: 10px;
}

.evaluation-switch-row :deep(.el-switch) {
  --el-switch-on-color: #126047;
  --el-switch-off-color: #cbd9d1;
}

.evaluation-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 18px;
  border-top: 1px solid #e8f0eb;
}

.evaluation-dialog-actions .el-button {
  min-width: 88px;
  height: 40px;
  padding: 0 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 650;
}

.evaluation-dialog-actions .el-button:not(.el-button--primary) {
  color: #466056;
  background: #fff;
  border-color: #d6e3dc;
}

.evaluation-dialog-actions .el-button:not(.el-button--primary):hover {
  color: #185b44;
  background: #f4faf6;
  border-color: #9fc4af;
}

.evaluation-dialog-actions .el-button.el-button--primary {
  color: #fff;
  background: #126047;
  border-color: #126047;
  box-shadow: 0 5px 12px rgb(18 96 71 / 16%);
}

.evaluation-dialog-actions .el-button.el-button--primary:hover:not(.is-disabled) {
  background: #0f523c;
  border-color: #0f523c;
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
.evaluation-run-table td:nth-child(2) { width: 36%; }
.evaluation-run-table th:nth-child(3),
.evaluation-run-table td:nth-child(3) { width: 16%; }
.evaluation-run-table th:nth-child(4),
.evaluation-run-table td:nth-child(4) { width: 16%; }
.evaluation-run-table th:nth-child(5),
.evaluation-run-table td:nth-child(5) { width: 20%; }
.evaluation-run-table th:nth-child(6),
.evaluation-run-table td:nth-child(6) { width: 78px; }

.evaluation-run-table tbody tr {
  cursor: pointer;
}

.evaluation-run-table tbody tr:hover,
.evaluation-run-table tbody tr.evaluation-run-selected {
  background: #f0f7f4;
}

.evaluation-run-toggle.el-button {
  width: 26px;
  height: 26px;
  color: #536077;
}

.evaluation-run-toggle.el-button:hover {
  color: #185b44;
  background: #e4f0eb;
}

.evaluation-run-toggle :deep(svg) {
  transition: transform 160ms ease;
}

.evaluation-run-toggle[aria-expanded='true'] :deep(svg) {
  transform: rotate(90deg);
}

.evaluation-run-delete.el-button {
  padding: 5px 8px;
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
  grid-template-columns: repeat(6, minmax(0, 1fr));
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
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evaluation-section-heading .evaluation-primary {
    width: 100px;
    min-width: 100px;
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
    grid-template-columns: minmax(180px, 1fr) minmax(140px, 1fr);
  }

  .evaluation-create-form .evaluation-primary {
    grid-column: 1 / -1;
    justify-self: end;
  }
}

@media (max-width: 620px) {
  :deep(.evaluation-case-dialog.el-dialog) {
    width: calc(100vw - 20px) !important;
    max-width: calc(100vw - 20px);
    margin-top: 10px;
  }

  :deep(.evaluation-case-dialog .el-dialog__header) {
    padding: 18px 18px 12px;
  }

  :deep(.evaluation-case-dialog .el-dialog__body) {
    max-height: calc(100vh - 112px);
    padding: 18px 18px 20px;
  }

  :deep(.evaluation-case-dialog .el-dialog__title) {
    font-size: 21px;
  }

  .evaluation-form-array-row,
  .evaluation-source-row {
    grid-template-columns: 1fr;
  }

  .evaluation-form-array-row > .el-button {
    justify-self: end;
    margin-top: 0;
  }

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

  .evaluation-section-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .evaluation-section-heading .evaluation-primary {
    width: 100%;
    min-width: 0;
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

  .evaluation-form-array-row,
  .evaluation-source-row {
    grid-template-columns: 1fr;
  }

  .evaluation-dialog-actions {
    justify-content: stretch;
  }

  .evaluation-dialog-actions .el-button {
    flex: 1;
  }
}
</style>
