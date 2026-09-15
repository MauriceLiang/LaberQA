import { flushPromises, shallowMount } from '@vue/test-utils'
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
  it('loads pending topics sorted by frequency and displays the topic', async () => {
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenCalledWith({
      page: 1,
      size: 20,
      status: 'PENDING',
      keyword: undefined,
      sort: 'count_desc',
    })
    expect(wrapper.text()).toContain('公司拖欠工资怎么办')
    expect(wrapper.text()).toContain('工资支付与欠薪')
    expect(wrapper.text()).toContain('待补充')
    wrapper.unmount()
  })

  it('applies the status, keyword, and sort filters', async () => {
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    const selects = wrapper.findAll('select')
    await wrapper.get('input[type="search"]').setValue('工资')
    await selects[0].setValue('')
    await selects[1].setValue('last_seen_desc')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenLastCalledWith({
      page: 1,
      size: 20,
      status: undefined,
      keyword: '工资',
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
    await wrapper.findAll('button').find((button) => button.text() === '下一页')?.trigger('click')
    await flushPromises()

    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenLastCalledWith({
      page: 2,
      size: 20,
      status: 'PENDING',
      keyword: undefined,
      sort: 'count_desc',
    })
    wrapper.unmount()
  })

  it('saves status and note changes', async () => {
    vi.mocked(missingKnowledgeApi.getMissingKnowledge)
      .mockResolvedValueOnce(page([item]))
      .mockResolvedValueOnce(page([]))
    const wrapper = shallowMount(MissingKnowledgeView)
    await flushPromises()
    await wrapper.findAll('select')[2].setValue('RESOLVED')
    await wrapper.get('textarea').setValue('已补充工资支付材料')
    await wrapper.findAll('button').find((button) => button.text() === '保存')?.trigger('click')
    await flushPromises()

    expect(missingKnowledgeApi.updateMissingKnowledge).toHaveBeenCalledWith(1, {
      status: 'RESOLVED',
      note: '已补充工资支付材料',
    })
    expect(missingKnowledgeApi.getMissingKnowledge).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('暂无符合条件的知识缺口')
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
    await wrapper.findAll('button').find((button) => button.text() === '保存')?.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('保存失败')
    wrapper.unmount()
  })
})
