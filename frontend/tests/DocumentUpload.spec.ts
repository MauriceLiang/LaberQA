import { nextTick } from 'vue'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DocumentItem, DocumentUploadAccepted } from '@/api/documents'
import * as documentsApi from '@/api/documents'
import DocumentUpload from '@/components/documents/DocumentUpload.vue'

vi.mock('@/api/documents', () => ({
  getDocument: vi.fn(),
  uploadDocument: vi.fn(),
}))

const buttonStub = {
  props: ['disabled', 'loading'],
  emits: ['click'],
  template: '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function accepted(documentId: number, fileName: string): DocumentUploadAccepted {
  return {
    document_id: documentId,
    file_name: fileName,
    status: 'PROCESSING',
  }
}

function documentStatus(documentId: number, fileName: string, status: DocumentItem['status']): DocumentItem {
  return {
    id: documentId,
    file_name: fileName,
    file_type: fileName.split('.').pop() as DocumentItem['file_type'],
    status,
    chunk_count: status === 'SUCCESS' ? 1 : 0,
    error_message: null,
    created_at: '2026-09-19T00:00:00Z',
    updated_at: '2026-09-19T00:00:00Z',
  }
}

function mountUpload() {
  return shallowMount(DocumentUpload, {
    global: {
      stubs: {
        ElButton: buttonStub,
      },
    },
  })
}

async function chooseFiles(wrapper: ReturnType<typeof mountUpload>, files: File[]) {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: files,
  })
  await input.trigger('change')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('DocumentUpload', () => {
  it('accepts multiple files and waits for each import to finish before the next one', async () => {
    vi.useFakeTimers()
    const firstFile = new File(['# first'], '第一份.md', { type: 'text/markdown' })
    const secondFile = new File(['second'], '第二份.txt', { type: 'text/plain' })
    const firstUpload = deferred<DocumentUploadAccepted>()
    const secondUpload = deferred<DocumentUploadAccepted>()
    vi.mocked(documentsApi.uploadDocument)
      .mockReturnValueOnce(firstUpload.promise)
      .mockReturnValueOnce(secondUpload.promise)
    vi.mocked(documentsApi.getDocument)
      .mockResolvedValueOnce(documentStatus(1, firstFile.name, 'PROCESSING'))
      .mockResolvedValueOnce(documentStatus(1, firstFile.name, 'SUCCESS'))
      .mockResolvedValueOnce(documentStatus(2, secondFile.name, 'SUCCESS'))

    const wrapper = mountUpload()
    await chooseFiles(wrapper, [firstFile, secondFile])

    const input = wrapper.get('input[type="file"]')
    expect(input.attributes('multiple')).toBeDefined()
    expect(wrapper.text()).toContain('已选择 2 个文件')

    await wrapper.get('.upload-submit-button').trigger('click')
    await nextTick()
    expect(documentsApi.uploadDocument).toHaveBeenCalledTimes(1)
    expect(documentsApi.uploadDocument).toHaveBeenNthCalledWith(1, firstFile)
    expect(wrapper.text()).toContain('正在处理第 1 / 2 个文件')

    firstUpload.resolve(accepted(1, firstFile.name))
    await flushPromises()
    expect(documentsApi.uploadDocument).toHaveBeenCalledTimes(1)
    expect(documentsApi.getDocument).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(documentsApi.uploadDocument).toHaveBeenCalledTimes(2)
    expect(documentsApi.uploadDocument).toHaveBeenNthCalledWith(2, secondFile)
    expect(wrapper.text()).toContain('正在处理第 2 / 2 个文件')

    secondUpload.resolve(accepted(2, secondFile.name))
    await flushPromises()
    expect(wrapper.emitted('uploaded')).toEqual([
      [accepted(1, firstFile.name)],
      [accepted(2, secondFile.name)],
    ])
    expect(wrapper.text()).not.toContain('已选择 2 个文件')
    wrapper.unmount()
  })
})
