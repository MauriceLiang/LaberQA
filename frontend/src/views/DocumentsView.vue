<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElAlert, ElButton } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import ChunkDetail from '@/components/documents/ChunkDetail.vue'
import ChunkList from '@/components/documents/ChunkList.vue'
import DocumentList from '@/components/documents/DocumentList.vue'
import DocumentUpload from '@/components/documents/DocumentUpload.vue'
import {
  getDocument,
  getDocumentChunks,
  getDocuments,
  reimportDocument,
  type ChunkItem,
  type DocumentItem,
  type DocumentUploadAccepted,
} from '@/api/documents'
import { getErrorMessage } from '@/api/http'

const POLL_INTERVAL_MS = 2000

const documents = ref<DocumentItem[]>([])
const totalDocuments = ref(0)
const documentPage = ref(1)
const documentPageSize = ref(10)
const keyword = ref('')
const status = ref<DocumentItem['status'] | ''>('')
const selectedDocumentId = ref<number>()
const pageLoading = ref(false)
const pageError = ref('')
const actionError = ref('')

const chunks = ref<ChunkItem[]>([])
const totalChunks = ref(0)
const chunkPage = ref(1)
const chunkPageSize = ref(10)
const chunksLoading = ref(false)
const selectedChunk = ref<ChunkItem>()
const chunkDetailVisible = ref(false)

let pollingTimer: ReturnType<typeof setInterval> | undefined
let pollingInProgress = false
let isMounted = false
let documentRequestId = 0
let chunkRequestId = 0
const trackedProcessingIds = new Set<number>()

const selectedDocument = computed(() =>
  documents.value.find((document) => document.id === selectedDocumentId.value),
)

function stopPolling() {
  if (pollingTimer !== undefined) {
    clearInterval(pollingTimer)
    pollingTimer = undefined
  }
}

function syncPolling() {
  stopPolling()
  if (!isMounted || trackedProcessingIds.size === 0) return
  pollingTimer = setInterval(() => void pollProcessingDocuments(), POLL_INTERVAL_MS)
}

function clearSelection() {
  chunkRequestId += 1
  selectedDocumentId.value = undefined
  chunks.value = []
  totalChunks.value = 0
  chunksLoading.value = false
  selectedChunk.value = undefined
  chunkDetailVisible.value = false
}

function upsertDocument(document: DocumentItem) {
  const index = documents.value.findIndex((item) => item.id === document.id)
  if (index >= 0) {
    documents.value[index] = document
    return
  }
  documents.value.unshift(document)
  if (documents.value.length > documentPageSize.value) documents.value.pop()
}

async function selectInitialDocument() {
  if (selectedDocumentId.value !== undefined || documents.value.length === 0) return
  const document = documents.value.find((item) => item.status === 'SUCCESS') ?? documents.value[0]
  selectedDocumentId.value = document.id
  chunkPage.value = 1
  if (document.status === 'SUCCESS') await loadChunks()
}

async function loadDocuments() {
  const requestId = ++documentRequestId
  pageLoading.value = true
  pageError.value = ''
  try {
    const result = await getDocuments({
      page: documentPage.value,
      size: documentPageSize.value,
      keyword: keyword.value || undefined,
      status: status.value || undefined,
    })
    if (!isMounted || requestId !== documentRequestId) return
    for (const document of documents.value) {
      if (document.status === 'PROCESSING') trackedProcessingIds.add(document.id)
    }
    for (const document of result.items) {
      if (document.status === 'PROCESSING') trackedProcessingIds.add(document.id)
      else trackedProcessingIds.delete(document.id)
    }
    documents.value = result.items
    totalDocuments.value = result.total
    if (!documents.value.some((document) => document.id === selectedDocumentId.value)) {
      clearSelection()
    }
    syncPolling()
    await selectInitialDocument()
  } catch (error) {
    if (requestId === documentRequestId) pageError.value = getErrorMessage(error)
  } finally {
    if (requestId === documentRequestId) pageLoading.value = false
  }
}

