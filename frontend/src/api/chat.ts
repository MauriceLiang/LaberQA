import type { ChatRequest, ChatStreamHandlers } from '@/types/sse'
import { ApiError, getErrorMessage, http } from '@/api/http'

export async function streamChat(
  payload: ChatRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const baseUrl = String(http.defaults.baseURL).replace(/\/+$/, '')
  const response = await fetch(`${baseUrl}/chat/stream`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    let body: unknown
    try {
      body = await response.json()
    } catch {
      body = null
    }
    const error = body as { code?: unknown; message?: unknown } | null
    throw new ApiError(
      typeof error?.code === 'number' ? error.code : response.status,
      typeof error?.message === 'string' ? error.message : '聊天请求失败',
    )
  }
  if (!response.body) throw new Error('后端未返回聊天数据流')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminalEventReceived = false

  try {
    while (!terminalEventReceived) {
      const { value, done } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })

      let boundary = /\r?\n\r?\n/.exec(buffer)
      while (boundary) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        terminalEventReceived = dispatchFrame(frame, handlers)
        if (terminalEventReceived) break
        boundary = /\r?\n\r?\n/.exec(buffer)
      }

      if (done) break
    }
  } finally {
    if (terminalEventReceived) await reader.cancel()
    reader.releaseLock()
  }

  if (!signal?.aborted && !terminalEventReceived) {
    throw new Error('聊天数据流意外结束')
  }
}

function dispatchFrame(frame: string, handlers: ChatStreamHandlers): boolean {
  const lines = frame.split(/\r?\n/)
  const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
  const data = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')

  if (!event || !data) return false
  const payload: unknown = JSON.parse(data)

  switch (event) {
    case 'tool':
      handlers.onTool?.(payload as Parameters<NonNullable<ChatStreamHandlers['onTool']>>[0])
      return false
    case 'token':
      handlers.onToken(payload as Parameters<ChatStreamHandlers['onToken']>[0])
      return false
    case 'sources':
      handlers.onSources(payload as Parameters<ChatStreamHandlers['onSources']>[0])
      return false
    case 'done':
      handlers.onDone(payload as Parameters<ChatStreamHandlers['onDone']>[0])
      return true
    case 'error':
      handlers.onError(payload as Parameters<ChatStreamHandlers['onError']>[0])
      return true
    default:
      return false
  }
}

export function getChatApiError(error: unknown): string {
  if (error instanceof TypeError) return '无法连接后端，请检查服务是否已启动'
  return getErrorMessage(error)
}
