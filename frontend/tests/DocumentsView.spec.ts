import { nextTick } from 'vue'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPage, DocumentItem, DocumentPage } from '@/api/documents'
import * as documentsApi from '@/api/documents'
import { ApiError } from '@/api/http'
import DocumentsView from '@/views/DocumentsView.vue'
import ChunkDetail from '@/components/documents/ChunkDetail.vue'
import ChunkList from '@/components/documents/ChunkList.vue'
import DocumentList from '@/components/documents/DocumentList.vue'
import DocumentUpload from '@/components/documents/DocumentUpload.vue'

vi.mock('@/api/documents', () => ({
  deleteDocument: vi.fn(),
  getDocument: vi.fn(),
  getDocumentChunks: vi.fn(),
  getDocuments: vi.fn(),
  reimportDocument: vi.fn(),
  uploadDocument: vi.fn(),
}))

const processingDocument: DocumentItem = {
  id: 7,
  file_name: '法规.txt',
  file_type: 'txt',
  status: 'PROCESSING',
  chunk_count: 0,
  error_message: null,
  created_at: '2026-09-15T00:00:00Z',
  updated_at: '2026-09-15T00:00:00Z',
}

const successDocument: DocumentItem = {
  ...processingDocument,
  status: 'SUCCESS',
  chunk_count: 1,
  updated_at: '2026-09-15T00:00:02Z',
}
const failedDocument: DocumentItem = {
  ...processingDocument,
  status: 'FAILED',
  error_message: 'LibreOffice 不可用',
  updated_at: '2026-09-15T00:00:02Z',
}
const secondDocument: DocumentItem = {
  ...successDocument,
  id: 8,
  file_name: '第二份资料.txt',
}

function page(items: DocumentItem[]) {
  return { items, page: 1, size: 10, total: items.length, pages: items.length ? 1 : 0 }
}