async function loadChunks() {
  const requestId = ++chunkRequestId
  const document = selectedDocument.value
  if (!document || document.status !== 'SUCCESS') {
    chunks.value = []
    totalChunks.value = 0
    chunksLoading.value = false
    return
  }

  const requestedPage = chunkPage.value
  const requestedSize = chunkPageSize.value
  chunksLoading.value = true
  actionError.value = ''
  try {
    const result = await getDocumentChunks(document.id, requestedPage, requestedSize)
    if (
      !isMounted ||
      requestId !== chunkRequestId ||
      selectedDocumentId.value !== document.id
    ) return
    chunks.value = result.items
    totalChunks.value = result.total
    if (selectedChunk.value && !chunks.value.some((chunk) => chunk.id === selectedChunk.value?.id)) {
      selectedChunk.value = undefined
      chunkDetailVisible.value = false
    }
  } catch (error) {
    if (requestId === chunkRequestId) {
      actionError.value = `加载分块失败：${getErrorMessage(error)}`
    }
  } finally {
    if (requestId === chunkRequestId) chunksLoading.value = false
  }
}

async function pollProcessingDocuments() {
  if (pollingInProgress) return
  for (const document of documents.value) {
    if (document.status === 'PROCESSING') trackedProcessingIds.add(document.id)
  }
  if (trackedProcessingIds.size === 0) {
    stopPolling()
    return
  }

  pollingInProgress = true
  pageError.value = ''
  let reachedTerminalStatus = false
  try {
    const results = await Promise.all([...trackedProcessingIds].map((id) => getDocument(id)))
    if (!isMounted) return
    for (const updated of results) {
      const index = documents.value.findIndex((document) => document.id === updated.id)
      if (updated.status === 'PROCESSING') trackedProcessingIds.add(updated.id)
      else {
        trackedProcessingIds.delete(updated.id)
        reachedTerminalStatus = true
      }
      if (index < 0) {
        if (selectedDocumentId.value === updated.id) upsertDocument(updated)
        continue
      }
      const previous = documents.value[index]
      documents.value[index] = updated
      if (previous.status === 'PROCESSING' && updated.status !== 'PROCESSING') {
        if (updated.status === 'SUCCESS' && selectedDocumentId.value === updated.id && isMounted) {
          await loadChunks()
        }
      }
    }
  } catch (error) {
    pageError.value = `刷新导入状态失败：${getErrorMessage(error)}`
  } finally {
    pollingInProgress = false
    syncPolling()
  }

  if (reachedTerminalStatus && isMounted) await loadDocuments()
}

async function selectDocument(document: DocumentItem) {
  if (selectedDocumentId.value === document.id) {
    clearSelection()
    return
  }

  selectedDocumentId.value = document.id
  chunkPage.value = 1
  chunks.value = []
  totalChunks.value = 0
  selectedChunk.value = undefined
  chunkDetailVisible.value = false
  if (document.status === 'SUCCESS') await loadChunks()
}

async function onUpload(uploaded: DocumentUploadAccepted) {
  keyword.value = ''
  status.value = ''
  documentPage.value = 1
  selectedDocumentId.value = uploaded.document_id
  chunkPage.value = 1
  chunkRequestId += 1
  chunks.value = []
  totalChunks.value = 0
  chunksLoading.value = false
  selectedChunk.value = undefined
  chunkDetailVisible.value = false
  actionError.value = ''
  trackedProcessingIds.add(uploaded.document_id)
  syncPolling()
  try {
    const [document] = await Promise.all([getDocument(uploaded.document_id), loadDocuments()])
    if (!isMounted) return
    if (document.status === 'PROCESSING') trackedProcessingIds.add(document.id)
    else trackedProcessingIds.delete(document.id)
    upsertDocument(document)
    selectedDocumentId.value = document.id
    syncPolling()
    if (document.status === 'SUCCESS') await loadChunks()
  } catch (error) {
    actionError.value = `上传已受理，但无法读取处理状态：${getErrorMessage(error)}`
  }
}

