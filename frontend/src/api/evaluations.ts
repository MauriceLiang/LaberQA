import type { components, paths } from '@/types/api.generated'
import { http } from '@/api/http'

export type EvaluationRunSummary = components['schemas']['EvaluationRunSummary']
export type EvaluationRunDetail = components['schemas']['EvaluationRunDetail']
export type EvaluationRunJob = components['schemas']['EvaluationRunJob']
export type EvaluationMetrics = components['schemas']['EvaluationMetrics']
export type EvaluationResultItem = components['schemas']['EvaluationResultItem']
export type EvaluationCasePage = {
  items: EvaluationCase[]
  page: number
  size: number
  total: number
  pages: number
}
export type EvaluationRunPage = NonNullable<
  paths['/api/evaluations/runs']['get']['responses'][200]['content']['application/json']['data']
>
export type EvaluationExpectedType = components['schemas']['EvaluationExpectedType']
export type EvaluationJobStatus = components['schemas']['JobStatus']
export type EvaluationAnswerStyle = components['schemas']['AnswerStyle']

export type EvaluationCaseOrigin = 'BUILTIN' | 'CUSTOM'
export type EvaluationCaseStatus = 'ACTIVE' | 'ARCHIVED'
export type EvaluationCaseScope = 'BUILTIN_BASELINE' | 'ALL_ACTIVE' | 'SELECTED'

export interface EvaluationExpectedSource {
  file_name: string
  chunk_no: number | null
}

export interface EvaluationCase {
  id: number
  topic: string
  expected_type: EvaluationExpectedType
  turns: string[]
  expected_points: string[]
  expected_sources: EvaluationExpectedSource[]
  should_show_compliance: boolean
  origin: EvaluationCaseOrigin
  status: EvaluationCaseStatus
  version: number
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface EvaluationCaseInput {
  topic: string
  expected_type: EvaluationExpectedType
  turns: string[]
  expected_points: string[]
  expected_sources: EvaluationExpectedSource[]
  should_show_compliance: boolean
}

export interface EvaluationCaseUpdate extends EvaluationCaseInput {
  version: number
}

export interface EvaluationCaseQuery {
  page: number
  size: number
  topic?: string
  expected_type?: EvaluationExpectedType
  is_multi_turn?: boolean
  origin?: EvaluationCaseOrigin
  status?: EvaluationCaseStatus
  include_archived?: boolean
}

export interface EvaluationRunQuery {
  page: number
  size: number
  status?: EvaluationJobStatus
}

export interface EvaluationRunCreate {
  name: string
  case_ids: number[] | null
  answer_style: EvaluationAnswerStyle
  case_scope: EvaluationCaseScope
}

export async function getEvaluationCases(
  query: EvaluationCaseQuery,
): Promise<EvaluationCasePage> {
  const response = await http.get<EvaluationCasePage>('/evaluations/cases', { params: query })
  return response.data
}

export async function createEvaluationCase(
  payload: EvaluationCaseInput,
): Promise<EvaluationCase> {
  const response = await http.post<EvaluationCase>('/evaluations/cases', payload)
  return response.data
}

export async function getEvaluationCase(id: number): Promise<EvaluationCase> {
  const response = await http.get<EvaluationCase>(`/evaluations/cases/${id}`)
  return response.data
}

export async function updateEvaluationCase(
  id: number,
  payload: EvaluationCaseUpdate,
): Promise<EvaluationCase> {
  const response = await http.patch<EvaluationCase>(`/evaluations/cases/${id}`, payload)
  return response.data
}

export async function deleteEvaluationCase(id: number): Promise<void> {
  await http.delete(`/evaluations/cases/${id}`)
}

export async function getEvaluationRuns(query: EvaluationRunQuery): Promise<EvaluationRunPage> {
  const response = await http.get<EvaluationRunPage>('/evaluations/runs', { params: query })
  return response.data
}

export async function createEvaluationRun(payload: EvaluationRunCreate): Promise<EvaluationRunJob> {
  const response = await http.post<EvaluationRunJob>('/evaluations/runs', payload)
  return response.data
}

export async function getEvaluationRun(id: number): Promise<EvaluationRunDetail> {
  const response = await http.get<EvaluationRunDetail>(`/evaluations/runs/${id}`)
  return response.data
}

export async function deleteEvaluationRun(id: number): Promise<void> {
  await http.delete(`/evaluations/runs/${id}`)
}
