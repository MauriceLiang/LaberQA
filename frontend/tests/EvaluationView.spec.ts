import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElInput, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as evaluationsApi from '@/api/evaluations'
import MarkdownContent from '@/components/chat/MarkdownContent.vue'
import EvaluationView from '@/views/EvaluationView.vue'

vi.mock('@/api/evaluations', () => ({
  createEvaluationRun: vi.fn(),
  getEvaluationCases: vi.fn(),
  getEvaluationRun: vi.fn(),
  getEvaluationRuns: vi.fn(),
}))

const evaluationCase: evaluationsApi.EvaluationCase = {
  id: 3,
  topic: '工资支付与欠薪',
  expected_type: 'ANSWER',
  turns: ['公司拖欠工资怎么办？'],
  expected_points: ['申请劳动仲裁'],
  expected_sources: [],
  should_show_compliance: true,
}

function casePage(items = [evaluationCase], page = 1, pages = 1) {
  return { items, page, size: 20, total: items.length, pages }
}

function runSummary(
  status: evaluationsApi.EvaluationRunSummary['status'] = 'RUNNING',
): evaluationsApi.EvaluationRunSummary {
  return {
    id: 8,
    name: '回归评测',
    status,
    progress_current: 1,
    progress_total: 1,
    error_message: null,
    created_at: '2026-09-15T00:00:00Z',
    updated_at: '2026-09-15T00:00:01Z',
  }
}

function runDetail(
  status: evaluationsApi.EvaluationRunDetail['status'] = 'RUNNING',
): evaluationsApi.EvaluationRunDetail {
  return {
    ...runSummary(status),
    config: {
      answer_style: 'plain',
      llm_model: 'test-model',
      evaluator_model: 'test-model',
      evaluator_prompt_version: 'evaluation_judge_v1',
      embedding_provider: 'local',
      embedding_model: 'BAAI/bge-small-zh-v1.5',
      embedding_normalize: true,
      prompt_version: 'labor_v1',
      chunk_size: 600,
      chunk_overlap: 100,
      top_k: 5,
      rerank_enabled: false,
      score_threshold: 0.35,
    },
    metrics: status === 'COMPLETED' ? {
      accuracy: 0.9,
      reject_rate: 0.2,
      citation_hit_rate: 0.8,
      multi_turn_pass_rate: 0.75,
      compliance_hit_rate: 1,
    } : null,
    results: status === 'COMPLETED' ? [{
      case_id: 3,
      status: 'COMPLETED',
      answer: '**简要结论：**\n\n可以申请劳动仲裁。\n\n- 准备工资记录\n- 保存沟通证据',
      refused: false,
      correct: true,
      source_hit: true,
      multi_turn_correct: null,
      compliance_hit: true,
      citations: [{
        chunk_id: 11,
        document_id: 4,
        file_name: '工资支付规定.txt',
        chunk_no: 2,
        content: '工资应当按月支付。',
        score: 0.9,
        retrieval_score: 0.9,
        rerank_score: null,
        rank_no: 1,
      }],
      latency_ms: 120,
      error_message: null,
    }] : [],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  vi.mocked(evaluationsApi.getEvaluationCases).mockResolvedValue(casePage())
  vi.mocked(evaluationsApi.getEvaluationRuns).mockResolvedValue({
    items: [], page: 1, size: 10, total: 0, pages: 0,
  })
  vi.mocked(evaluationsApi.getEvaluationRun).mockResolvedValue(runDetail())
  vi.mocked(evaluationsApi.createEvaluationRun).mockResolvedValue({
    run_id: 8, status: 'PENDING', progress_current: 0, progress_total: 1, error_message: null,
  })
})

afterEach(() => vi.useRealTimers())

