import type { components, paths } from '@/types/api.generated'
import { http } from '@/api/http'

export type ExperimentConfig = components['schemas']['ExperimentConfig']
export type ExperimentCreate = components['schemas']['ExperimentCreate']
export type ExperimentCaseScope = 'BUILTIN_BASELINE' | 'ALL_ACTIVE' | 'SELECTED'
export type ExperimentSummary = components['schemas']['ExperimentSummary'] & {
  archived_at?: string | null
}
export type ExperimentDetail = components['schemas']['ExperimentDetail'] & {
  config_names?: string[]
  archived_at?: string | null
}
export type ExperimentJob = components['schemas']['ExperimentJob']
export type ExperimentConfigResult = components['schemas']['ExperimentConfigResult']
export type ExperimentStatus = components['schemas']['JobStatus']
export type CitationItem = components['schemas']['CitationItem']
type GeneratedExperimentPage = NonNullable<
  paths['/api/retrieval-experiments']['get']['responses'][200]['content']['application/json']['data']
>
export type ExperimentPage = Omit<GeneratedExperimentPage, 'items'> & {
  items: ExperimentSummary[]
}

export interface ExperimentQuery {
  page: number
  size: number
  status?: ExperimentStatus
  include_archived?: boolean
}

export interface RetrievalStrategy {
  id: number
  name: string
  description: string
  builtin_key: string | null
  config: ExperimentConfig
  is_builtin: boolean
  version: number
  is_active: boolean
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface RetrievalStrategyPayload {
  name: string
  description: string
  config: ExperimentConfig
}

export interface RetrievalStrategyVersion {
  id: number
  strategy_id: number
  version: number
  name: string
  description: string
  config: ExperimentConfig
  created_at: string
}

export interface RetrievalTraceStage {
  stage: string
  status: 'completed' | 'skipped' | 'failed'
  detail: string
  duration_ms: number | null
}

export interface RetrievalPreview {
  question: string
  rewritten_question: string
  answer: string
  refused: boolean
  retrieval_ms: number
  retrieved_sources: CitationItem[]
  citations: CitationItem[]
  trace: RetrievalTraceStage[]
  config: ExperimentConfig
}

export async function getExperiments(query: ExperimentQuery): Promise<ExperimentPage> {
  const response = await http.get<ExperimentPage>('/retrieval-experiments', { params: query })
  return response.data
}

export async function createExperiment(payload: ExperimentCreate & { config_names?: string[]; case_scope?: ExperimentCaseScope }): Promise<ExperimentJob> {
  const response = await http.post<ExperimentJob>('/retrieval-experiments', payload)
  return response.data
}

export async function getExperiment(id: number): Promise<ExperimentDetail> {
  const response = await http.get<ExperimentDetail>(`/retrieval-experiments/${id}`)
  return response.data
}

export async function listRetrievalStrategies(params?: { include_archived?: boolean }): Promise<RetrievalStrategy[]> {
  const response = await http.get<RetrievalStrategy[]>('/retrieval-strategies', { params })
  return response.data
}

export async function createRetrievalStrategy(payload: RetrievalStrategyPayload): Promise<RetrievalStrategy> {
  const response = await http.post<RetrievalStrategy>('/retrieval-strategies', payload)
  return response.data
}

export async function updateRetrievalStrategy(id: number, payload: RetrievalStrategyPayload): Promise<RetrievalStrategy> {
  const response = await http.patch<RetrievalStrategy>(`/retrieval-strategies/${id}`, payload)
  return response.data
}

export async function listRetrievalStrategyVersions(id: number): Promise<RetrievalStrategyVersion[]> {
  const response = await http.get<RetrievalStrategyVersion[]>(`/retrieval-strategies/${id}/versions`)
  return response.data
}

export async function restoreRetrievalStrategyVersion(id: number, version: number): Promise<RetrievalStrategy> {
  const response = await http.post<RetrievalStrategy>(`/retrieval-strategies/${id}/versions/${version}/restore`)
  return response.data
}

export async function setRetrievalStrategyActive(id: number, isActive: boolean): Promise<RetrievalStrategy> {
  const response = await http.patch<RetrievalStrategy>(`/retrieval-strategies/${id}/status`, { is_active: isActive })
  return response.data
}

export async function archiveRetrievalStrategy(id: number): Promise<RetrievalStrategy> {
  const response = await http.post<RetrievalStrategy>(`/retrieval-strategies/${id}/archive`)
  return response.data
}

export async function restoreRetrievalStrategy(id: number): Promise<RetrievalStrategy> {
  const response = await http.post<RetrievalStrategy>(`/retrieval-strategies/${id}/restore`)
  return response.data
}

export async function deleteRetrievalStrategy(id: number): Promise<void> {
  await http.delete(`/retrieval-strategies/${id}`)
}

export async function previewRetrieval(payload: {
  question: string
  answer_style: 'plain' | 'legal'
  config: ExperimentConfig
}): Promise<RetrievalPreview> {
  const response = await http.post<RetrievalPreview>('/retrieval-experiments/preview', payload)
  return response.data
}

export async function deleteExperiment(id: number): Promise<void> {
  await http.delete(`/retrieval-experiments/${id}`)
}

export async function archiveRetrievalExperiment(id: number): Promise<ExperimentSummary> {
  const response = await http.post<ExperimentSummary>(`/retrieval-experiments/${id}/archive`)
  return response.data
}

export async function restoreRetrievalExperiment(id: number): Promise<ExperimentSummary> {
  const response = await http.post<ExperimentSummary>(`/retrieval-experiments/${id}/restore`)
  return response.data
}

export async function exportRetrievalExperiment(id: number): Promise<string> {
  const response = await http.get<string>(`/retrieval-experiments/${id}/export`)
  return response.data
}

export async function copyExperiment(id: number, name: string): Promise<ExperimentJob> {
  const response = await http.post<ExperimentJob>(`/retrieval-experiments/${id}/copy`, { name })
  return response.data
}
