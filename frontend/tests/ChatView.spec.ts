import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as chatApi from '@/api/chat'
import * as sessionsApi from '@/api/sessions'
import ChatView from '@/views/ChatView.vue'
import type { MessageItem, SessionItem } from '@/api/sessions'
import type { CitationItem, ToolExecutionItem } from '@/types/sse'

vi.mock('@/api/chat', () => ({
  getChatApiError: (error: unknown) => (error instanceof Error ? error.message : '请求失败'),
  streamChat: vi.fn(),
}))

vi.mock('@/api/sessions', () => ({
  createSession: vi.fn(),
  getSessionMessages: vi.fn(),
}))

const session: SessionItem = {
  id: '7ad8c9e1-62b2-4d40-9c6f-c48657f901d0',
  title: '欠薪问题',
  created_at: '2026-09-15T00:00:00Z',
  updated_at: '2026-09-15T00:00:00Z',
}

const nextSession: SessionItem = {
  ...session,
  id: '88f4d026-b4d1-4128-8213-87663049e775',
  title: '新会话',
}

const citation: CitationItem = {
  chunk_id: 4,
  document_id: 2,
  file_name: '工资支付规定.txt',
  chunk_no: 3,
  content: '用人单位应当按月支付工资。',
  score: 0.84,
  retrieval_score: 0.84,
  rerank_score: null,
  rank_no: 1,
}

const materialChecklist: ToolExecutionItem = {
  tool_name: 'generate_rights_material_checklist',
  input: { dispute_type: '欠薪', description: '公司拖欠工资，我应该准备什么材料？' },
  output: {
    materials: ['劳动合同或能够证明劳动关系的材料', '工资条、银行流水等工资支付记录'],
    note: '材料清单仅用于信息整理，具体以实际争议和受理机构要求为准。',
  },
}

const history: MessageItem[] = [
  {
    id: 1,
    session_id: session.id,
    role: 'user',
    content: '工资拖欠怎么办？',
    rewritten_question: null,
    answer_style: null,
    refused: null,
    created_at: '2026-09-15T00:00:00Z',
    citations: [],
    tool_executions: [],
  },
  {
    id: 2,
    session_id: session.id,
    role: 'assistant',
    content: '可以先保存工资流水等证据。',
    rewritten_question: null,
    answer_style: 'plain',
    refused: false,
    created_at: '2026-09-15T00:00:01Z',
    citations: [citation],
    tool_executions: [],
  },
]

