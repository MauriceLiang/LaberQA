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
    <div class="page-intro">
      <div>
        <p class="eyebrow">RETRIEVAL STRATEGY EXPERIMENT</p>
        <h2 id="experiment-title">检索策略实验</h2>
        <p>使用同一批 60 条评测用例，对比六种固定检索配置及其命中的实验 Chunk。</p>
      </div>
      <span class="experiment-count">固定对比 A–F 共 {{ experimentGroups.length }} 组</span>
    </div>

    <section class="experiment-panel" aria-labelledby="experiment-config-title">
      <div class="experiment-heading">
        <div>
          <h3 id="experiment-config-title">固定实验配置</h3>
          <p>每组 overlap 为 100、score threshold 为 0.35；检索索引独立构建。</p>
        </div>
      </div>
      <div class="experiment-table-wrap">
        <table class="experiment-table">
          <thead><tr><th>组别</th><th>Chunk Size</th><th>Overlap</th><th>Top-k</th><th>Rerank</th><th>Rerank Top-N</th><th>阈值</th></tr></thead>
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

    <section class="experiment-panel" aria-labelledby="experiment-create-title">
      <div class="experiment-heading">
        <div>
          <h3 id="experiment-create-title">创建实验</h3>
          <p>每次实验均运行全部 60 条用例和六组固定配置。</p>
        </div>
      </div>
      <form class="experiment-create-form" @submit.prevent="submitExperiment">
        <label>
          实验名称
          <input v-model="experimentName" maxlength="100" required placeholder="例如：检索参数对比-20260915" />
        </label>
        <label>
          回答风格（可选，默认通俗版）
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
      <p v-if="createError" class="experiment-error" role="alert">{{ createError }}</p>
    </section>

    <section class="experiment-panel" aria-labelledby="experiment-list-title">
      <div class="experiment-heading">
        <div>
          <h3 id="experiment-list-title">实验记录</h3>
          <p>后台运行中的实验每 2 秒刷新详情，完成或失败后自动停止轮询。</p>
        </div>
      </div>
      <p v-if="listError" class="experiment-error" role="alert">{{ listError }}</p>
      <div class="experiment-table-wrap" :aria-busy="loadingList">
        <table class="experiment-table experiment-list-table">
          <thead><tr><th>实验</th><th>状态</th><th>进度</th><th>创建时间</th></tr></thead>
          <tbody>
            <tr
              v-for="item in experiments"
              :key="item.id"
              :class="{ 'experiment-row-selected': item.id === selectedId }"
              @click="selectExperiment(item)"
            >
              <td><button class="experiment-link" type="button" @click.stop="selectExperiment(item)">{{ item.name }}</button></td>
              <td>{{ formatStatus(item.status) }}</td>
              <td>{{ item.progress_current }} / {{ item.progress_total }}</td>
              <td>{{ new Date(item.created_at).toLocaleString() }}</td>
            </tr>
            <tr v-if="!loadingList && experiments.length === 0"><td colspan="4" class="experiment-empty">暂无检索实验</td></tr>
          </tbody>
        </table>
      </div>
      <div class="experiment-pagination">
        <span>共 {{ total }} 条，第 {{ page }} / {{ pages || 1 }} 页</span>
        <button :disabled="page <= 1 || loadingList" @click="changePage(page - 1)">上一页</button>
        <button :disabled="page >= pages || loadingList" @click="changePage(page + 1)">下一页</button>
      </div>
    </section>

    <section v-if="selectedId !== undefined" class="experiment-panel" aria-labelledby="experiment-detail-title">
      <div class="experiment-heading">
        <div>
          <p class="eyebrow">EXPERIMENT DETAIL</p>
          <h3 id="experiment-detail-title">{{ selectedName || '检索实验 #' + selectedId }}</h3>
        </div>
        <span class="experiment-status">{{ formatStatus(status) }}</span>
      </div>
      <p v-if="detailError" class="experiment-error" role="alert">{{ detailError }}</p>
      <p v-if="detail?.error_message" class="experiment-error" role="alert">{{ detail.error_message }}</p>
      <p v-if="loadingDetail && !detail" class="experiment-muted">正在读取实验详情…</p>
      <template v-if="detail">
        <div class="experiment-progress" aria-label="实验进度">
          <span>{{ detail.progress_current }} / {{ detail.progress_total }} 题次</span>
          <progress :value="detail.progress_current" :max="Math.max(detail.progress_total, 1)" />
        </div>
        <p class="experiment-signature">
          Embedding 快照：{{ detail.embedding_signature.embedding_provider }} · {{ detail.embedding_signature.embedding_model }} · {{ detail.embedding_signature.embedding_dimension }} 维
        </p>
        <p v-if="detail.best_config_index !== null" class="experiment-best" role="status">
          当前最优配置：{{ experimentGroups[detail.best_config_index]?.label ?? '#' + detail.best_config_index }}
        </p>
        <div v-else-if="detail.status === 'COMPLETED'" class="experiment-muted">没有可比较的完整配置结果。</div>

        <div class="experiment-table-wrap">
          <table class="experiment-table experiment-results-table">
            <thead><tr><th>配置</th><th>Chunk / Top-k / Rerank</th><th>引用命中率</th><th>正确率</th><th>拒答率</th><th>平均检索耗时</th><th>状态</th></tr></thead>
            <tbody>
              <tr
                v-for="(group, index) in experimentGroups"
                :key="group.label"
                :class="{
                  'experiment-row-selected': index === expandedConfigIndex,
                  'experiment-row-best': index === detail.best_config_index,
                }"
              >
                <th scope="row">
                  <button class="experiment-link" type="button" :aria-expanded="index === expandedConfigIndex" @click="chooseConfig(index)">
                    {{ group.label }}{{ index === detail.best_config_index ? ' · 最优' : '' }}
                  </button>
                </th>
                <td>{{ group.config.chunk_size }} / {{ group.config.top_k }} / {{ group.config.rerank_enabled ? '开启' : '关闭' }}</td>
                <td>{{ formatRate(configResult(index)?.citation_hit_rate) }}</td>
                <td>{{ formatRate(configResult(index)?.accuracy) }}</td>
                <td>{{ formatRate(configResult(index)?.reject_rate) }}</td>
                <td>{{ formatDuration(configResult(index)?.avg_retrieval_ms) }}</td>
                <td>{{ configStatus(index) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="expandedConfigIndex !== undefined" class="experiment-cases">
          <h4>{{ experimentGroups[expandedConfigIndex]?.label }} 组逐题检索结果（{{ selectedConfigResults.length }}）</h4>
          <p class="experiment-muted">以下段号来自该组重新切分后的实验 Chunk，不对应原评测集中的来源段号。</p>
          <p v-if="selectedConfigResults.length === 0" class="experiment-muted">此配置尚无逐题结果。</p>
          <article v-for="result in selectedConfigResults" :key="result.case_id" class="experiment-case">
            <div class="experiment-case-heading">
              <strong>用例 #{{ result.case_id }}</strong>
              <span :class="result.status === 'FAILED' ? 'experiment-failed' : 'experiment-completed'">{{ result.status === 'FAILED' ? '单题失败' : '已完成' }}</span>
              <span>引用命中：{{ result.source_hit === null ? '—' : result.source_hit ? '是' : '否' }}</span>
              <span>正确：{{ result.correct === null ? '—' : result.correct ? '是' : '否' }}</span>
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
          </article>
        </div>
      </template>
    </section>
  </section>
</template>

<style scoped>
.experiment-page { display: grid; gap: 20px; }
.experiment-count { color: #26705d; font-size: 13px; font-weight: 650; white-space: nowrap; }
.experiment-panel { padding: 22px; background: #fff; border: 1px solid #e8edf3; border-radius: 16px; }
.experiment-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 14px; }
.experiment-heading h3 { margin: 0; font-size: 17px; }
.experiment-heading p:not(.eyebrow) { margin: 6px 0 0; color: #758195; font-size: 13px; }
.experiment-create-form { display: flex; align-items: end; flex-wrap: wrap; gap: 12px; }
.experiment-create-form label { display: grid; gap: 6px; color: #667286; font-size: 13px; }
.experiment-create-form input, .experiment-create-form select { min-height: 36px; padding: 7px 9px; color: #202938; background: #fff; border: 1px solid #d8dee8; border-radius: 7px; font: inherit; }
.experiment-create-form input { min-width: 280px; }
.experiment-primary { min-height: 36px; padding: 0 14px; color: #fff; background: #26705d; border: 0; border-radius: 7px; cursor: pointer; }
.experiment-primary:disabled { opacity: .6; cursor: default; }
.experiment-table-wrap { margin-top: 12px; overflow-x: auto; }
.experiment-table { width: 100%; border-collapse: collapse; text-align: left; }
.experiment-table th, .experiment-table td { padding: 11px 9px; border-bottom: 1px solid #edf0f4; vertical-align: top; }
.experiment-table th { color: #758195; font-size: 12px; font-weight: 650; white-space: nowrap; }
.experiment-table td { color: #4e5a6b; font-size: 13px; }
.experiment-list-table tbody tr { cursor: pointer; }
.experiment-list-table tbody tr:hover, .experiment-row-selected { background: #f0f7f4; }
.experiment-row-best { background: #f0f7f4; }
.experiment-link { padding: 0; color: #26705d; font: inherit; font-weight: 650; text-align: left; background: none; border: 0; cursor: pointer; }
.experiment-status { padding: 5px 10px; color: #26705d; background: #edf7f3; border-radius: 999px; font-size: 12px; font-weight: 650; }
.experiment-progress { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 12px; color: #667286; font-size: 13px; }
.experiment-progress progress { width: 100%; height: 10px; accent-color: #26705d; }
.experiment-signature, .experiment-muted { color: #8a95a5; font-size: 13px; line-height: 1.6; }
.experiment-best { margin: 14px 0 0; padding: 12px 14px; color: #26705d; background: #f0f7f4; border-radius: 9px; font-size: 14px; font-weight: 650; }
.experiment-results-table tbody tr { cursor: default; }
.experiment-cases { margin-top: 22px; }
.experiment-cases h4 { margin: 0 0 8px; font-size: 15px; }
.experiment-case { display: grid; gap: 10px; padding: 14px 0; border-top: 1px solid #edf0f4; }
.experiment-case-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; color: #667286; font-size: 12px; }
.experiment-case-heading strong { color: #202938; font-size: 13px; }
.experiment-completed { color: #26705d; }
.experiment-failed, .experiment-error { color: #c45656; }
.experiment-sources { display: grid; gap: 12px; margin: 0; padding-left: 20px; color: #4e5a6b; font-size: 13px; }
.experiment-sources li { display: grid; gap: 5px; }
.experiment-sources li > span { color: #758195; font-size: 12px; }
.experiment-sources p { margin: 0; line-height: 1.6; white-space: pre-wrap; }
.experiment-error { margin: 10px 0; padding: 10px 12px; background: #fff1f0; border: 1px solid #f3d0ce; border-radius: 8px; font-size: 13px; }
.experiment-empty { padding: 26px !important; color: #8a95a5 !important; text-align: center; }
.experiment-pagination { display: flex; justify-content: flex-end; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 16px; color: #758195; font-size: 13px; }
.experiment-pagination button { min-height: 34px; padding: 0 10px; color: #4e5a6b; background: #fff; border: 1px solid #d8dee8; border-radius: 7px; cursor: pointer; }
.experiment-pagination button:disabled { color: #b4bbc5; cursor: default; }
@media (max-width: 700px) { .experiment-panel { padding: 16px; } .experiment-create-form { align-items: stretch; } .experiment-create-form label { flex: 1 1 100%; } }
</style>