describe('EvaluationView', () => {
  it('loads filtered, paginated cases with the API contract values', async () => {
    const wrapper = shallowMount(EvaluationView)
    await flushPromises()

    expect(evaluationsApi.getEvaluationCases).toHaveBeenCalledWith({
      page: 1, size: 20, topic: undefined, expected_type: undefined, is_multi_turn: undefined,
    })

    await wrapper.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '工资')
    await wrapper.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'REJECT')
    await wrapper.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'true')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(evaluationsApi.getEvaluationCases).toHaveBeenLastCalledWith({
      page: 1, size: 20, topic: '工资', expected_type: 'REJECT', is_multi_turn: true,
    })
    expect(wrapper.text()).toContain('公司拖欠工资怎么办？')
    wrapper.unmount()
  })

  it('creates a run for the selected IDs and uses null when no case is selected', async () => {
    const wrapper = shallowMount(EvaluationView)
    await flushPromises()

    await wrapper.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', '工资回归')
    await wrapper.findAllComponents(ElSelect)[3].vm.$emit('update:modelValue', 'legal')
    await wrapper.get('.evaluation-create-form').trigger('submit')
    await flushPromises()
    expect(evaluationsApi.createEvaluationRun).toHaveBeenCalledWith({
      name: '工资回归', case_ids: null, answer_style: 'legal',
    })

    vi.mocked(evaluationsApi.createEvaluationRun).mockResolvedValueOnce({
      run_id: 9, status: 'PENDING', progress_current: 0, progress_total: 1, error_message: null,
    })
    await wrapper.get('input[aria-label="选择用例 3"]').setValue(true)
    await wrapper.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', '指定用例')
    await wrapper.get('.evaluation-create-form').trigger('submit')
    await flushPromises()
    expect(evaluationsApi.createEvaluationRun).toHaveBeenLastCalledWith({
      name: '指定用例', case_ids: [3], answer_style: 'legal',
    })
    wrapper.unmount()
  })

  it('polls every two seconds, shows all metrics and per-case results, then stops at completion', async () => {
    vi.useFakeTimers()
    vi.mocked(evaluationsApi.getEvaluationRuns).mockResolvedValue({
      items: [runSummary()], page: 1, size: 10, total: 1, pages: 1,
    })
    vi.mocked(evaluationsApi.getEvaluationRun)
      .mockResolvedValueOnce(runDetail('RUNNING'))
      .mockResolvedValueOnce(runDetail('COMPLETED'))

    const wrapper = shallowMount(EvaluationView)
    await flushPromises()
    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(1999)
    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('回答正确率')
    expect(wrapper.text()).toContain('90.0%')
    expect(wrapper.text()).toContain('多轮通过率')
    expect(wrapper.text()).toContain('用例 #3')
    expect(wrapper.text()).toContain('工资支付规定.txt')
    const answer = wrapper.findComponent(MarkdownContent)
    expect(answer.exists()).toBe(true)
    expect(answer.props('content')).toContain('**简要结论：**')
    expect(vi.getTimerCount()).toBe(0)

    await vi.advanceTimersByTimeAsync(4000)
    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('explains metrics that have no applicable cases instead of presenting them as failed calculations', async () => {
    const detail = runDetail('COMPLETED')
    detail.metrics = {
      accuracy: 0.85,
      reject_rate: null,
      citation_hit_rate: 0.65,
      multi_turn_pass_rate: null,
      compliance_hit_rate: null,
    }
    vi.mocked(evaluationsApi.getEvaluationRuns).mockResolvedValue({
      items: [runSummary('COMPLETED')], page: 1, size: 10, total: 1, pages: 1,
    })
    vi.mocked(evaluationsApi.getEvaluationRun).mockResolvedValue(detail)

    const wrapper = shallowMount(EvaluationView)
    await flushPromises()

    expect(wrapper.get('.evaluation-metrics').text()).toContain('85.0%')
    expect(wrapper.get('.evaluation-metrics').text()).toContain('65.0%')
    expect(wrapper.get('.evaluation-metrics').text()).toContain('不适用')
    expect(wrapper.get('.evaluation-metric-note').text()).toContain('没有包含该指标所需的用例')
    expect(wrapper.text()).not.toContain('—')
    wrapper.unmount()
  })
})
