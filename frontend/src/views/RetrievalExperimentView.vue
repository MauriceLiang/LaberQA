<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElButton, ElDialog, ElInput, ElInputNumber, ElMessage, ElMessageBox, ElOption, ElSelect, ElSwitch } from 'element-plus'

import {
  createExperiment,
  copyExperiment,
  createRetrievalStrategy,
  deleteExperiment,
  deleteRetrievalStrategy,
  archiveRetrievalExperiment,
  archiveRetrievalStrategy,
  exportRetrievalExperiment,
  getExperiment,
  getExperiments,
  listRetrievalStrategies,
  listRetrievalStrategyVersions,
  previewRetrieval,
  restoreRetrievalExperiment,
  restoreRetrievalStrategy,
  restoreRetrievalStrategyVersion,
  setRetrievalStrategyActive,
  updateRetrievalStrategy,
  type ExperimentConfig,
  type ExperimentConfigResult,
  type ExperimentDetail,
  type ExperimentCaseScope,
  type ExperimentStatus,
  type ExperimentSummary,
  type RetrievalPreview,
  type RetrievalStrategy,
  type RetrievalStrategyPayload,
  type RetrievalStrategyVersion,
} from '@/api/experiments'
import { getErrorMessage } from '@/api/http'
import { getEvaluationCases, type EvaluationCase } from '@/api/evaluations'

const experimentGroups: Array<{ label: string; config: ExperimentConfig }> = [
  { label: 'A', config: { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 } },
  { label: 'B', config: { chunk_size: 400, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 } },
  { label: 'C', config: { chunk_size: 800, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 } },
  { label: 'D', config: { chunk_size: 600, chunk_overlap: 100, top_k: 3, rerank_enabled: false, rerank_top_n: 3, score_threshold: 0.35 } },
  { label: 'E', config: { chunk_size: 600, chunk_overlap: 100, top_k: 8, rerank_enabled: false, rerank_top_n: 8, score_threshold: 0.35 } },
  { label: 'F', config: { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: true, rerank_top_n: 5, score_threshold: 0.35 } },
]

function cloneConfig(config: ExperimentConfig): ExperimentConfig {
  return { ...config }
}

function fallbackStrategies(): RetrievalStrategy[] {
  return experimentGroups.map((group, index) => ({
    id: -(index + 1),
    name: `基线 ${group.label}`,
    description: '内置基线策略',
    builtin_key: `baseline_${group.label.toLowerCase()}`,
    config: cloneConfig(group.config),
    is_builtin: true,
    version: 1,
    is_active: true,
    archived_at: null,
    created_at: '',
    updated_at: '',
  }))
}

const experiments = ref<ExperimentSummary[]>([])
const page = ref(1)
const pageSize = 10
const total = ref(0)
const pages = ref(0)
const loadingList = ref(false)
const listError = ref('')
const experimentName = ref('')
const answerStyle = ref<'' | 'plain' | 'legal'>('')
const caseScope = ref<ExperimentCaseScope>('BUILTIN_BASELINE')
const evaluationCases = ref<EvaluationCase[]>([])
const selectedCaseIds = ref<number[]>([])
const caseLoading = ref(false)
const caseError = ref('')
const creating = ref(false)
const createError = ref('')
const selectedId = ref<number>()
const detail = ref<ExperimentDetail>()
const loadingDetail = ref(false)
const detailError = ref('')
const expandedConfigIndex = ref<number>()
const detailRequests = new Set<number>()
const strategies = ref<RetrievalStrategy[]>([])
const strategyLoading = ref(false)
const strategyError = ref('')
const selectedStrategyIds = ref<number[]>([])
const strategyEditorVisible = ref(false)
const strategyEditorId = ref<number>()
const strategySaving = ref(false)
const strategyEditorError = ref('')
const strategyVersionVisible = ref(false)
const strategyVersionStrategy = ref<RetrievalStrategy>()
const strategyVersions = ref<RetrievalStrategyVersion[]>([])
const strategyVersionLoading = ref(false)
const strategyVersionError = ref('')
const restoringStrategyVersion = ref<number>()
const strategyDraft = reactive<RetrievalStrategyPayload>({
  name: '',
  description: '',
  config: cloneConfig(experimentGroups[0].config),
})
const previewVisible = ref(false)
const previewQuestion = ref('公司拖欠工资，我应该准备什么材料？')
const previewLoading = ref(false)
const previewError = ref('')
const previewResult = ref<RetrievalPreview>()
const comparisonVisible = ref(false)
const comparisonLoading = ref(false)
const comparisonError = ref('')
const comparisonResults = ref<RetrievalPreview[]>([])
const deletingExperimentId = ref<number>()
const copyingExperimentId = ref<number>()
const archivingExperimentId = ref<number>()
const exportingExperimentId = ref<number>()
let selectionVersion = 0
let pollTimer: ReturnType<typeof setInterval> | undefined

