import type { components } from './api.generated'

export type AnswerStyle = 'plain' | 'legal'
export type CitationItem = components['schemas']['CitationItem']
export type ToolExecutionItem = components['schemas']['ToolExecutionItem']

export interface ChatRequest {
  session_id: string
  question: string
  answer_style: AnswerStyle
}

export interface ChatStreamHandlers {
  onTool?: (data: ToolExecutionItem) => void
  onToken: (data: { content: string }) => void
  onSources: (data: { items: CitationItem[] }) => void
  onDone: (data: { message_id: number; answer_style: AnswerStyle; refused: boolean }) => void
  onError: (data: { code: number; message: string }) => void
}

export type ChatStreamEvent =
  | { event: 'tool'; data: ToolExecutionItem }
  | { event: 'token'; data: { content: string } }
  | { event: 'sources'; data: { items: CitationItem[] } }
  | { event: 'done'; data: { message_id: number; answer_style: AnswerStyle; refused: boolean } }
  | { event: 'error'; data: { code: number; message: string } }
