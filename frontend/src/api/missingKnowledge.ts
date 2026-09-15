import type { components, paths } from '@/types/api.generated'
import { http } from '@/api/http'

export type MissingKnowledgeItem = components['schemas']['MissingKnowledgeItem']
export type MissingKnowledgeStatus = components['schemas']['MissingKnowledgeStatus']
export type MissingKnowledgePage = NonNullable<
  paths['/api/missing-knowledge']['get']['responses'][200]['content']['application/json']['data']
>
export type MissingKnowledgeSort = 'count_desc' | 'last_seen_desc'

export interface MissingKnowledgeQuery {
  page: number
  size: number
  status?: MissingKnowledgeStatus
  keyword?: string
  sort: MissingKnowledgeSort
}

export interface MissingKnowledgeUpdate {
  status: MissingKnowledgeStatus
  note: string | null
}

export async function getMissingKnowledge(
  query: MissingKnowledgeQuery,
): Promise<MissingKnowledgePage> {
  const response = await http.get<MissingKnowledgePage>('/missing-knowledge', {
    params: query,
  })
  return response.data
}

export async function updateMissingKnowledge(
  id: number,
  payload: MissingKnowledgeUpdate,
): Promise<MissingKnowledgeItem> {
  const response = await http.patch<MissingKnowledgeItem>(
    `/missing-knowledge/${id}`,
    payload,
  )
  return response.data
}