const status = computed(() => detail.value?.status ?? experiments.value.find((item) => item.id === selectedId.value)?.status)
const selectedName = computed(() => detail.value?.name ?? experiments.value.find((item) => item.id === selectedId.value)?.name ?? '')
const isTerminal = (value: ExperimentStatus | undefined) => value === 'COMPLETED' || value === 'FAILED'
const configResults = computed(() => new Map((detail.value?.config_results ?? []).map((item) => [item.config_index, item])))
const selectedConfigResults = computed(() => detail.value?.results.filter((item) => item.config_index === expandedConfigIndex.value) ?? [])
const selectedStrategies = computed(() => strategies.value.filter((item) => item.is_active && !item.archived_at && selectedStrategyIds.value.includes(item.id)))
const availableStrategies = computed(() => strategies.value.filter((item) => item.is_active && !item.archived_at))
const activeStrategy = computed(() => selectedStrategies.value[0] ?? availableStrategies.value[0])
const strategyEditorTitle = computed(() => strategyEditorId.value === undefined ? '新建检索策略' : '编辑检索策略')
const strategyDraftWarning = computed(() => {
  if (strategyDraft.config.score_threshold >= 0.8) return '阈值较高，可能过滤掉有用材料。建议先试跑确认。'
  if (strategyDraft.config.top_k >= 12) return 'Top-k 较大，可能增加响应耗时和上下文长度。'
  if (!strategyDraft.config.rerank_enabled) return '关闭重排会减少处理步骤，但可能降低候选材料的排序准确性。'
  return ''
})
const detailConfigGroups = computed(() => (detail.value?.config_results ?? []).map((result, index) => ({
  label: detail.value?.config_names?.[index] ?? experimentGroups[index]?.label ?? `配置 ${index + 1}`,
  config: result.config,
})))
const comparisonStrategies = computed(() => selectedStrategies.value.slice(0, 2))

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
    const result = await getExperiments({ page: page.value, size: pageSize, include_archived: true })
    experiments.value = result.items
    total.value = result.total
    pages.value = result.pages
    if (selectedId.value === undefined && result.items.length > 0) {
      const activeItems = result.items.filter((item) => !item.archived_at)
      const latest = activeItems.find((item) => !isTerminal(item.status)) ?? activeItems[0]
      if (latest) selectExperiment(latest)
    }
  } catch (error) {
    listError.value = getErrorMessage(error)
  } finally {
    loadingList.value = false
  }
}

async function loadEvaluationCases() {
  caseLoading.value = true
  caseError.value = ''
  try {
    const result = await getEvaluationCases({
      page: 1,
      size: 100,
      status: 'ACTIVE',
      include_archived: false,
    })
    evaluationCases.value = result.items
  } catch (error) {
    caseError.value = getErrorMessage(error)
  } finally {
    caseLoading.value = false
  }
}

function updateCaseScope(value: ExperimentCaseScope) {
  caseScope.value = value
  if (value !== 'SELECTED') selectedCaseIds.value = []
}

async function loadStrategies() {
  strategyLoading.value = true
  strategyError.value = ''
  try {
    strategies.value = await listRetrievalStrategies({ include_archived: true })
  } catch (error) {
    // Keep the page usable while an older backend is being upgraded.
    strategies.value = fallbackStrategies()
    strategyError.value = getErrorMessage(error)
  } finally {
    if (strategies.value.length > 0 && selectedStrategyIds.value.length === 0) {
      selectedStrategyIds.value = availableStrategies.value.map((item) => item.id)
    }
    strategyLoading.value = false
  }
}

function isStrategySelected(id: number) {
  return selectedStrategyIds.value.includes(id)
}

function toggleStrategy(id: number) {
  const strategy = strategies.value.find((item) => item.id === id)
  if (!strategy?.is_active || strategy.archived_at) return
  selectedStrategyIds.value = isStrategySelected(id)
    ? selectedStrategyIds.value.filter((item) => item !== id)
    : [...selectedStrategyIds.value, id]
}

const strategyActionId = ref<number>()

function replaceStrategy(strategy: RetrievalStrategy) {
  const index = strategies.value.findIndex((item) => item.id === strategy.id)
  if (index >= 0) strategies.value.splice(index, 1, strategy)
  else strategies.value.push(strategy)
}

async function toggleStrategyActive(strategy: RetrievalStrategy) {
  if (strategy.is_builtin || strategy.archived_at) return
  strategyActionId.value = strategy.id
  try {
    const updated = await setRetrievalStrategyActive(strategy.id, !strategy.is_active)
    replaceStrategy(updated)
    if (!updated.is_active) {
      selectedStrategyIds.value = selectedStrategyIds.value.filter((id) => id !== updated.id)
    }
    ElMessage.success(updated.is_active ? '策略已启用' : '策略已停用')
  } catch (error) {
    strategyError.value = getErrorMessage(error)
  } finally {
    strategyActionId.value = undefined
  }
}

