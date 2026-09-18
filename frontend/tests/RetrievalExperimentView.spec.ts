import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElInput } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as experimentsApi from '@/api/experiments'
import * as evaluationsApi from '@/api/evaluations'
import RetrievalExperimentView from '@/views/RetrievalExperimentView.vue'

vi.mock('@/api/experiments', () => ({
  createExperiment: vi.fn(),
  getExperiment: vi.fn(),
  getExperiments: vi.fn(),
}))

vi.mock('@/api/evaluations', () => ({
  getEvaluationCases: vi.fn(),
}))

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
    best_config_index: status === 'COMPLETED' ? 5 : null,
    config_results: status === 'COMPLETED' ? [0, 1, 2, 3, 4, 5].map((config_index) => ({
      config_index,
      config: {
        chunk_size: config_index === 1 ? 400 : config_index === 2 ? 800 : 600,
        chunk_overlap: 100,
        top_k: config_index === 3 ? 3 : config_index === 4 ? 8 : 5,
        rerank_enabled: config_index === 5,
        rerank_top_n: config_index === 3 ? 3 : config_index === 4 ? 8 : 5,
        score_threshold: 0.35,
      },
      accuracy: 0.8,
      reject_rate: 0.7,
      citation_hit_rate: 0.9,
      avg_retrieval_ms: 12.5,
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
    progress_total: 360,
    error_message: null,
  })
  vi.mocked(evaluationsApi.getEvaluationCases).mockResolvedValue({
    items: [], page: 1, size: 100, total: 0, pages: 0,
  })
})

afterEach(() => vi.useRealTimers())

describe('RetrievalExperimentView', () => {
  it('shows the six fixed A–F baseline configurations', async () => {
    const wrapper = shallowMount(RetrievalExperimentView)
    await flushPromises()

    expect(wrapper.text()).toContain('600')
    expect(wrapper.text()).toContain('400')
    expect(wrapper.text()).toContain('800')
    expect(wrapper.text()).toContain('A')
    expect(wrapper.text()).toContain('F')
    expect(wrapper.text()).toContain('Rerank Top-N')
    wrapper.unmount()
  })

  it('requires a name and creates a full six-group experiment with null case_ids', async () => {
    const wrapper = shallowMount(RetrievalExperimentView)
    await flushPromises()

    await wrapper.get('form').trigger('submit')
    expect(experimentsApi.createExperiment).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请填写实验名称')

    await wrapper.findComponent(ElInput).vm.$emit('update:modelValue', '劳动权益检索实验')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(experimentsApi.createExperiment).toHaveBeenCalledWith({
      name: '劳动权益检索实验',
      case_ids: null,
      case_scope: 'BUILTIN_BASELINE',
      answer_style: 'plain',
      configs: [
        { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 },
        { chunk_size: 400, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 },
        { chunk_size: 800, chunk_overlap: 100, top_k: 5, rerank_enabled: false, rerank_top_n: 5, score_threshold: 0.35 },
        { chunk_size: 600, chunk_overlap: 100, top_k: 3, rerank_enabled: false, rerank_top_n: 3, score_threshold: 0.35 },
        { chunk_size: 600, chunk_overlap: 100, top_k: 8, rerank_enabled: false, rerank_top_n: 8, score_threshold: 0.35 },
        { chunk_size: 600, chunk_overlap: 100, top_k: 5, rerank_enabled: true, rerank_top_n: 5, score_threshold: 0.35 },
      ],
    })
    wrapper.unmount()
  })

  it('shows per-group metrics and experimental chunk sources', async () => {
    vi.mocked(experimentsApi.getExperiments).mockResolvedValue({
      items: [summary('COMPLETED')], page: 1, size: 10, total: 1, pages: 1,
    })
    vi.mocked(experimentsApi.getExperiment).mockResolvedValue(experimentDetail())

    const wrapper = shallowMount(RetrievalExperimentView)
    await flushPromises()

    expect(wrapper.text()).toContain('当前最优配置：F')
    expect(wrapper.text()).toContain('引用命中率')
    expect(wrapper.text()).toContain('90.0%')
    await wrapper.findAll('.experiment-link').find((button) => button.text() === 'F · 最优')?.trigger('click')
    expect(wrapper.text()).toContain('用例 #12')
    expect(wrapper.text()).toContain('实验分块第 7 段')
    expect(wrapper.text()).toContain('不对应原评测集中的来源段号')
    wrapper.unmount()
  })

  it('polls detail every two seconds and stops after completion', async () => {
    vi.useFakeTimers()
    vi.mocked(experimentsApi.getExperiments).mockResolvedValue({
      items: [summary()], page: 1, size: 10, total: 1, pages: 1,
    })
    vi.mocked(experimentsApi.getExperiment)
      .mockResolvedValueOnce(experimentDetail('RUNNING'))
      .mockResolvedValueOnce(experimentDetail('COMPLETED'))

    const wrapper = shallowMount(RetrievalExperimentView)
    await flushPromises()
    expect(experimentsApi.getExperiment).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1999)
    expect(experimentsApi.getExperiment).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(experimentsApi.getExperiment).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('已完成')
    expect(vi.getTimerCount()).toBe(0)
    wrapper.unmount()
  })
})
