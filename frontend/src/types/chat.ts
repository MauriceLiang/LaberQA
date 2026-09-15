import type { AnswerStyle, CitationItem, ToolExecutionItem } from '@/types/sse'

export interface UiMessage {
  key: string
  id: number | null
  role: 'user' | 'assistant'
  content: string
  citations: CitationItem[]
  toolExecutions: ToolExecutionItem[]
  answerStyle: AnswerStyle | null
  refused: boolean
  status: 'complete' | 'streaming' | 'stopped' | 'error'
}