async function archiveStrategy(strategy: RetrievalStrategy) {
  if (strategy.is_builtin || strategy.archived_at) return
  try {
    await ElMessageBox.confirm(
      `归档“${strategy.name}”后，它不会出现在可运行的策略选择中，历史实验结果不受影响。`,
      '归档检索策略',
      { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' },
    )
    strategyActionId.value = strategy.id
    const archived = await archiveRetrievalStrategy(strategy.id)
    replaceStrategy(archived)
    selectedStrategyIds.value = selectedStrategyIds.value.filter((id) => id !== archived.id)
    ElMessage.success('策略已归档')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') strategyError.value = getErrorMessage(error)
  } finally {
    strategyActionId.value = undefined
  }
}

async function restoreStrategy(strategy: RetrievalStrategy) {
  if (strategy.is_builtin || !strategy.archived_at) return
  strategyActionId.value = strategy.id
  try {
    const restored = await restoreRetrievalStrategy(strategy.id)
    replaceStrategy(restored)
    ElMessage.success('策略已恢复')
  } catch (error) {
    strategyError.value = getErrorMessage(error)
  } finally {
    strategyActionId.value = undefined
  }
}

function openStrategyEditor(strategy?: RetrievalStrategy) {
  strategyEditorId.value = strategy?.is_builtin ? undefined : strategy?.id
  strategyEditorError.value = ''
  strategyDraft.name = strategy ? `${strategy.name}${strategy.is_builtin ? ' · 副本' : ''}` : ''
  strategyDraft.description = strategy?.description ?? ''
  strategyDraft.config = cloneConfig(strategy?.config ?? experimentGroups[0].config)
  strategyEditorVisible.value = true
}

function resetStrategyDraft() {
  strategyDraft.config = cloneConfig(experimentGroups[0].config)
}

async function saveStrategy() {
  const name = strategyDraft.name.trim()
  if (!name) {
    strategyEditorError.value = '请填写策略名称'
    return
  }
  if (strategyDraft.config.chunk_overlap >= strategyDraft.config.chunk_size) {
    strategyEditorError.value = 'Overlap 必须小于 Chunk Size'
    return
  }
  if (strategyDraft.config.rerank_top_n > strategyDraft.config.top_k) {
    strategyEditorError.value = 'Rerank Top-N 不能大于 Top-k'
    return
  }
  strategySaving.value = true
  strategyEditorError.value = ''
  try {
    const saved = strategyEditorId.value === undefined
      ? await createRetrievalStrategy({
          name,
          description: strategyDraft.description.trim(),
          config: cloneConfig(strategyDraft.config),
        })
      : await updateRetrievalStrategy(strategyEditorId.value, {
          name,
          description: strategyDraft.description.trim(),
          config: cloneConfig(strategyDraft.config),
        })
    const existingIndex = strategies.value.findIndex((item) => item.id === saved.id)
    if (existingIndex >= 0) strategies.value.splice(existingIndex, 1, saved)
    else strategies.value.push(saved)
    if (!selectedStrategyIds.value.includes(saved.id)) {
      selectedStrategyIds.value = [...selectedStrategyIds.value, saved.id]
    }
    strategyEditorVisible.value = false
    ElMessage.success(strategyEditorId.value === undefined ? '策略已创建' : '策略已更新')
  } catch (error) {
    strategyEditorError.value = getErrorMessage(error)
  } finally {
    strategySaving.value = false
  }
}

function copyStrategy(strategy: RetrievalStrategy) {
  openStrategyEditor(strategy)
}

async function openStrategyVersions(strategy: RetrievalStrategy) {
  strategyVersionStrategy.value = strategy
  strategyVersions.value = []
  strategyVersionError.value = ''
  strategyVersionVisible.value = true
  strategyVersionLoading.value = true
  try {
    strategyVersions.value = await listRetrievalStrategyVersions(strategy.id)
  } catch (error) {
    strategyVersionError.value = getErrorMessage(error)
  } finally {
    strategyVersionLoading.value = false
  }
}

async function restoreStrategyVersion(version: RetrievalStrategyVersion) {
  const strategy = strategyVersionStrategy.value
  if (!strategy || strategy.is_builtin) return
  try {
    await ElMessageBox.confirm(
      `恢复版本 ${version.version} 会生成一个新的当前版本，是否继续？`,
      '恢复策略版本',
      { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' },
    )
    restoringStrategyVersion.value = version.version
    const restored = await restoreRetrievalStrategyVersion(strategy.id, version.version)
    replaceStrategy(restored)
    strategyVersionStrategy.value = restored
    strategyVersions.value = await listRetrievalStrategyVersions(restored.id)
    ElMessage.success(`已恢复版本 ${version.version}`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') strategyVersionError.value = getErrorMessage(error)
  } finally {
    restoringStrategyVersion.value = undefined
  }
}

async function removeStrategy(strategy: RetrievalStrategy) {
  if (strategy.is_builtin) return
  try {
    await ElMessageBox.confirm(
      `删除“${strategy.name}”后，已完成的实验结果不会受影响。`,
      '删除检索策略',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteRetrievalStrategy(strategy.id)
    strategies.value = strategies.value.filter((item) => item.id !== strategy.id)
    selectedStrategyIds.value = selectedStrategyIds.value.filter((id) => id !== strategy.id)
    ElMessage.success('策略已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') strategyError.value = getErrorMessage(error)
  }
}

async function runPreview(strategy = activeStrategy.value) {
  if (!strategy) {
    previewError.value = '请先选择一个检索策略'
    return
  }
  const question = previewQuestion.value.trim()
  if (!question) {
    previewError.value = '请输入要试跑的问题'
    previewVisible.value = true
    return
  }
  previewVisible.value = true
  previewLoading.value = true
  previewError.value = ''
  previewResult.value = undefined
  try {
    previewResult.value = await previewRetrieval({
      question,
      answer_style: answerStyle.value || 'plain',
      config: cloneConfig(strategy.config),
    })
  } catch (error) {
    previewError.value = getErrorMessage(error)
  } finally {
    previewLoading.value = false
  }
}

async function runComparison() {
  if (comparisonStrategies.value.length < 2) {
    ElMessage.warning('请至少选择两条策略进行对比')
    return
  }
  comparisonVisible.value = true
  comparisonLoading.value = true
  comparisonError.value = ''
  comparisonResults.value = []
  try {
    comparisonResults.value = await Promise.all(
      comparisonStrategies.value.map((strategy) => previewRetrieval({
        question: previewQuestion.value.trim() || '公司拖欠工资，我应该准备什么材料？',
        answer_style: answerStyle.value || 'plain',
        config: cloneConfig(strategy.config),
      })),
    )
  } catch (error) {
    comparisonError.value = getErrorMessage(error)
  } finally {
    comparisonLoading.value = false
  }
}

async function submitExperiment() {
  const name = experimentName.value.trim()
  if (!name) {
    createError.value = '请填写实验名称'
    return
  }
  if (selectedStrategies.value.length === 0) {
    createError.value = '至少选择一个检索策略'
    return
  }
  if (caseScope.value === 'SELECTED' && selectedCaseIds.value.length === 0) {
    createError.value = '自定义问题集至少选择一个评测用例'
    return
  }

  creating.value = true
  createError.value = ''
  try {
    const selected = selectedStrategies.value
    const job = await createExperiment({
      name,
      case_ids: caseScope.value === 'SELECTED' ? selectedCaseIds.value : null,
      case_scope: caseScope.value,
      answer_style: answerStyle.value || 'plain',
      configs: selected.map((strategy) => cloneConfig(strategy.config)),
      ...(selected.every((strategy) => strategy.id > 0)
        ? { config_names: selected.map((strategy) => strategy.name) }
        : {}),
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

async function removeExperiment(item: ExperimentSummary) {
  if (item.status === 'PENDING' || item.status === 'RUNNING') {
    ElMessage.warning('运行中的实验完成后才能删除')
    return
  }
  try {
    await ElMessageBox.confirm(
      `删除“${item.name}”后，实验记录和隔离索引都会被清理。`,
      '删除实验记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    deletingExperimentId.value = item.id
    await deleteExperiment(item.id)
    if (selectedId.value === item.id) {
      stopPolling()
      selectedId.value = undefined
      detail.value = undefined
    }
    await loadExperiments()
    ElMessage.success('实验记录已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') listError.value = getErrorMessage(error)
  } finally {
    deletingExperimentId.value = undefined
  }
}

async function archiveExperimentRecord(item: ExperimentSummary) {
  if (item.status === 'PENDING' || item.status === 'RUNNING' || item.archived_at) {
    ElMessage.warning('只有已完成或失败且未归档的实验才能归档')
    return
  }
  try {
    await ElMessageBox.confirm(
      `归档“${item.name}”后，它会从默认实验列表中隐藏，历史结果仍可恢复查看。`,
      '归档实验记录',
      { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' },
    )
    archivingExperimentId.value = item.id
    const archived = await archiveRetrievalExperiment(item.id)
    const index = experiments.value.findIndex((current) => current.id === archived.id)
    if (index >= 0) experiments.value.splice(index, 1, archived)
    if (selectedId.value === item.id) await loadDetail(item.id)
    ElMessage.success('实验记录已归档')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') listError.value = getErrorMessage(error)
  } finally {
    archivingExperimentId.value = undefined
  }
}

async function restoreExperimentRecord(item: ExperimentSummary) {
  if (!item.archived_at) return
  archivingExperimentId.value = item.id
  try {
    const restored = await restoreRetrievalExperiment(item.id)
    const index = experiments.value.findIndex((current) => current.id === restored.id)
    if (index >= 0) experiments.value.splice(index, 1, restored)
    ElMessage.success('实验记录已恢复')
  } catch (error) {
    listError.value = getErrorMessage(error)
  } finally {
    archivingExperimentId.value = undefined
  }
}

async function exportExperimentRecord(item: ExperimentSummary) {
  exportingExperimentId.value = item.id
  try {
    const csv = await exportRetrievalExperiment(item.id)
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${item.name || `检索实验-${item.id}`}.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('结果已导出')
  } catch (error) {
    listError.value = getErrorMessage(error)
  } finally {
    exportingExperimentId.value = undefined
  }
}

async function duplicateExperiment(item: ExperimentSummary) {
  try {
    copyingExperimentId.value = item.id
    const job = await copyExperiment(item.id, `${item.name} · 副本`)
    stopPolling()
    selectionVersion += 1
    selectedId.value = job.experiment_id
    detail.value = undefined
    expandedConfigIndex.value = undefined
    if (!isTerminal(job.status)) startPolling(job.experiment_id)
    void loadDetail(job.experiment_id, true)
    await loadExperiments()
    ElMessage.success('已复制为新实验并开始运行')
  } catch (error) {
    listError.value = getErrorMessage(error)
  } finally {
    copyingExperimentId.value = undefined
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

onMounted(() => {
  void loadExperiments()
  void loadStrategies()
  void loadEvaluationCases()
})

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
        <p>先用单条问题验证检索链路，再批量对比选中的策略和命中结果。</p>
      </div>
      <span class="experiment-count">已选 {{ selectedStrategies.length }} 组策略</span>
    </header>

    <section class="experiment-panel experiment-workbench" aria-labelledby="strategy-workbench-title">
      <div class="experiment-heading">
        <div>
          <h2 id="strategy-workbench-title">策略工作台</h2>
          <p>选择策略后可直接试跑；内置策略只能复制，复制后可以按业务资料调整。</p>
        </div>
        <div class="experiment-heading-actions">
          <ElButton class="experiment-secondary" type="primary" plain :disabled="comparisonStrategies.length < 2" @click="runComparison">对比已选</ElButton>
          <ElButton class="experiment-secondary" type="primary" plain @click="openStrategyEditor()">新建策略</ElButton>
        </div>
      </div>
      <p v-if="strategyError" class="experiment-inline-hint" role="status">策略服务暂不可用，当前使用页面内置基线：{{ strategyError }}</p>
      <div class="strategy-grid" :aria-busy="strategyLoading">
        <article
          v-for="strategy in strategies"
          :key="strategy.id"
          class="strategy-card"
          :class="{
            'strategy-card-selected': isStrategySelected(strategy.id),
            'strategy-card-disabled': !strategy.is_active || strategy.archived_at,
          }"
        >
          <label class="strategy-card-select">
            <input
              type="checkbox"
              :checked="isStrategySelected(strategy.id)"
              :disabled="!strategy.is_active || !!strategy.archived_at"
              :aria-label="`选择策略 ${strategy.name}`"
              @change="toggleStrategy(strategy.id)"
            />
            <span>{{ strategy.name }} <em>v{{ strategy.version }}</em><em v-if="strategy.archived_at"> · 已归档</em><em v-else-if="!strategy.is_active"> · 已停用</em></span>
          </label>
          <p>{{ strategy.description }}</p>
          <dl class="strategy-card-meta">
            <div><dt>分块</dt><dd>{{ strategy.config.chunk_size }} / {{ strategy.config.chunk_overlap }}</dd></div>
            <div><dt>召回</dt><dd>{{ strategy.config.top_k }}</dd></div>
            <div><dt>重排</dt><dd>{{ strategy.config.rerank_enabled ? '开' : '关' }}</dd></div>
            <div><dt>阈值</dt><dd>{{ strategy.config.score_threshold.toFixed(2) }}</dd></div>
          </dl>
          <div class="strategy-card-actions">
            <ElButton text :disabled="!strategy.is_active || !!strategy.archived_at" @click="runPreview(strategy)">试跑</ElButton>
            <ElButton text @click="copyStrategy(strategy)">{{ strategy.is_builtin ? '复制' : '编辑' }}</ElButton>
            <ElButton text @click="openStrategyVersions(strategy)">版本</ElButton>
            <ElButton
              v-if="!strategy.is_builtin && !strategy.archived_at"
              text
              :loading="strategyActionId === strategy.id"
              @click="toggleStrategyActive(strategy)"
            >{{ strategy.is_active ? '停用' : '启用' }}</ElButton>
            <ElButton
              v-if="!strategy.is_builtin"
              text
              :loading="strategyActionId === strategy.id"
              @click="strategy.archived_at ? restoreStrategy(strategy) : archiveStrategy(strategy)"
            >{{ strategy.archived_at ? '恢复' : '归档' }}</ElButton>
            <ElButton v-if="!strategy.is_builtin" text type="danger" @click="removeStrategy(strategy)">删除</ElButton>
          </div>
        </article>
        <p v-if="!strategyLoading && strategies.length === 0" class="experiment-empty">暂无策略，请先新建一条策略。</p>
      </div>
      <div class="quick-preview-bar">
        <div>
          <strong>快速试跑</strong>
          <span>使用当前选中的第一条策略验证一个真实问题</span>
        </div>
        <input v-model="previewQuestion" class="quick-preview-input" maxlength="2000" placeholder="例如：公司拖欠工资，我应该准备什么材料？" @keyup.enter="runPreview()" />
        <ElButton class="experiment-primary" :disabled="!activeStrategy || previewLoading" :loading="previewLoading" @click="runPreview()">试跑 1 条</ElButton>
      </div>
    </section>

    <section class="experiment-panel" aria-labelledby="experiment-config-title">
      <div class="experiment-heading">
        <div>
          <h2 id="experiment-config-title">内置基线参数参考</h2>
          <p>批量实验会为每条选中的策略独立构建分块索引，避免影响生产检索。</p>
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
            <p>每次实验运行当前选中的策略和评测用例</p>
          </div>
        </div>
        <form class="experiment-create-form" @submit.prevent="submitExperiment">
          <label>
            <span>实验名称</span>
            <ElInput
              v-model="experimentName"
              class="experiment-create-input"
              maxlength="100"
              required
              placeholder="例如：检索参数对比-20260915"
              aria-label="实验名称"
            />
          </label>
          <label>
            <span>评测问题集</span>
            <ElSelect
              :model-value="caseScope"
              class="experiment-create-select"
              aria-label="评测问题集"
              @update:model-value="updateCaseScope"
            >
              <ElOption label="官方基线问题集" value="BUILTIN_BASELINE" />
              <ElOption label="全部活动用例" value="ALL_ACTIVE" />
              <ElOption label="自定义选择" value="SELECTED" />
            </ElSelect>
          </label>
          <label v-if="caseScope === 'SELECTED'" class="experiment-case-select-label">
            <span>选择评测用例</span>
            <ElSelect
              v-model="selectedCaseIds"
              class="experiment-create-select"
              multiple
              filterable
              collapse-tags
              :loading="caseLoading"
              placeholder="请选择一个或多个用例"
              aria-label="选择评测用例"
            >
              <ElOption
                v-for="item in evaluationCases"
                :key="item.id"
                :label="`#${item.id} ${item.topic}`"
                :value="item.id"
              />
            </ElSelect>
          </label>
          <label>
            <span>回答风格</span>
            <ElSelect v-model="answerStyle" class="experiment-create-select" placeholder="使用默认值" aria-label="回答风格">
              <ElOption label="使用默认值" value="" />
              <ElOption label="通俗版" value="plain" />
              <ElOption label="严谨版" value="legal" />
            </ElSelect>
          </label>
          <ElButton class="experiment-primary" type="primary" native-type="submit" :loading="creating" :disabled="creating">
            {{ creating ? '创建中…' : '创建实验' }}
          </ElButton>
        </form>
      </div>
      <p v-if="caseError" class="experiment-error" role="alert">评测用例加载失败：{{ caseError }}</p>
      <p v-if="createError" class="experiment-error" role="alert">{{ createError }}</p>
    </section>

    <section class="experiment-panel" aria-labelledby="experiment-list-title">
      <div class="experiment-heading">
        <div>
          <h2 id="experiment-list-title">实验记录</h2>
          <p>选择实验查看进度；运行中的任务每 2 秒更新一次。归档记录可恢复或导出。</p>
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
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in experiments"
              :key="item.id"
              :class="{
                'experiment-row-selected': item.id === selectedId,
                'experiment-row-archived': item.archived_at,
              }"
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
              <td>
                <button class="experiment-link" type="button" @click.stop="selectExperiment(item)">{{ item.name }}</button>
                <span v-if="item.archived_at" class="experiment-archived-label">已归档</span>
              </td>
              <td>
                <span class="experiment-status-inline" :class="statusClass(item.status)">
                  <i aria-hidden="true" />{{ formatStatus(item.status) }}
                </span>
              </td>
              <td>{{ item.progress_current }} / {{ item.progress_total }}</td>
              <td>{{ formatCreatedAt(item.created_at) }}</td>
              <td>
                <ElButton
                  class="experiment-table-action"
                  text
                  :loading="exportingExperimentId === item.id"
                  :disabled="item.status === 'PENDING' || item.status === 'RUNNING'"
                  @click.stop="exportExperimentRecord(item)"
                >导出</ElButton>
                <ElButton
                  class="experiment-table-action"
                  text
                  :loading="archivingExperimentId === item.id"
                  :disabled="item.status === 'PENDING' || item.status === 'RUNNING'"
                  @click.stop="item.archived_at ? restoreExperimentRecord(item) : archiveExperimentRecord(item)"
                >{{ item.archived_at ? '恢复' : '归档' }}</ElButton>
                <ElButton
                  class="experiment-table-action"
                  text
                  :loading="copyingExperimentId === item.id"
                  @click.stop="duplicateExperiment(item)"
                >复制</ElButton>
                <ElButton
                  class="experiment-table-action"
                  text
                  type="danger"
                  :loading="deletingExperimentId === item.id"
                  :disabled="item.status === 'PENDING' || item.status === 'RUNNING'"
                  @click.stop="removeExperiment(item)"
                >删除</ElButton>
              </td>
            </tr>
            <tr v-if="!loadingList && experiments.length === 0">
              <td colspan="6" class="experiment-empty">暂无检索实验。先在上方试跑，再创建批量实验。</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="experiment-pagination">
        <span>共 {{ total }} 条，第 {{ page }} / {{ pages || 1 }} 页</span>
        <ElButton native-type="button" :disabled="page <= 1 || loadingList" @click="changePage(page - 1)">上一页</ElButton>
        <ElButton native-type="button" :disabled="page >= pages || loadingList" @click="changePage(page + 1)">下一页</ElButton>
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
            当前最优配置：<strong>{{ detailConfigGroups[detail.best_config_index]?.label ?? '#' + detail.best_config_index }}</strong>
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
                v-for="(group, index) in detailConfigGroups"
                :key="group.label + index"
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
          <h3>{{ detailConfigGroups[expandedConfigIndex]?.label }} 组逐题检索结果（{{ selectedConfigResults.length }}）</h3>
          <p class="experiment-muted">以下段号来自该组重新切分后的实验 Chunk，不对应原评测集中的来源段号。</p>
          <p v-if="selectedConfigResults.length === 0" class="experiment-muted">此配置尚无逐题结果。</p>
          <details v-for="(result, resultIndex) in selectedConfigResults" :key="result.case_id" class="experiment-case" :open="resultIndex === 0">
            <summary class="experiment-case-summary">
              <span class="experiment-case-chevron" aria-hidden="true">⌄</span>
              <strong>{{ detailConfigGroups[expandedConfigIndex]?.label }} 组逐题结果</strong>
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

    <ElDialog v-model="strategyEditorVisible" :title="strategyEditorTitle" width="640px" class="experiment-dialog">
      <form class="strategy-editor" @submit.prevent="saveStrategy">
        <label>
          <span>策略名称</span>
          <ElInput v-model="strategyDraft.name" maxlength="100" placeholder="例如：劳动合同高召回" />
        </label>
        <label>
          <span>使用说明</span>
          <ElInput v-model="strategyDraft.description" maxlength="255" placeholder="说明这组参数适合什么问题" />
        </label>
        <div class="strategy-editor-grid">
          <label><span>Chunk Size</span><ElInputNumber v-model="strategyDraft.config.chunk_size" :min="100" :max="2000" :step="50" controls-position="right" /></label>
          <label><span>Overlap</span><ElInputNumber v-model="strategyDraft.config.chunk_overlap" :min="0" :max="500" :step="10" controls-position="right" /></label>
          <label><span>Top-k</span><ElInputNumber v-model="strategyDraft.config.top_k" :min="1" :max="20" controls-position="right" /></label>
          <label><span>Rerank Top-N</span><ElInputNumber v-model="strategyDraft.config.rerank_top_n" :min="1" :max="20" controls-position="right" /></label>
          <label><span>阈值</span><ElInputNumber v-model="strategyDraft.config.score_threshold" :min="0" :max="1" :step="0.05" :precision="2" controls-position="right" /></label>
          <label class="strategy-editor-switch"><span>启用重排</span><ElSwitch v-model="strategyDraft.config.rerank_enabled" /></label>
        </div>
        <p class="experiment-inline-hint">Overlap 必须小于 Chunk Size；Rerank Top-N 不能大于 Top-k。</p>
        <p v-if="strategyDraftWarning" class="experiment-warning">{{ strategyDraftWarning }}</p>
        <p v-if="strategyEditorError" class="experiment-error" role="alert">{{ strategyEditorError }}</p>
        <div class="strategy-editor-actions">
          <ElButton text native-type="button" @click="resetStrategyDraft">恢复默认参数</ElButton>
          <ElButton native-type="button" @click="strategyEditorVisible = false">取消</ElButton>
          <ElButton class="experiment-primary" type="primary" native-type="submit" :loading="strategySaving">保存策略</ElButton>
        </div>
      </form>
    </ElDialog>

    <ElDialog
      v-model="strategyVersionVisible"
      :title="`${strategyVersionStrategy?.name ?? '检索策略'} · 版本记录`"
      width="720px"
      class="experiment-dialog"
    >
      <p v-if="strategyVersionError" class="experiment-error" role="alert">{{ strategyVersionError }}</p>
      <p v-if="strategyVersionLoading" class="experiment-muted">正在读取版本记录…</p>
      <div v-else-if="strategyVersions.length === 0" class="experiment-empty">暂无版本记录。</div>
      <div v-else class="strategy-version-list">
        <article v-for="version in strategyVersions" :key="version.id" class="strategy-version-item">
          <div>
            <strong>版本 {{ version.version }}</strong>
            <span>{{ formatCreatedAt(version.created_at) }} · {{ version.name }}</span>
            <p>{{ version.description || '未填写说明' }}</p>
          </div>
          <ElButton
            v-if="!strategyVersionStrategy?.is_builtin && version.version !== strategyVersionStrategy?.version"
            text
            :loading="restoringStrategyVersion === version.version"
            @click="restoreStrategyVersion(version)"
          >恢复</ElButton>
          <span v-else class="strategy-version-current">当前版本</span>
        </article>
      </div>
    </ElDialog>

    <ElDialog v-model="previewVisible" title="单条试跑与检索链路" width="820px" class="experiment-dialog">
      <div class="preview-dialog-body">
        <ElInput v-model="previewQuestion" type="textarea" :rows="2" maxlength="2000" placeholder="输入一个你想验证的问题" />
        <div class="preview-dialog-actions">
          <span v-if="activeStrategy">当前策略：{{ activeStrategy.name }}</span>
          <ElButton class="experiment-primary" type="primary" :loading="previewLoading" :disabled="!activeStrategy" @click="runPreview()">重新试跑</ElButton>
        </div>
        <p v-if="previewError" class="experiment-error" role="alert">{{ previewError }}</p>
        <div v-if="previewLoading" class="preview-loading">正在执行检索链路…</div>
        <template v-if="previewResult">
          <div class="preview-answer" :class="{ 'preview-answer-refused': previewResult.refused }">
            <div class="preview-answer-heading"><strong>{{ previewResult.refused ? '证据门控结果：建议拒答' : '试跑回答' }}</strong><span>{{ previewResult.retrieval_ms }} ms</span></div>
            <p>{{ previewResult.answer }}</p>
          </div>
          <div class="preview-trace">
            <h3>链路检查</h3>
            <ol>
              <li v-for="stage in previewResult.trace" :key="stage.stage">
                <span class="preview-trace-dot" :class="`preview-trace-${stage.status}`" aria-hidden="true" />
                <div><strong>{{ stage.stage }}</strong><span>{{ stage.detail }}</span></div>
              </li>
            </ol>
          </div>
          <details class="preview-sources" :open="previewResult.retrieved_sources.length > 0">
            <summary>召回片段（{{ previewResult.retrieved_sources.length }}）</summary>
            <ul v-if="previewResult.retrieved_sources.length > 0">
              <li v-for="source in previewResult.retrieved_sources" :key="source.chunk_id">
                <strong>{{ source.file_name }} · 第 {{ source.chunk_no }} 段</strong>
                <span>排序 {{ source.rank_no }} · 检索分 {{ source.retrieval_score.toFixed(3) }}</span>
                <p>{{ source.content }}</p>
              </li>
            </ul>
            <p v-else class="experiment-muted">没有召回片段，建议降低阈值或检查资料覆盖范围。</p>
          </details>
        </template>
      </div>
    </ElDialog>

    <ElDialog v-model="comparisonVisible" title="策略 A/B 对比" width="900px" class="experiment-dialog">
      <div class="comparison-dialog-body">
        <p class="experiment-inline-hint">对比问题：{{ previewQuestion.trim() || '公司拖欠工资，我应该准备什么材料？' }}</p>
        <div v-if="comparisonLoading" class="preview-loading">正在并行执行两条策略…</div>
        <p v-if="comparisonError" class="experiment-error" role="alert">{{ comparisonError }}</p>
        <div v-if="comparisonResults.length > 0" class="comparison-grid">
          <article v-for="(result, index) in comparisonResults" :key="`${result.config.chunk_size}-${index}`" class="comparison-card">
            <header>
              <strong>{{ comparisonStrategies[index]?.name ?? `策略 ${index + 1}` }}</strong>
              <span>{{ result.retrieval_ms }} ms · 引用 {{ result.citations.length }}</span>
            </header>
            <p class="comparison-result-status" :class="{ 'comparison-result-refused': result.refused }">{{ result.refused ? '证据不足，建议拒答' : '完成回答' }}</p>
            <p class="comparison-answer">{{ result.answer }}</p>
            <details class="preview-sources">
              <summary>召回片段（{{ result.retrieved_sources.length }}）</summary>
              <ul v-if="result.retrieved_sources.length > 0">
                <li v-for="source in result.retrieved_sources" :key="source.chunk_id">
                  <strong>{{ source.file_name }} · 第 {{ source.chunk_no }} 段</strong>
                  <span>检索分 {{ source.retrieval_score.toFixed(3) }}</span>
                </li>
              </ul>
            </details>
          </article>
        </div>
      </div>
    </ElDialog>
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

.experiment-heading-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
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
  box-shadow: none;
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

.experiment-create-input,
.experiment-create-select {
  flex: 1 1 auto;
  min-width: 0;
}

.experiment-case-select-label {
  grid-column: span 2;
}

.experiment-create-input :deep(.el-input__wrapper),
.experiment-create-select :deep(.el-select__wrapper) {
  min-height: 38px;
  padding: 0 10px;
  color: #354257;
  border: 1px solid #d8e0da;
  border-radius: 7px;
  box-shadow: none;
  font: inherit;
}

.experiment-create-input :deep(.el-input__inner) {
  color: #354257;
  font: inherit;
}

.experiment-create-input :deep(.el-input__inner::placeholder),
.experiment-create-select :deep(.el-select__placeholder) {
  color: #a0a9b5;
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
.experiment-list-table td:nth-child(5) { width: 18%; }
.experiment-list-table th:nth-child(6),
.experiment-list-table td:nth-child(6) { width: 12%; }

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

.experiment-row-archived {
  opacity: 0.72;
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

.experiment-archived-label {
  margin-left: 6px;
  padding: 2px 5px;
  color: #758195;
  background: #f1f3f2;
  border-radius: 4px;
  font-size: 10px;
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

.experiment-secondary {
  min-height: 34px;
  padding: 0 13px;
  color: #126047 !important;
  background: #eff7f2 !important;
  border-color: #a9c8b9 !important;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 650;
}

.experiment-secondary:hover:not(.is-disabled),
.experiment-secondary:focus:not(.is-disabled),
.experiment-secondary:active:not(.is-disabled) {
  color: #0f523c !important;
  background: #e4f2ea !important;
  border-color: #8fc0ab !important;
  box-shadow: 0 4px 10px rgb(18 96 71 / 10%);
}

.experiment-secondary.is-disabled,
.experiment-secondary.is-disabled:hover {
  color: #9bb4a7 !important;
  background: #f3f7f5 !important;
  border-color: #dbe7e0 !important;
  box-shadow: none;
}

.experiment-inline-hint {
  margin: 0 0 9px;
  color: #8793a4;
  font-size: 12px;
  line-height: 1.5;
}

.experiment-warning {
  margin: -6px 0 0;
  color: #a47726;
  font-size: 12px;
  line-height: 1.5;
}

.strategy-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.strategy-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: 12px;
  background: #fbfdfc;
  border: 1px solid #e2ebe6;
  border-radius: 8px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.strategy-card-selected {
  border-color: #8fc0ab;
  box-shadow: 0 3px 12px rgb(18 96 71 / 8%);
}

.strategy-card-disabled {
  opacity: 0.68;
  background: #f5f7f6;
}

.strategy-card-select {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #20352d;
  font-size: 13px;
  font-weight: 700;
}

.strategy-card-select input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: #126047;
}

.strategy-card-select em {
  color: #8a9692;
  font-size: 10px;
  font-style: normal;
  font-weight: 500;
}

.strategy-version-list {
  display: grid;
  gap: 8px;
}

.strategy-version-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: #fafcfb;
  border: 1px solid #e2ebe6;
  border-radius: 7px;
}

.strategy-version-item > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.strategy-version-item strong {
  color: #315447;
  font-size: 12px;
}

.strategy-version-item span,
.strategy-version-item p {
  overflow: hidden;
  margin: 0;
  color: #8793a4;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strategy-version-current {
  flex: 0 0 auto;
  color: #26705d !important;
  font-weight: 650;
}

.strategy-card p {
  min-height: 34px;
  margin: 8px 0;
  color: #7a8798;
  font-size: 11px;
  line-height: 1.5;
}

.strategy-card-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 5px;
  margin: 0;
}

.strategy-card-meta div {
  min-width: 0;
  padding: 5px 6px;
  background: #f2f7f4;
  border-radius: 5px;
}

.strategy-card-meta dt {
  color: #8793a4;
  font-size: 10px;
}

.strategy-card-meta dd {
  overflow: hidden;
  margin: 2px 0 0;
  color: #315447;
  font-size: 11px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strategy-card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
  margin-top: 8px;
}

.strategy-card-actions :deep(.el-button) {
  padding: 2px 5px;
  font-size: 11px;
}

.quick-preview-bar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 104px;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e7ece9;
}

.quick-preview-bar > div:first-child {
  display: grid;
  gap: 3px;
  color: #2d463b;
  font-size: 12px;
  white-space: nowrap;
}

.quick-preview-bar > div:first-child span {
  color: #8a95a5;
  font-size: 11px;
}

.quick-preview-input {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  color: #354257;
  background: #fff;
  border: 1px solid #d8e4dd;
  border-radius: 7px;
  outline: 0;
  font: inherit;
  font-size: 12px;
}

.quick-preview-input:focus {
  border-color: #8fc0ab;
  box-shadow: 0 0 0 3px rgb(18 96 71 / 10%);
}

.quick-preview-input::placeholder {
  color: #a0a9b5;
}

.experiment-table-action {
  padding: 2px 4px;
  font-size: 11px;
}

.strategy-editor {
  display: grid;
  gap: 14px;
}

.strategy-editor > label,
.strategy-editor-grid label {
  display: grid;
  gap: 6px;
  color: #536077;
  font-size: 12px;
  font-weight: 650;
}

.strategy-editor-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.strategy-editor-grid :deep(.el-input-number) {
  width: 100%;
}

.strategy-editor-switch {
  align-items: start;
}

.strategy-editor-actions,
.preview-dialog-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 9px;
}

.strategy-editor-actions {
  padding-top: 5px;
  border-top: 1px solid #edf1ee;
}

.preview-dialog-body {
  display: grid;
  gap: 12px;
}

.preview-dialog-actions {
  justify-content: space-between;
  color: #7a8798;
  font-size: 12px;
}

.preview-loading {
  padding: 20px;
  color: #7a8798;
  text-align: center;
}

.preview-answer {
  padding: 12px 14px;
  background: #f1f8f4;
  border: 1px solid #d6e9dd;
  border-radius: 8px;
}

.preview-answer-refused {
  background: #fff8ee;
  border-color: #f0dfbd;
}

.preview-answer-heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #185b44;
  font-size: 12px;
}

.preview-answer-heading span {
  color: #8a95a5;
  font-weight: 400;
}

.preview-answer p {
  margin: 8px 0 0;
  color: #354257;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.preview-trace h3 {
  margin: 0 0 8px;
  color: #20352d;
  font-size: 13px;
}

.preview-trace ol {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.preview-trace li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 9px;
  background: #fafcfb;
  border: 1px solid #edf1ee;
  border-radius: 6px;
}

.preview-trace-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  margin-top: 4px;
  border-radius: 50%;
  background: #199267;
}

.preview-trace-skipped { background: #b7a36c; }
.preview-trace-failed { background: #c45656; }

.preview-trace li div {
  display: grid;
  gap: 2px;
}

.preview-trace li strong {
  color: #354257;
  font-size: 12px;
}

.preview-trace li span:not(.preview-trace-dot) {
  color: #8793a4;
  font-size: 11px;
}

.preview-sources {
  border-top: 1px solid #edf1ee;
  padding-top: 10px;
}

.preview-sources summary {
  color: #26705d;
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
}

.preview-sources ul {
  display: grid;
  gap: 7px;
  margin: 9px 0 0;
  padding: 0;
  list-style: none;
}

.preview-sources li {
  padding: 8px 10px;
  background: #fafcfb;
  border: 1px solid #edf1ee;
  border-radius: 6px;
}

.preview-sources li strong,
.preview-sources li span {
  display: block;
  font-size: 11px;
}

.preview-sources li strong { color: #354257; }
.preview-sources li span { margin-top: 3px; color: #8793a4; }
.preview-sources li p { margin: 5px 0 0; color: #536077; font-size: 11px; line-height: 1.55; }

.comparison-dialog-body {
  display: grid;
  gap: 10px;
}

.comparison-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.comparison-card {
  min-width: 0;
  padding: 12px;
  background: #fbfdfc;
  border: 1px solid #e2ebe6;
  border-radius: 8px;
}

.comparison-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #20352d;
  font-size: 12px;
}

.comparison-card header span {
  color: #8a95a5;
  font-size: 11px;
  white-space: nowrap;
}

.comparison-result-status {
  margin: 10px 0 0;
  color: #168052;
  font-size: 11px;
  font-weight: 650;
}

.comparison-result-refused { color: #a47726; }

.comparison-answer {
  min-height: 74px;
  margin: 7px 0 10px;
  color: #354257;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

@media (max-width: 820px) {
  .strategy-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quick-preview-bar {
    grid-template-columns: 1fr 104px;
  }

  .quick-preview-bar > div:first-child {
    grid-column: 1 / -1;
  }

  .strategy-editor-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .comparison-grid {
    grid-template-columns: 1fr;
  }

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

  .strategy-grid,
  .strategy-editor-grid {
    grid-template-columns: 1fr;
  }

  .experiment-heading-actions {
    align-self: flex-start;
  }

  .quick-preview-bar {
    grid-template-columns: 1fr;
  }

  .quick-preview-bar .experiment-primary {
    width: 100%;
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
