<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElButton, ElInput, ElOption, ElPagination, ElSelect } from 'element-plus'
import { ArrowRight, Delete, Filter, Search } from '@element-plus/icons-vue'

import type { DocumentItem } from '@/api/documents'

const props = defineProps<{
  documents: DocumentItem[]
  loading: boolean
  page: number
  size: number
  total: number
  selectedId?: number
  deletingId?: number
  keyword: string
  status: DocumentItem['status'] | ''
}>()

const emit = defineEmits<{
  filter: [query: { keyword: string; status: DocumentItem['status'] | '' }]
  page: [page: number]
  size: [size: number]
  select: [document: DocumentItem]
  reimport: [document: DocumentItem]
  delete: [document: DocumentItem]
}>()

const draftKeyword = ref(props.keyword)
const draftStatus = ref(props.status)
const statusLabels: Record<DocumentItem['status'], string> = {
  PROCESSING: '处理中',
  SUCCESS: '已完成',
  FAILED: '失败',
}
watch(() => props.keyword, (value) => { draftKeyword.value = value })
watch(() => props.status, (value) => { draftStatus.value = value })

function applyFilters() {
  emit('filter', { keyword: draftKeyword.value.trim(), status: draftStatus.value })
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function statusLabel(status: DocumentItem['status']) {
  return statusLabels[status]
}

function statusClass(status: DocumentItem['status']) {
  return `document-status-${status.toLowerCase()}`
}

function selectRow(row: unknown) {
  emit('select', row as DocumentItem)
}

function requestReimport(document: unknown) {
  emit('reimport', document as DocumentItem)
}

function requestDelete(document: unknown) {
  emit('delete', document as DocumentItem)
}

function selectWithKeyboard(event: KeyboardEvent, document: DocumentItem) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    selectRow(document)
  }
}
</script>

<template>
  <section class="document-list" aria-labelledby="documents-title">
    <div class="section-heading">
      <div>
        <h2 id="documents-title">资料列表</h2>
        <p>选择已完成的资料，可查看其文本分块。</p>
      </div>
      <div class="document-filters">
        <ElInput
          v-model="draftKeyword"
          clearable
          placeholder="按文件名搜索"
          aria-label="按文件名搜索"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        >
          <template #prefix><Search aria-hidden="true" /></template>
        </ElInput>
        <ElSelect v-model="draftStatus" clearable placeholder="全部状态" aria-label="按处理状态筛选">
          <ElOption label="处理中" value="PROCESSING" />
          <ElOption label="已完成" value="SUCCESS" />
          <ElOption label="失败" value="FAILED" />
        </ElSelect>
        <ElButton class="document-filter-button" @click="applyFilters">
          <Filter aria-hidden="true" />
          筛选
        </ElButton>
      </div>
    </div>

    <div v-loading="loading" class="document-table-wrap">
      <table class="document-data-table">
        <thead>
          <tr>
            <th scope="col">文件名</th>
            <th scope="col">格式</th>
            <th scope="col">状态</th>
            <th scope="col">Chunk 数</th>
            <th scope="col">创建时间</th>
            <th scope="col">处理说明</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="document in documents"
            :key="document.id"
            class="document-data-row"
            :class="{ 'selected-document-row': document.id === selectedId }"
            :aria-selected="document.id === selectedId"
            tabindex="0"
            @click="selectRow(document)"
            @keydown="selectWithKeyboard($event, document)"
          >
            <td class="document-name-cell" :title="document.file_name">{{ document.file_name }}</td>
            <td class="document-format-cell">{{ document.file_type.toUpperCase() }}</td>
            <td>
              <span class="document-status" :class="statusClass(document.status)">
                <span class="document-status-dot" aria-hidden="true" />
                {{ statusLabel(document.status) }}
              </span>
            </td>
            <td>{{ document.chunk_count ?? '—' }}</td>
            <td class="document-created-cell">{{ formatDate(document.created_at) }}</td>
            <td class="document-description-cell">
              <span v-if="document.status === 'FAILED'" class="failure-message">
                {{ document.error_message || '处理失败' }}
              </span>
              <span v-else-if="document.status === 'PROCESSING'" class="muted-copy">正在解析并建立索引</span>
              <span v-else class="muted-copy">—</span>
            </td>
            <td>
              <div class="document-operation-actions">
                <ElButton
                  v-if="document.status === 'FAILED'"
                  class="document-reimport-button"
                  :disabled="deletingId === document.id"
                  @click.stop="requestReimport(document)"
                >
                  重新导入
                  <ArrowRight aria-hidden="true" />
                </ElButton>
                <ElButton
                  class="document-delete-button"
                  :disabled="deletingId === document.id"
                  :aria-busy="deletingId === document.id"
                  @click.stop="requestDelete(document)"
                >
                  <Delete aria-hidden="true" />
                  {{ deletingId === document.id ? '删除中…' : '删除' }}
                </ElButton>
              </div>
            </td>
          </tr>
          <tr v-if="!loading && documents.length === 0" class="document-empty-row">
            <td colspan="7">暂无资料</td>
          </tr>
        </tbody>
      </table>
    </div>

    <ElPagination
      v-if="total > 0"
      class="document-pagination"
      background
      layout="total, sizes, prev, pager, next"
      :current-page="page"
      :page-size="size"
      :page-sizes="[10, 20, 50]"
      :total="total"
      @current-change="(nextPage: number) => emit('page', nextPage)"
      @size-change="(nextSize: number) => emit('size', nextSize)"
    />
  </section>
</template>
