import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElButton, ElInput, ElSelect } from 'element-plus'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as missingKnowledgeApi from '@/api/missingKnowledge'
import { ApiError } from '@/api/http'
import MissingKnowledgeView from '@/views/MissingKnowledgeView.vue'

vi.mock('@/api/missingKnowledge', () => ({
  getMissingKnowledge: vi.fn(),
  updateMissingKnowledge: vi.fn(),
}))

const item: missingKnowledgeApi.MissingKnowledgeItem = {
  id: 1,
  topic_key: 'wage_payment',
  sample_question: '公司拖欠工资怎么办',
  count: 4,
  missing_area: '工资支付与欠薪',
  status: 'PENDING',
  note: null,
  first_seen_at: '2026-09-15T00:00:00Z',
  last_seen_at: '2026-09-15T01:00:00Z',
}

function page(items: missingKnowledgeApi.MissingKnowledgeItem[], pages = 1) {
  return { items, page: 1, size: 20, total: items.length, pages }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(missingKnowledgeApi.getMissingKnowledge).mockResolvedValue(page([item]))
  vi.mocked(missingKnowledgeApi.updateMissingKnowledge).mockResolvedValue({
    ...item,
    status: 'RESOLVED',
    note: '已补充工资支付材料',
  })
})

describe('MissingKnowledgeView', () => {
  it('loads all topics sorted by frequency and displays the topic', async () => {
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenCalledWith({
      page: 1,
      size: 20,
      status: undefined,
      keyword: undefined,
      sort: 'count_desc',
    })
    expect(wrapper.text()).toContain('公司拖欠工资怎么办')
    expect(wrapper.text()).toContain('工资支付与欠薪')
    expect(wrapper.findAllComponents(ElSelect)[0].props('modelValue')).toBe('')
    wrapper.unmount()
  })

  it('applies the status and keyword filters', async () => {
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    const selects = wrapper.findAllComponents(ElSelect)
    await wrapper.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '工资')
    await selects[0].vm.$emit('update:modelValue', 'RESOLVED')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenLastCalledWith({
      page: 1,
      size: 20,
      status: 'RESOLVED',
      keyword: '工资',
      sort: 'count_desc',
    })
    wrapper.unmount()
  })

  it('applies a new sort order immediately', async () => {
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    const sortSelect = wrapper.findAllComponents(ElSelect)[1]

    await sortSelect.vm.$emit('update:modelValue', 'last_seen_desc')
    await sortSelect.vm.$emit('change', 'last_seen_desc')
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenLastCalledWith({
      page: 1,
      size: 20,
      status: undefined,
      keyword: undefined,
      sort: 'last_seen_desc',
    })
    wrapper.unmount()
  })

  it('keeps the loading state and shows an empty result message', async () => {
    let finishRequest: ((value: ReturnType<typeof page>) => void) | undefined
    vi.mocked(missingKnowledgeApi.getMissingKnowledge).mockImplementation(
      () => new Promise((resolve) => { finishRequest = resolve }),
    )
    const loadingWrapper = shallowMount(MissingKnowledgeView)
    expect(finishRequest).toBeDefined()
    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenCalledTimes(1)
    await nextTick()
    expect(loadingWrapper.get('.missing-knowledge-table-wrap').attributes('aria-busy')).toBe('true')
    finishRequest?.(page([]))
    await flushPromises()
    expect(loadingWrapper.text()).toContain('暂无符合条件的知识缺口')
    loadingWrapper.unmount()
  })

  it('requests the next page when pagination advances', async () => {
    vi.mocked(missingKnowledgeApi.getMissingKnowledge)
      .mockResolvedValueOnce(page([item], 2))
      .mockResolvedValueOnce(page([item], 2))
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    await wrapper.get('.missing-page-next').trigger('click')
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenLastCalledWith({
      page: 2,
      size: 20,
      status: undefined,
      keyword: undefined,
      sort: 'count_desc',
    })
    wrapper.unmount()
  })

  it('saves status and note changes', async () => {
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    await wrapper.findAllComponents(ElSelect)[2].vm.$emit('update:modelValue', 'RESOLVED')
    await wrapper.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', '已补充工资支付材料')
    await wrapper.findAllComponents(ElButton).find((button) => !button.classes('missing-filter-submit'))?.trigger('click')
    await flushPromises()

    expect(missingKnowledgeApi.updateMissingKnowledge).toHaveBeenCalledWith(1, {
      status: 'RESOLVED',
      note: '已补充工资支付材料',
    })
    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('公司拖欠工资怎么办')
    expect(wrapper.findAllComponents(ElSelect)[2].props('modelValue')).toBe('RESOLVED')
    wrapper.unmount()
  })

  it('shows errors from list and update requests', async () => {
    vi.mocked(missingKnowledgeApi.getMissingKnowledge).mockRejectedValueOnce(
      new ApiError(500, '读取知识缺口失败'),
    )
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('读取知识缺口失败')

    vi.mocked(missingKnowledgeApi.updateMissingKnowledge).mockRejectedValueOnce(
      new ApiError(500, '保存失败'),
    )
    vi.mocked(missingKnowledgeApi.getMissingKnowledge).mockResolvedValueOnce(page([item]))
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    await wrapper.findAllComponents(ElButton).find((button) => !button.classes('missing-filter-submit'))?.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('保存失败')
    wrapper.unmount()
  })
})
