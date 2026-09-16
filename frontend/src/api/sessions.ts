import type { components } from '@/types/api.generated'
import { http } from '@/api/http'

export type SessionItem = components['schemas']['SessionItem']
export type MessageItem = components['schemas']['MessageItem']

export async function createSession(title?: string): Promise<SessionItem> {
  const response = await http.post<SessionItem>('/sessions', title ? { title } : {})
  return response.data
}

export async function listSessions(limit = 20): Promise<SessionItem[]> {
  const response = await http.get<SessionItem[]>('/sessions', { params: { limit } })
  return response.data
}

export async function getSessionMessages(sessionId: string): Promise<MessageItem[]> {
  const response = await http.get<MessageItem[]>(`/sessions/${sessionId}/messages`)
  return response.data
}