function mountView() {
  return shallowMount(DocumentsView, {
    global: {
      stubs: {
        ElAlert: {
          props: ['title'],
          template: '<div role="alert">{{ title }}</div>',
        },
        ElButton: true,
        ElTag: true,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  vi.mocked(documentsApi.getDocuments).mockResolvedValue(page([]))
  vi.mocked(documentsApi.getDocument).mockResolvedValue(successDocument)
  vi.mocked(documentsApi.getDocumentChunks).mockResolvedValue({
    items: [{ id: 11, document_id: 7, chunk_no: 1, content: '完整原文', vector_key: 'chunk-11' }],
    page: 1,
    size: 10,
    total: 1,
    pages: 1,
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('DocumentsView', () => {
  it('passes an empty page to the list after loading completes', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.getComponent(DocumentList).props('documents')).toEqual([])
    expect(wrapper.getComponent(DocumentList).props('total')).toBe(0)
    expect(wrapper.getComponent(DocumentList).props('loading')).toBe(false)
    wrapper.unmount()
  })

  it('selects the first successful document and loads its chunks for the initial view', async () => {
    vi.mocked(documentsApi.getDocuments).mockResolvedValueOnce(page([successDocument, secondDocument]))
    const initialChunkPage: ChunkPage = {
      items: [{ id: 31, document_id: successDocument.id, chunk_no: 1, content: '首屏分块', vector_key: 'chunk-31' }],
      page: 1,
      size: 10,
      total: 1,
      pages: 1,
    }
    vi.mocked(documentsApi.getDocumentChunks).mockResolvedValueOnce(initialChunkPage)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.getComponent(DocumentList).props('selectedId')).toBe(successDocument.id)
    expect(wrapper.getComponent(ChunkList).props('chunks')).toEqual(initialChunkPage.items)
    expect(documentsApi.getDocumentChunks).toHaveBeenCalledWith(successDocument.id, 1, 10)
    wrapper.unmount()
  })

  it('collapses the selected document chunks when the same row is clicked again', async () => {
    vi.mocked(documentsApi.getDocuments).mockResolvedValueOnce(page([successDocument]))
    vi.mocked(documentsApi.getDocumentChunks).mockResolvedValueOnce({
      items: [{ id: 31, document_id: successDocument.id, chunk_no: 1, content: '首屏分块', vector_key: 'chunk-31' }],
      page: 1,
      size: 10,
      total: 1,
      pages: 1,
    })

    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.getComponent(DocumentList).props('selectedId')).toBe(successDocument.id)
    expect(wrapper.getComponent(ChunkList).props('chunks')).toHaveLength(1)

    wrapper.getComponent(DocumentList).vm.$emit('select', successDocument)
    await nextTick()

    expect(wrapper.getComponent(DocumentList).props('selectedId')).toBeUndefined()
    expect(wrapper.findComponent(ChunkList).exists()).toBe(false)
    expect(wrapper.getComponent(ChunkDetail).props('modelValue')).toBe(false)
    expect(documentsApi.getDocumentChunks).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('shows the API error when the document list cannot load', async () => {
    vi.mocked(documentsApi.getDocuments).mockRejectedValueOnce(new ApiError(500, '读取资料失败'))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('读取资料失败')
    wrapper.unmount()
  })

  it('keeps the loading state visible while the list request is pending', () => {
    vi.mocked(documentsApi.getDocuments).mockReturnValue(new Promise(() => {}))
    const wrapper = mountView()

    return nextTick().then(() => {
      expect(wrapper.getComponent(DocumentList).props('loading')).toBe(true)
      wrapper.unmount()
    })
  })

  it('polls an uploaded document until success, loads chunks, and leaves no timer', async () => {
    vi.useFakeTimers()
    vi.mocked(documentsApi.getDocuments)
      .mockResolvedValueOnce(page([]))
      .mockResolvedValueOnce(page([processingDocument]))
      .mockResolvedValueOnce(page([successDocument]))
    vi.mocked(documentsApi.getDocument)
      .mockResolvedValueOnce(processingDocument)
      .mockResolvedValueOnce(successDocument)
    const wrapper = mountView()
    await flushPromises()

    wrapper.getComponent(DocumentUpload).vm.$emit('uploaded', {
      document_id: processingDocument.id,
      file_name: processingDocument.file_name,
      status: 'PROCESSING',
    })
    await flushPromises()
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(documentsApi.getDocument).toHaveBeenCalledWith(processingDocument.id)
    expect(documentsApi.getDocumentChunks).toHaveBeenCalledWith(processingDocument.id, 1, 10)
    expect(vi.getTimerCount()).toBe(0)
    wrapper.unmount()
  })

  it('loads chunks when upload status is already successful and closes the previous detail', async () => {
    const previousChunk = {
      id: 11,
      document_id: successDocument.id,
      chunk_no: 1,
      content: '旧资料原文',
      vector_key: 'chunk-11',
    }
    const uploadedChunk = {
      ...previousChunk,
      id: 22,
      document_id: secondDocument.id,
      content: '新资料原文',
      vector_key: 'chunk-22',
    }
    vi.mocked(documentsApi.getDocuments)
      .mockResolvedValueOnce(page([successDocument]))
      .mockResolvedValueOnce(page([secondDocument]))
    vi.mocked(documentsApi.getDocument).mockResolvedValueOnce(secondDocument)
    vi.mocked(documentsApi.getDocumentChunks)
      .mockResolvedValueOnce({ items: [previousChunk], page: 1, size: 10, total: 1, pages: 1 })
      .mockResolvedValueOnce({ items: [uploadedChunk], page: 1, size: 10, total: 1, pages: 1 })
    const wrapper = mountView()
    await flushPromises()

    wrapper.getComponent(ChunkList).vm.$emit('select', previousChunk)
    await nextTick()
    expect(wrapper.getComponent(ChunkDetail).props('modelValue')).toBe(true)

    wrapper.getComponent(DocumentUpload).vm.$emit('uploaded', {
      document_id: secondDocument.id,
      file_name: secondDocument.file_name,
      status: 'PROCESSING',
    })
    await flushPromises()

    expect(documentsApi.getDocumentChunks).toHaveBeenLastCalledWith(secondDocument.id, 1, 10)
    expect(wrapper.getComponent(ChunkDetail).props('modelValue')).toBe(false)
    expect(wrapper.getComponent(ChunkDetail).props('chunk')).toBeUndefined()
    wrapper.unmount()
  })

  it('clears the poll timer when the page is unmounted', async () => {
    vi.useFakeTimers()
    vi.mocked(documentsApi.getDocuments).mockResolvedValueOnce(page([processingDocument]))
    const wrapper = mountView()
    await flushPromises()
    expect(vi.getTimerCount()).toBe(1)

    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(4000)
    expect(documentsApi.getDocument).not.toHaveBeenCalled()
  })

  it('requires confirmation before deleting a document and refreshes after success', async () => {
    vi.mocked(documentsApi.getDocuments)
      .mockResolvedValueOnce(page([successDocument]))
      .mockResolvedValueOnce(page([]))
    vi.mocked(documentsApi.deleteDocument).mockResolvedValueOnce()
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce(new Error('cancel'))
    const wrapper = mountView()
    await flushPromises()

    wrapper.getComponent(DocumentList).vm.$emit('delete', successDocument)
    await nextTick()
    expect(confirm).toHaveBeenCalledWith(
      '将同时删除该资料的文本分块、向量索引和上传文件，删除后不可恢复。',
      `确定删除“${successDocument.file_name}”吗？`,
      expect.objectContaining({ confirmButtonText: '删除', cancelButtonText: '取消' }),
    )
    expect(documentsApi.deleteDocument).not.toHaveBeenCalled()

    confirm.mockResolvedValueOnce(undefined as never)
    wrapper.getComponent(DocumentList).vm.$emit('delete', successDocument)
    await flushPromises()

    expect(documentsApi.deleteDocument).toHaveBeenCalledWith(successDocument.id)
    expect(wrapper.getComponent(DocumentList).props('documents')).toEqual([])
    expect(wrapper.getComponent(DocumentList).props('selectedId')).toBeUndefined()
    wrapper.unmount()
  })

  it('does not restart polling when an in-flight status request finishes after unmount', async () => {
    vi.useFakeTimers()
    vi.mocked(documentsApi.getDocuments).mockResolvedValueOnce(page([processingDocument]))
    let resolveStatus!: (value: DocumentItem) => void
    vi.mocked(documentsApi.getDocument).mockReturnValueOnce(
      new Promise((resolve) => { resolveStatus = resolve }),
    )
    const wrapper = mountView()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)
    expect(documentsApi.getDocument).toHaveBeenCalledWith(processingDocument.id)

    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    resolveStatus(successDocument)
    await flushPromises()

    expect(vi.getTimerCount()).toBe(0)
    expect(documentsApi.getDocumentChunks).not.toHaveBeenCalled()
    expect(documentsApi.getDocuments).toHaveBeenCalledTimes(1)
  })

  it('stops polling on failure and allows reimport', async () => {
    vi.useFakeTimers()
    vi.mocked(documentsApi.getDocuments)
      .mockResolvedValueOnce(page([failedDocument]))
      .mockResolvedValueOnce(page([failedDocument]))
      .mockResolvedValueOnce(page([processingDocument]))
      .mockResolvedValueOnce(page([failedDocument]))
    vi.mocked(documentsApi.getDocument)
      .mockResolvedValueOnce(processingDocument)
      .mockResolvedValueOnce(failedDocument)
    vi.mocked(documentsApi.reimportDocument).mockResolvedValue()
    const wrapper = mountView()
    await flushPromises()

    wrapper.getComponent(DocumentList).vm.$emit('filter', { keyword: '', status: 'FAILED' })
    await flushPromises()
    expect(wrapper.getComponent(DocumentList).props('status')).toBe('FAILED')

    wrapper.getComponent(DocumentList).vm.$emit('reimport', failedDocument)
    await flushPromises()
    expect(documentsApi.reimportDocument).toHaveBeenCalledWith(failedDocument.id)
    expect(wrapper.getComponent(DocumentList).props('status')).toBe('')
    expect(wrapper.getComponent(DocumentList).props('keyword')).toBe(failedDocument.file_name)
    expect(documentsApi.getDocuments).toHaveBeenLastCalledWith({
      page: 1,
      size: 10,
      keyword: failedDocument.file_name,
      status: undefined,
    })
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(wrapper.getComponent(DocumentList).props('documents')).toEqual([failedDocument])
    expect(wrapper.text()).toContain(failedDocument.error_message)
    expect(vi.getTimerCount()).toBe(0)
    wrapper.unmount()
  })

  it('ignores an older list response after a newer filter request', async () => {
    let resolveInitial!: (value: DocumentPage) => void
    const initialRequest = new Promise<DocumentPage>((resolve) => { resolveInitial = resolve })
    vi.mocked(documentsApi.getDocuments)
      .mockReset()
      .mockReturnValueOnce(initialRequest)
      .mockResolvedValueOnce(page([successDocument]))
    const wrapper = mountView()
    await nextTick()

    wrapper.getComponent(DocumentList).vm.$emit('filter', { keyword: '法规', status: '' })
    await flushPromises()
    expect(wrapper.getComponent(DocumentList).props('documents')).toEqual([successDocument])

    resolveInitial(page([failedDocument]))
    await flushPromises()
    expect(wrapper.getComponent(DocumentList).props('documents')).toEqual([successDocument])
    wrapper.unmount()
  })

  it('ignores an older chunk response after switching documents', async () => {
    const oldChunkPage: ChunkPage = {
      items: [{ id: 21, document_id: 7, chunk_no: 1, content: '旧分块', vector_key: 'chunk-21' }],
      page: 1,
      size: 10,
      total: 1,
      pages: 1,
    }
    const newChunkPage: ChunkPage = {
      items: [{ id: 22, document_id: 8, chunk_no: 1, content: '新分块', vector_key: 'chunk-22' }],
      page: 1,
      size: 10,
      total: 1,
      pages: 1,
    }
    let resolveOldChunks!: (value: ChunkPage) => void
    const oldRequest = new Promise<ChunkPage>((resolve) => { resolveOldChunks = resolve })
    vi.mocked(documentsApi.getDocuments).mockResolvedValueOnce(page([successDocument, secondDocument]))
    vi.mocked(documentsApi.getDocumentChunks)
      .mockReset()
      .mockResolvedValueOnce({ items: [], page: 1, size: 10, total: 0, pages: 0 })
      .mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce(newChunkPage)
    const wrapper = mountView()
    await flushPromises()

    wrapper.getComponent(DocumentList).vm.$emit('select', secondDocument)
    wrapper.getComponent(DocumentList).vm.$emit('select', successDocument)
    await flushPromises()
    expect(wrapper.getComponent(ChunkList).props('chunks')).toEqual(newChunkPage.items)

    resolveOldChunks(oldChunkPage)
    await flushPromises()
    expect(wrapper.getComponent(ChunkList).props('chunks')).toEqual(newChunkPage.items)
    wrapper.unmount()
  })
})
