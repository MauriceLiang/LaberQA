import axios from 'axios'

import type { paths } from '@/types/api.generated'

type HealthResponse = paths['/api/health']['get']['responses'][200]['content']['application/json']
export type HealthData = NonNullable<HealthResponse['data']>

interface ApiResponse<T> {
  code: number
  message: string
  data: T | null
}

export class ApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
  timeout: 8000,
})

http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiResponse<unknown>
    if (body.code !== 0) {
      throw new ApiError(body.code, body.message || '后端请求失败')
    }
    return { ...response, data: body.data }
  },
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const requestId = error.response?.headers['x-request-id']
      if (requestId) console.error(`API request failed (X-Request-ID: ${requestId})`)

      const body: unknown = error.response?.data
      if (
        typeof body === 'object' &&
        body !== null &&
        'code' in body &&
        typeof body.code === 'number' &&
        'message' in body &&
        typeof body.message === 'string'
      ) {
        return Promise.reject(new ApiError(body.code, body.message))
      }
    }
    return Promise.reject(error)
  },
)

export async function getHealth(): Promise<HealthData> {
  const response = await http.get<HealthData>('/health')
  return response.data
}
