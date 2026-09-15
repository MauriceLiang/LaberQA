import type { components, paths } from '@/types/api.generated'
import { http } from '@/api/http'

export type ExperimentConfig = components['schemas']['ExperimentConfig']
export type ExperimentCreate = components['schemas']['ExperimentCreate']
export type ExperimentSummary = components['schemas']['ExperimentSummary']
export type ExperimentDetail = components['schemas']['ExperimentDetail']
export type ExperimentJob = components['schemas']['ExperimentJob']
export type ExperimentConfigResult = components['schemas']['ExperimentConfigResult']
export type ExperimentStatus = components['schemas']['JobStatus']
export type ExperimentPage = NonNullable<
  paths['/api/retrieval-experiments']['get']['responses'][200]['content']['application/json']['data']
>

export interface ExperimentQuery {
  page: number
  size: number
  status?: ExperimentStatus
}

export async function getExperiments(query: ExperimentQuery): Promise<ExperimentPage> {
  const response = await http.get<ExperimentPage>('/retrieval-experiments', { params: query })
  return response.data
}

export async function createExperiment(payload: ExperimentCreate): Promise<ExperimentJob> {
  const response = await http.post<ExperimentJob>('/retrieval-experiments', payload)
  return response.data
}

export async function getExperiment(id: number): Promise<ExperimentDetail> {
  const response = await http.get<ExperimentDetail>(`/retrieval-experiments/${id}`)
  return response.data
}
