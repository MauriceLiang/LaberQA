import axios from 'axios'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElButton } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as experimentsApi from '@/api/experiments'
import * as evaluationsApi from '@/api/evaluations'
import { getErrorMessage } from '@/api/http'
import RetrievalExperimentView from '@/views/RetrievalExperimentView.vue'

vi.mock('@/api/experiments', () => ({
  archiveRetrievalExperiment: vi.fn(),
  archiveRetrievalStrategy: vi.fn(),
  copyExperiment: vi.fn(),
  createExperiment: vi.fn(),
  createRetrievalStrategy: vi.fn(),
  deleteExperiment: vi.fn(),
  deleteRetrievalStrategy: vi.fn(),
  exportRetrievalExperiment: vi.fn(),
  getExperiment: vi.fn(),
  getExperiments: vi.fn(),
  listRetrievalStrategies: vi.fn(),
  listRetrievalStrategyVersions: vi.fn(),
  previewRetrieval: vi.fn(),
  restoreRetrievalExperiment: vi.fn(),
  restoreRetrievalStrategy: vi.fn(),
  restoreRetrievalStrategyVersion: vi.fn(),
  setRetrievalStrategyActive: vi.fn(),
  updateRetrievalStrategy: vi.fn(),
}))

vi.mock('@/api/evaluations', () => ({
  getEvaluationCases: vi.fn(),
}))

const configs = [
  { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 },
  { chunk_size: 400, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 },
  { chunk_size: 800, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 },
  { chunk_size: 600, chunk_overlap: 100, top_k: 3, rerank_enabled: false, rerank_top_n: 3, score_threshold: 0.35 },
  { chunk_size: 600, chunk_overlap: 100, top_k: 8, rerank_enabled: false, rerank_top_n: 8, score_threshold: 0.35 },
  { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: true, rerank_top_n: 5, score_threshold: 0.35 },
]

function strategyFixtures(): experimentsApi.RetrievalStrategy[] {
  return configs.map((config, index) => ({
    id: index + 1,
    name: '基线 ' + String.fromCharCode(65 + index) + ' · ' + (index === 5 ? '重排' : '实验'),
    description: '测试策略',
    builtin_key: 'baseline_' + (index + 1),
    config,
    is_builtin: true,
    version: 1,
    is_active: true,
    archived_at: null,
    created_at: '2026-09-15T00:00:00Z',
    updated_at: '2026-09-15T00:00:00Z',
  }))
}

function summary(status: experimentsApi.ExperimentSummary['status'] = 'RUNNING'): experimentsApi.ExperimentSummary {
  return {
    id: 9,
    name: '检索对比',
    status,
    progress_current: 3,
    progress_total: 360,
    error_message: null,
    created_at: '2026-09-15T00:00:00Z',
    updated_at: '2026-09-15T00:00:01Z',
  }
}

function experimentDetail(status: experimentsApi.ExperimentDetail['status'] = 'COMPLETED'): experimentsApi.ExperimentDetail {
  const strategies = strategyFixtures()
  return {
    ...summary(status),
    embedding_signature: {
      embedding_provider: 'local',
      embedding_model: 'test-model',
      embedding_dimension: 384,
      normalize_embeddings: true,
    },
    runtime_config: {
      langchain_version: '1.6.3',
      chat_provider: 'langchain_openai.ChatOpenAI',
      llm_model: 'test-model',
      embedding_provider: 'local',
      embedding_model: 'test-model',
      embedding_normalize: true,
      splitter_type: 'app.rag.splitters.LegalTextSplitter',
      splitter_version: 'legal-text-splitter-v1',
      vectorstore_type: 'langchain_community.vectorstores.FAISS',
      retrieval_type: 'similarity',
      rerank_model: null,
      prompt_version: 'labor_langchain_v1',
    },
    case_count: 60,
    best_config_index: status === 'COMPLETED' ? 5 : null,
    strategy_snapshots: strategies.map((strategy) => ({
      strategy_id: strategy.id,
      name: strategy.name,
      version: strategy.version,
      config: strategy.config,
    })),
    config_results: status === 'COMPLETED' ? configs.map((config, config_index) => ({
      config_index,
      config,
      accuracy: 0.8,
      reject_rate: 0.7,
      citation_hit_rate: 0.9,
      avg_retrieval_ms: 12.5 + config_index,
    })) : [],
    results: status === 'COMPLETED' ? [{
      config_index: 5,
      case_id: 12,
      status: 'COMPLETED',
      retrieved_sources: [{
        chunk_id: 81,
        document_id: 2,
        file_name: '劳动法.txt',
        chunk_no: 7,
        content: '实验索引中的来源片段。',
        score: 0.8,
        retrieval_score: 0.8,
        rerank_score: 0.9,
        rank_no: 1,
      }],
      source_hit: true,
      correct: true,
      refused: false,
      retrieval_ms: 12.5,
      error_message: null,
    }] : [],
  }
}

