import axios from 'axios'

export interface ApiResponse<T> {
  code: number
  message: string
  data: T | null
}

export interface HealthData {
  service: string
  database: string
  vector_store: string
  doc_converter: string
  llm_configured: boolean
  embedding_provider: string
  embedding_model: string
  embedding_ready: boolean
  embedding_index_compatible: boolean
}

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
  timeout: 8000,
})

export async function getHealth(): Promise<HealthData> {
  const response = await http.get<ApiResponse<HealthData>>('/health')
  if (response.data.code !== 0 || response.data.data === null) {
    throw new Error(response.data.message || '后端健康检查失败')
  }
  return response.data.data
}
