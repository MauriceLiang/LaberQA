import type { components, paths } from '@/types/api.generated'
import { http } from '@/api/http'

export type DocumentItem = components['schemas']['DocumentItem']
export type ChunkItem = components['schemas']['ChunkItem']
export type DocumentUploadAccepted = components['schemas']['DocumentUploadAccepted']
export type DocumentPage = NonNullable<
  paths['/api/documents']['get']['responses'][200]['content']['application/json']['data']
>
export type ChunkPage = NonNullable<
  paths['/api/documents/{id}/chunks']['get']['responses'][200]['content']['application/json']['data']
>

export interface DocumentQuery {
  page: number
  size: number
  status?: DocumentItem['status']
  keyword?: string
}

export async function getDocuments(query: DocumentQuery): Promise<DocumentPage> {
  const response = await http.get<DocumentPage>('/documents', { params: query })
  return response.data
}

export async function getDocument(id: number): Promise<DocumentItem> {
  const response = await http.get<DocumentItem>(`/documents/${id}`)
  return response.data
}

export async function uploadDocument(file: File): Promise<DocumentUploadAccepted> {
  const body = new FormData()
  body.append('file', file)
  const response = await http.post<DocumentUploadAccepted>('/documents/upload', body, {
    timeout: 60_000,
  })
  return response.data
}

export async function reimportDocument(id: number): Promise<void> {
  await http.post(`/documents/${id}/reimport`)
}

export async function getDocumentChunks(
  id: number,
  page: number,
  size: number,
): Promise<ChunkPage> {
  const response = await http.get<ChunkPage>(`/documents/${id}/chunks`, {
    params: { page, size },
  })
  return response.data
}