const previewResult: experimentsApi.RetrievalPreview = {
  strategy_id: 6,
  strategy_name: '基线 F · 重排',
  strategy_version: 1,
  index_mode: 'PRODUCTION_INDEX_REUSE',
  limitations: ['快速试跑复用生产索引', 'Chunk Size 与 Chunk Overlap 不会重新切分'],
  question: '公司拖欠工资，我应该准备什么材料？',
  rewritten_question: '公司拖欠工资需要准备什么材料',
  answer: '请准备劳动合同、工资流水等材料。',
  refused: false,
  retrieval_ms: 120,
  retrieved_sources: [],
  citations: [],
  trace: [{
    stage: '文本分块',
    status: 'completed',
    detail: '试跑复用生产索引',
    duration_ms: null,
  }],
  config: configs[5],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  vi.mocked(experimentsApi.getExperiments).mockResolvedValue({
    items: [], page: 1, size: 10, total: 0, pages: 0,
  })
  vi.mocked(experimentsApi.getExperiment).mockResolvedValue(experimentDetail())
  vi.mocked(experimentsApi.createExperiment).mockResolvedValue({
    experiment_id: 10,
    status: 'PENDING',
    progress_current: 0,
    progress_total: 120,
    error_message: null,
  })
  vi.mocked(experimentsApi.listRetrievalStrategies).mockResolvedValue(strategyFixtures())
  vi.mocked(experimentsApi.previewRetrieval).mockResolvedValue(previewResult)
  vi.mocked(evaluationsApi.getEvaluationCases).mockResolvedValue({
    items: [], page: 1, size: 100, total: 60, pages: 1,
  })
})

afterEach(() => vi.useRealTimers())

async function mountView() {
  const wrapper = shallowMount(RetrievalExperimentView)
  await flushPromises()
  return wrapper
}

describe('RetrievalExperimentView', () => {
  it('does not preselect formal experiment strategies or render global comparison controls', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as unknown as {
      experimentName: string
      experimentStrategyIds: number[]
    }

    expect(vm.experimentStrategyIds).toEqual([])
    expect(wrapper.text()).not.toContain('已选 6 组策略')
    expect(wrapper.text()).not.toContain('对比已选')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0)
    expect(wrapper.findAll('.strategy-card')).toHaveLength(6)

    vm.experimentName = '劳动权益检索实验'
    await wrapper.get('form').trigger('submit')
    expect(experimentsApi.createExperiment).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('检索策略对比实验至少需要选择两条策略')
    wrapper.unmount()
  })

  it('requires at least two strategies before creating a formal experiment', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as unknown as {
      experimentName: string
      experimentStrategyIds: number[]
    }

    vm.experimentName = '劳动权益检索实验'
    vm.experimentStrategyIds = [1]
    await wrapper.get('form').trigger('submit')
    expect(experimentsApi.createExperiment).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('检索策略对比实验至少需要选择两条策略')

    vm.experimentStrategyIds = [1, 2]
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(experimentsApi.createExperiment).toHaveBeenCalledWith({
      name: '劳动权益检索实验',
      strategy_ids: [1, 2],
      case_ids: null,
      case_scope: 'BUILTIN_BASELINE',
      answer_style: 'plain',
    })
    wrapper.unmount()
  })

  it('sends the clicked strategy id for single-question preview and renders backend identity', async () => {
    const wrapper = await mountView()
    const previewButton = wrapper.findAll('.strategy-card-actions').at(5)!.findComponent(ElButton)
    expect(previewButton.exists()).toBe(true)
    await previewButton.trigger('click')
    expect(experimentsApi.previewRetrieval).not.toHaveBeenCalled()
    const startButton = wrapper.find('.preview-submit')
    expect(startButton.exists()).toBe(true)
    await startButton.trigger('click')
    await flushPromises()

    expect(experimentsApi.previewRetrieval).toHaveBeenCalledWith({
      question: '公司拖欠工资，我应该准备什么材料？',
      answer_style: 'plain',
      strategy_id: 6,
    })
    expect(wrapper.text()).toContain('基线 F · 重排 · v1')
    expect(wrapper.text()).toContain('Chunk Size 与 Chunk Overlap 不会重新切分')
    wrapper.unmount()
  })

  it('shows the timeout message without misreporting a connection failure', async () => {
    const wrapper = await mountView()
    vi.mocked(experimentsApi.previewRetrieval).mockRejectedValueOnce(
      new axios.AxiosError('timeout', 'ECONNABORTED'),
    )
    const startButton = wrapper.find('.preview-submit')
    expect(startButton.exists()).toBe(true)
    await startButton.trigger('click')
    await flushPromises()

    expect(getErrorMessage(new axios.AxiosError('timeout', 'ECONNABORTED'))).toBe('请求处理超时，请稍后重试')
    expect(wrapper.text()).toContain('请求处理超时，请稍后重试')
    expect(wrapper.text()).not.toContain('无法连接后端')
    wrapper.unmount()
  })

  it('calculates the estimated run count from the loaded case count', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as unknown as { experimentStrategyIds: number[] }
    vm.experimentStrategyIds = [1, 2, 6]
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('3 个策略 × 60 条问题 = 180 题次')
    wrapper.unmount()
  })

  it('renders every strategy in the result table and generates a structured conclusion', async () => {
    vi.mocked(experimentsApi.getExperiments).mockResolvedValue({
      items: [summary('COMPLETED')], page: 1, size: 10, total: 1, pages: 1,
    })
    vi.mocked(experimentsApi.getExperiment).mockResolvedValue(experimentDetail())

    const wrapper = await mountView()
    expect(wrapper.text()).toContain('实验结论')
    expect(wrapper.text()).toContain('本次实验共比较 6 条策略、60 条测试问题。')
    for (const strategy of strategyFixtures()) expect(wrapper.text()).toContain(strategy.name)
    expect(wrapper.text()).toContain('当前最优策略：基线 F · 重排 · v1')
    wrapper.unmount()
  })
})
