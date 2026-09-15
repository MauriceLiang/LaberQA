import type { components, paths } from '@/types/api.generated'
import { http } from '@/api/http'

export type EvaluationCase = components['schemas']['EvaluationCase']
export type EvaluationRunSummary = components['schemas']['EvaluationRunSummary']
export type EvaluationRunDetail = components['schemas']['EvaluationRunDetail']
export type EvaluationRunJob = components['schemas']['EvaluationRunJob']
export type EvaluationMetrics = components['schemas']['EvaluationMetrics']
export type EvaluationResultItem = components['schemas']['EvaluationResultItem']
export type EvaluationCasePage = NonNullable<
  paths['/api/evaluations/cases']['get']['responses'][200]['content']['application/json']['data']
>
export type EvaluationRunPage = NonNullable<
  paths['/api/evaluations/runs']['get']['responses'][200]['content']['application/json']['data']
>
export type EvaluationExpectedType = components['schemas']['EvaluationExpectedType']
export type EvaluationJobStatus = components['schemas']['JobStatus']
export type EvaluationAnswerStyle = components['schemas']['AnswerStyle']

export interface EvaluationCaseQuery {
  page: number
  size: number
  topic?: string
  expected_type?: EvaluationExpectedType
  is_multi_turn?: boolean
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
}

export async function getEvaluationCases(
  query: EvaluationCaseQuery,
): Promise<EvaluationCasePage> {
  const response = await http.get<EvaluationCasePage>('/evaluations/cases', { params: query })
  return response.data
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