function mountView() {
  return mount(ChatView, { global: { plugins: [createPinia()] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(sessionsApi.createSession).mockResolvedValue(session)
  vi.mocked(sessionsApi.getSessionMessages).mockResolvedValue([])
})

describe('ChatView', () => {
  it('creates a session, streams an answer with sources, and allows a new isolated session', async () => {
    vi.mocked(chatApi.streamChat).mockImplementation(async (_request, handlers) => {
      handlers.onToken({ content: '请保存工资记录。' })
      handlers.onSources({ items: [citation] })
      handlers.onDone({ message_id: 22, answer_style: 'plain', refused: false })
    })
    const wrapper = mountView()

    await wrapper.get('textarea').setValue(' 公司拖欠工资，我应该怎么办？ ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(sessionsApi.createSession).toHaveBeenCalledWith('公司拖欠工资，我应该怎么办？')
    expect(chatApi.streamChat).toHaveBeenCalledWith(
      {
        session_id: session.id,
        question: '公司拖欠工资，我应该怎么办？',
        answer_style: 'plain',
      },
      expect.any(Object),
      expect.any(AbortSignal),
    )
    expect(localStorage.getItem('labor-rights-qa.session-id')).toBe(session.id)
    expect(wrapper.text()).toContain('请保存工资记录。')
    expect(wrapper.text()).toContain('工资支付规定.txt')
    expect(wrapper.text()).toContain('参考资料（1）')

    await wrapper.get('.new-session-button').trigger('click')
    expect(localStorage.getItem('labor-rights-qa.session-id')).toBeNull()
    expect(wrapper.findAll('.message-row')).toHaveLength(0)
    wrapper.unmount()
  })

  it('restores a saved session and its citations on mount', async () => {
    localStorage.setItem('labor-rights-qa.session-id', session.id)
    vi.mocked(sessionsApi.getSessionMessages).mockResolvedValue(history)
    const wrapper = mountView()
    await flushPromises()

    expect(sessionsApi.getSessionMessages).toHaveBeenCalledWith(session.id)
    expect(wrapper.text()).toContain('工资拖欠怎么办？')
    expect(wrapper.text()).toContain('可以先保存工资流水等证据。')
    expect(wrapper.text()).toContain('工资支付规定.txt')
    wrapper.unmount()
  })

  it('shows a material checklist received through the tool event', async () => {
    vi.mocked(chatApi.streamChat).mockImplementation(async (_request, handlers) => {
      handlers.onTool?.(materialChecklist)
      handlers.onToken({ content: '建议整理相关材料。' })
      handlers.onDone({ message_id: 23, answer_style: 'plain', refused: false })
    })
    const wrapper = mountView()

    await wrapper.get('textarea').setValue('公司拖欠工资，我应该准备什么材料？')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('材料清单')
    expect(wrapper.text()).toContain('工资条、银行流水等工资支付记录')
    expect(wrapper.text()).toContain(materialChecklist.output.note)
    wrapper.unmount()
  })

  it('reuses the session for follow-ups and isolates a new conversation', async () => {
    vi.mocked(sessionsApi.createSession)
      .mockResolvedValueOnce(session)
      .mockResolvedValueOnce(nextSession)
    let messageId = 30
    vi.mocked(chatApi.streamChat).mockImplementation(async (request, handlers) => {
      handlers.onToken({ content: '收到问题。' })
      handlers.onDone({
        message_id: ++messageId,
        answer_style: request.answer_style,
        refused: false,
      })
    })
    const wrapper = mountView()
    const ask = async (text: string) => {
      await wrapper.get('textarea').setValue(text)
      await wrapper.get('form').trigger('submit')
      await flushPromises()
    }

    await ask('第一轮问题')
    await wrapper.get('.answer-style-switch').findAll('button')[1].trigger('click')
    await ask('第二轮追问')
    await ask('第三轮追问')

    const requests = vi.mocked(chatApi.streamChat).mock.calls.map(([payload]) => payload)
    expect(requests.map((payload) => payload.session_id)).toEqual([
      session.id,
      session.id,
      session.id,
    ])
    expect(requests.map((payload) => payload.answer_style)).toEqual([
      'plain',
      'legal',
      'legal',
    ])
    expect(sessionsApi.createSession).toHaveBeenCalledTimes(1)

    await wrapper.get('.new-session-button').trigger('click')
    await ask('新会话的问题')

    const finalRequest = vi.mocked(chatApi.streamChat).mock.calls.at(-1)?.[0]
    expect(finalRequest?.session_id).toBe(nextSession.id)
    expect(sessionsApi.createSession).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('第一轮问题')
    wrapper.unmount()
  })

  it('aborts generation and keeps already received text marked as stopped', async () => {
    vi.mocked(chatApi.streamChat).mockImplementation((_request, handlers, signal) => {
      handlers.onToken({ content: '目前收到的部分回答' })
      return new Promise((resolve) => {
        signal?.addEventListener('abort', () => resolve(), { once: true })
      })
    })
    const wrapper = mountView()
    await wrapper.get('textarea').setValue('我应该准备什么材料？')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    await wrapper.get('.stop-button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('目前收到的部分回答')
    expect(wrapper.text()).toContain('已停止生成')
    expect(wrapper.findAll('.message-row')).toHaveLength(2)
    wrapper.unmount()
  })

  it('shows an SSE error without assigning a completed message id', async () => {
    vi.mocked(chatApi.streamChat).mockImplementation(async (_request, handlers) => {
      handlers.onError({ code: 50302, message: '模型服务暂不可用' })
    })
    const wrapper = mountView()
    await wrapper.get('textarea').setValue('公司欠薪怎么办？')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('模型服务暂不可用')
    expect(wrapper.text()).toContain('回答未完成；可以重新提问。')
    wrapper.unmount()
  })
})
