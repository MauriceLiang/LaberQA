import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamChat } from '@/api/chat'
import type { ChatRequest, ChatStreamHandlers, CitationItem } from '@/types/sse'

function responseWithChunks(chunks: Uint8Array[], status = 200) {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  })
  return { ok: status >= 200 && status < 300, status, body } as Response
}

const request: ChatRequest = {
  session_id: '7ad8c9e1-62b2-4d40-9c6f-c48657f901d0',
  question: '公司拖欠工资怎么办？',
  answer_style: 'plain',
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

const handlers: ChatStreamHandlers = {
  onTool: vi.fn(),
  onToken: vi.fn(),
  onSources: vi.fn(),
  onDone: vi.fn(),
  onError: vi.fn(),
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('streamChat', () => {
  it('decodes UTF-8 chunks, dispatches events in order, and stops at done', async () => {
    const tool = {
      tool_name: 'generate_rights_material_checklist' as const,
      input: { dispute_type: '欠薪', description: '拖欠工资' },
      output: { materials: ['工资流水'], note: '仅供整理材料。' },
    }
    const stream = [
      `event: tool\ndata: ${JSON.stringify(tool)}\r\n\r\n`,
      'event: token\ndata: {"content":"工资被拖欠"}\n\n',
      `event: sources\ndata: ${JSON.stringify({ items: [citation] })}\n\n`,
      'event: done\ndata: {"message_id":12,"answer_style":"plain","refused":false}\n\n',
      'event: token\ndata: {"content":"不应读取"}\n\n',
    ].join('')
    const bytes = new TextEncoder().encode(stream)
    const chunks: Uint8Array[] = []
    for (let offset = 0; offset < bytes.length; offset += 11) {
      chunks.push(bytes.slice(offset, offset + 11))
    }
    const fetchMock = vi.fn().mockResolvedValue(responseWithChunks(chunks))
    vi.stubGlobal('fetch', fetchMock)

    await streamChat(request, handlers)

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/chat/stream',
      expect.objectContaining({ method: 'POST', body: JSON.stringify(request) }),
    )
    expect(handlers.onTool).toHaveBeenCalledWith(tool)
    expect(handlers.onToken).toHaveBeenCalledWith({ content: '工资被拖欠' })
    expect(handlers.onSources).toHaveBeenCalledWith({ items: [citation] })
    expect(handlers.onDone).toHaveBeenCalledWith({
      message_id: 12,
      answer_style: 'plain',
      refused: false,
    })
    expect(handlers.onToken).toHaveBeenCalledTimes(1)
  })

  it('treats error as terminal and never dispatches later frames', async () => {
    const stream = [
      'event: error\ndata: {"code":50302,"message":"模型服务暂不可用"}\n\n',
      'event: token\ndata: {"content":"忽略"}\n\n',
    ].join('')
    const bytes = new TextEncoder().encode(stream)
    const fetchMock = vi.fn().mockResolvedValue(
      responseWithChunks([bytes]),
    )
    vi.stubGlobal('fetch', fetchMock)

    await streamChat(request, handlers)

    expect(handlers.onError).toHaveBeenCalledWith({ code: 50302, message: '模型服务暂不可用' })
    expect(handlers.onToken).not.toHaveBeenCalled()
    expect(handlers.onDone).not.toHaveBeenCalled()
  })

  it('rejects a stream that ends without a terminal event', async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"content":"未完成"}\n\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responseWithChunks([bytes])))

    await expect(streamChat(request, handlers)).rejects.toThrow('聊天数据流意外结束')
  })

  it('converts pre-stream HTTP errors into the API error message', async () => {
    const response = {
      ok: false,
      status: 503,
      json: async () => ({ code: 50301, message: '知识库尚未就绪', data: null }),
    } as Response
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    await expect(streamChat(request, handlers)).rejects.toThrow('知识库尚未就绪')
  })
})