async function onReimport(document: DocumentItem) {
  actionError.value = ''
  try {
    await reimportDocument(document.id)
    trackedProcessingIds.add(document.id)
    selectedDocumentId.value = document.id
    chunkPage.value = 1
    chunkRequestId += 1
    chunks.value = []
    totalChunks.value = 0
    chunksLoading.value = false
    selectedChunk.value = undefined
    chunkDetailVisible.value = false
    if (status.value === 'FAILED') {
      status.value = ''
      keyword.value = document.file_name
      documentPage.value = 1
    }
    syncPolling()
    const [updated] = await Promise.all([getDocument(document.id), loadDocuments()])
    if (!isMounted) return
    if (updated.status === 'PROCESSING') trackedProcessingIds.add(updated.id)
    else trackedProcessingIds.delete(updated.id)
    upsertDocument(updated)
    selectedDocumentId.value = updated.id
    syncPolling()
    if (updated.status === 'SUCCESS') await loadChunks()
  } catch (error) {
    actionError.value = `重新导入失败：${getErrorMessage(error)}`
  }
}

async function onFilter(query: { keyword: string; status: DocumentItem['status'] | '' }) {
  keyword.value = query.keyword
  status.value = query.status
  documentPage.value = 1
  clearSelection()
  await loadDocuments()
}

async function onDocumentPage(page: number) {
  documentPage.value = page
  clearSelection()
  await loadDocuments()
}

async function onDocumentSize(size: number) {
  documentPageSize.value = size
  documentPage.value = 1
  clearSelection()
  await loadDocuments()
}

async function onChunkPage(page: number) {
  chunkPage.value = page
  await loadChunks()
}

async function onChunkSize(size: number) {
  chunkPageSize.value = size
  chunkPage.value = 1
  await loadChunks()
}

function openChunk(chunk: ChunkItem) {
  selectedChunk.value = chunk
  chunkDetailVisible.value = true
}

onMounted(() => {
  isMounted = true
  void loadDocuments()
})
onUnmounted(() => {
  isMounted = false
  documentRequestId += 1
  chunkRequestId += 1
  stopPolling()
})
</script>

<template>
  <div class="documents-page">
    <section class="page-intro documents-page-intro">
      <div>
        <h1>资料管理</h1>
        <p>导入法规和政策资料，查看解析状态及文本分块。</p>
      </div>
      <ElButton class="document-refresh-button" :loading="pageLoading" @click="loadDocuments">
        <Refresh aria-hidden="true" />
        刷新列表
      </ElButton>
    </section>

    <ElAlert v-if="pageError" :title="pageError" type="error" show-icon :closable="false" />
    <ElAlert v-if="actionError" :title="actionError" type="error" show-icon :closable="true" @close="actionError = ''" />

    <DocumentUpload @uploaded="onUpload" />

    <DocumentList
      :documents="documents"
      :loading="pageLoading"
      :page="documentPage"
      :size="documentPageSize"
      :total="totalDocuments"
      :selected-id="selectedDocumentId"
      :keyword="keyword"
      :status="status"
      @filter="onFilter"
      @page="onDocumentPage"
      @size="onDocumentSize"
      @select="selectDocument"
      @reimport="onReimport"
    />

    <section v-if="selectedDocument" class="selected-document-panel">
      <div class="selected-document-heading">
        <div>
          <h2>{{ selectedDocument.file_name }}</h2>
          <div class="selected-document-meta">
            <span class="document-status" :class="`document-status-${selectedDocument.status.toLowerCase()}`">
              <span class="document-status-dot" aria-hidden="true" />
              {{ selectedDocument.file_type.toUpperCase() }}
            </span>
            <span class="selected-document-meta-divider">·</span>
            <span class="selected-document-status-label">
              {{ selectedDocument.status === 'SUCCESS' ? '已完成' : selectedDocument.status === 'FAILED' ? '处理失败' : '处理中' }}
            </span>
          </div>
        </div>
      </div>

      <p v-if="selectedDocument.status === 'PROCESSING'" class="muted-copy">
        正在解析资料并建立索引，页面每 2 秒自动检查处理状态。
      </p>
      <ElAlert
        v-else-if="selectedDocument.status === 'FAILED'"
        :title="selectedDocument.error_message || '资料处理失败，可重新导入。'"
        type="error"
        show-icon
        :closable="false"
      />
      <ChunkList
        v-else
        :chunks="chunks"
        :loading="chunksLoading"
        :page="chunkPage"
        :size="chunkPageSize"
        :total="totalChunks"
        :selected-id="selectedChunk?.id"
        @select="openChunk"
        @page="onChunkPage"
        @size="onChunkSize"
      />
    </section>

    <ChunkDetail v-model="chunkDetailVisible" :chunk="selectedChunk" />
  </div>
</template>
