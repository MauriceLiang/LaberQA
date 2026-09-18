import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElInput, ElMessageBox, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as evaluationsApi from '@/api/evaluations'
import MarkdownContent from '@/components/chat/MarkdownContent.vue'
import EvaluationView from '@/views/EvaluationView.vue'

vi.mock('@/api/evaluations', () => ({
  createEvaluationCase: vi.fn(),
  createEvaluationRun: vi.fn(),
  deleteEvaluationCase: vi.fn(),
  deleteEvaluationRun: vi.fn(),
  getEvaluationCases: vi.fn(),
  getEvaluationCase: vi.fn(),
  getEvaluationRun: vi.fn(),
  getEvaluationRuns: vi.fn(),
  updateEvaluationCase: vi.fn(),
}))

const evaluationCase: evaluationsApi.EvaluationCase = {
  id: 3,
  topic: '工资支付与欠薪',
  expected_type: 'ANSWER',
  turns: ['公司拖欠工资怎么办？'],
  expected_points: ['申请劳动仲裁'],
  expected_sources: [],
  should_show_compliance: true,
  origin: 'CUSTOM',
  status: 'ACTIVE',
  version: 1,
  created_at: '2026-09-15T00:00:00Z',
  updated_at: '2026-09-15T00:00:00Z',
  archived_at: null,
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
      case_scope: 'BUILTIN_BASELINE',
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
  vi.mocked(evaluationsApi.createEvaluationCase).mockResolvedValue(evaluationCase)
  vi.mocked(evaluationsApi.updateEvaluationCase).mockResolvedValue(evaluationCase)
  vi.mocked(evaluationsApi.deleteEvaluationCase).mockResolvedValue()
  vi.mocked(evaluationsApi.getEvaluationRuns).mockResolvedValue({
    items: [], page: 1, size: 10, total: 0, pages: 0,
  })
  vi.mocked(evaluationsApi.getEvaluationRun).mockResolvedValue(runDetail())
  vi.mocked(evaluationsApi.createEvaluationRun).mockResolvedValue({
    run_id: 8, status: 'PENDING', progress_current: 0, progress_total: 1, error_message: null,
  })
  vi.mocked(evaluationsApi.deleteEvaluationRun).mockResolvedValue()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('EvaluationView', () => {
  it('loads filtered, paginated cases with the API contract values', async () => {
    const wrapper = shallowMount(EvaluationView)
    await flushPromises()

    expect(evaluationsApi.getEvaluationCases).toHaveBeenCalledWith({
      page: 1, size: 20, topic: undefined, expected_type: undefined, is_multi_turn: undefined,
      origin: undefined, status: undefined, include_archived: false,
    })

    await wrapper.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '工资')
    await wrapper.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'REJECT')
    await wrapper.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'true')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(evaluationsApi.getEvaluationCases).toHaveBeenLastCalledWith({
      page: 1, size: 20, topic: '工资', expected_type: 'REJECT', is_multi_turn: true,
      origin: undefined, status: undefined, include_archived: false,
    })
    expect(wrapper.text()).toContain('公司拖欠工资怎么办？')
    wrapper.unmount()
  })

  it('creates a run for the selected IDs and uses null when no case is selected', async () => {
    const wrapper = shallowMount(EvaluationView)
    await flushPromises()

    await wrapper.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', '工资回归')
    const answerStyleSelect = wrapper.findAllComponents(ElSelect).find(
      (component) => component.attributes('aria-label') === '回答风格',
    )
    await answerStyleSelect!.vm.$emit('update:modelValue', 'legal')
    await wrapper.get('.evaluation-create-form').trigger('submit')
    await flushPromises()
    expect(evaluationsApi.createEvaluationRun).toHaveBeenCalledWith({
      name: '工资回归', case_ids: null, answer_style: 'legal', case_scope: 'BUILTIN_BASELINE',
    })

    vi.mocked(evaluationsApi.createEvaluationRun).mockResolvedValueOnce({
      run_id: 9, status: 'PENDING', progress_current: 0, progress_total: 1, error_message: null,
    })
    await wrapper.get('input[aria-label="选择用例 3"]').setValue(true)
    const scopeSelect = wrapper.findAllComponents(ElSelect).find(
      (component) => component.attributes('aria-label') === '执行范围',
    )
    await scopeSelect!.vm.$emit('update:modelValue', 'SELECTED')
    await wrapper.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', '指定用例')
    await wrapper.get('.evaluation-create-form').trigger('submit')
    await flushPromises()
    expect(evaluationsApi.createEvaluationRun).toHaveBeenLastCalledWith({
      name: '指定用例', case_ids: [3], answer_style: 'legal', case_scope: 'SELECTED',
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
    expect(evaluationsApi.getEvaluationRun).not.toHaveBeenCalled()
    expect(wrapper.find('.evaluation-detail-panel').exists()).toBe(false)
    expect(wrapper.get('.evaluation-link').attributes('aria-expanded')).toBe('false')
    expect(vi.getTimerCount()).toBe(0)

    await wrapper.get('.evaluation-link').trigger('click')
    await flushPromises()

    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.evaluation-detail-panel').exists()).toBe(true)
    expect(wrapper.get('.evaluation-link').attributes('aria-expanded')).toBe('true')
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(1999)
    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('回答正确率')
    expect(wrapper.text()).toContain('90.0%')
    expect(wrapper.text()).toContain('多轮通过率')
    expect(wrapper.text()).not.toContain('此批次没有可计算的指标。')
    expect(wrapper.text()).toContain('用例 #3')
    expect(wrapper.text()).toContain('工资支付规定.txt')
    const answer = wrapper.findComponent(MarkdownContent)
    expect(answer.exists()).toBe(true)
    expect(answer.props('content')).toContain('**简要结论：**')
    expect(vi.getTimerCount()).toBe(0)

    await vi.advanceTimersByTimeAsync(4000)
    expect(evaluationsApi.getEvaluationRun).toHaveBeenCalledTimes(2)

    await wrapper.get('.evaluation-link').trigger('click')
    expect(wrapper.find('.evaluation-detail-panel').exists()).toBe(false)
    expect(wrapper.get('.evaluation-link').attributes('aria-expanded')).toBe('false')
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
    await wrapper.get('.evaluation-link').trigger('click')
    await flushPromises()

    expect(wrapper.get('.evaluation-metrics').text()).toContain('85.0%')
    expect(wrapper.get('.evaluation-metrics').text()).toContain('65.0%')
    expect(wrapper.get('.evaluation-metrics').text()).toContain('不适用')
    expect(wrapper.get('.evaluation-metric-note').text()).toContain('没有包含该指标所需的用例')
    expect(wrapper.text()).not.toContain('—')
    wrapper.unmount()
  })

  it('requires confirmation and refreshes the list after deleting a completed run', async () => {
    vi.mocked(evaluationsApi.getEvaluationRuns)
      .mockResolvedValueOnce({
        items: [runSummary('COMPLETED')], page: 1, size: 10, total: 1, pages: 1,
      })
      .mockResolvedValueOnce({
        items: [], page: 1, size: 10, total: 0, pages: 0,
      })
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce(new Error('cancel'))
    const wrapper = shallowMount(EvaluationView)
    await flushPromises()

    await wrapper.get('.evaluation-run-delete').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledWith(
      '将同时删除该批次的逐题结果、指标和用例关联，删除后不可恢复。',
      '确定删除评测批次“回归评测”吗？',
      expect.objectContaining({ confirmButtonText: '删除', cancelButtonText: '取消' }),
    )
    expect(evaluationsApi.deleteEvaluationRun).not.toHaveBeenCalled()

    vi.mocked(evaluationsApi.getEvaluationRun).mockResolvedValueOnce(runDetail('COMPLETED'))
    await wrapper.get('.evaluation-link').trigger('click')
    await flushPromises()
    expect(wrapper.find('.evaluation-detail-panel').exists()).toBe(true)

    confirm.mockResolvedValueOnce(undefined as never)
    await wrapper.get('.evaluation-run-delete').trigger('click')
    await flushPromises()

    expect(evaluationsApi.deleteEvaluationRun).toHaveBeenCalledWith(8)
    expect(wrapper.find('.evaluation-detail-panel').exists()).toBe(false)
    expect(wrapper.text()).toContain('暂无评测批次')
    wrapper.unmount()
  })
})
