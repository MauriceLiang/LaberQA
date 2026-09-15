<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  ElButton,
  ElInput,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'

import type { DocumentItem } from '@/api/documents'

const props = defineProps<{
  documents: DocumentItem[]
  loading: boolean
  page: number
  size: number
  total: number
  selectedId?: number
  keyword: string
  status: DocumentItem['status'] | ''
}>()

const emit = defineEmits<{
  filter: [query: { keyword: string; status: DocumentItem['status'] | '' }]
  page: [page: number]
  size: [size: number]
  select: [document: DocumentItem]
  reimport: [document: DocumentItem]
}>()

const draftKeyword = ref(props.keyword)
const draftStatus = ref(props.status)
const statusLabels: Record<DocumentItem['status'], string> = {
  PROCESSING: '处理中',
  SUCCESS: '已完成',
  FAILED: '失败',
}
const statusTypes: Record<DocumentItem['status'], 'info' | 'success' | 'danger'> = {
  PROCESSING: 'info',
  SUCCESS: 'success',
  FAILED: 'danger',
}
watch(() => props.keyword, (value) => { draftKeyword.value = value })
watch(() => props.status, (value) => { draftStatus.value = value })

function applyFilters() {
  emit('filter', { keyword: draftKeyword.value.trim(), status: draftStatus.value })
}

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

function statusLabel(status: DocumentItem['status']) {
  return statusLabels[status]
}

function statusType(status: DocumentItem['status']) {
  return statusTypes[status]
}

function selectRow(row: unknown) {
  emit('select', row as DocumentItem)
}

function requestReimport(document: unknown) {
  emit('reimport', document as DocumentItem)
}

function rowClassName({ row }: { row: DocumentItem }) {
  return row.id === props.selectedId ? 'selected-document-row' : ''
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
        />
        <ElSelect v-model="draftStatus" clearable placeholder="全部状态" aria-label="按处理状态筛选">
          <ElOption label="处理中" value="PROCESSING" />
          <ElOption label="已完成" value="SUCCESS" />
          <ElOption label="失败" value="FAILED" />
        </ElSelect>
        <ElButton @click="applyFilters">筛选</ElButton>
      </div>
    </div>

    <ElTable
      v-loading="loading"
      :data="documents"
      :row-class-name="rowClassName"
      row-key="id"
      empty-text="暂无资料"
      @row-click="selectRow"
    >
      <ElTableColumn prop="file_name" label="文件名" min-width="180" show-overflow-tooltip />
      <ElTableColumn label="格式" width="90">
        <template #default="scope">
          {{ scope.row.file_type.toUpperCase() }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="110">
        <template #default="scope">
          <ElTag :type="statusType(scope.row.status)">{{ statusLabel(scope.row.status) }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="chunk_count" label="Chunk 数" width="100" />
      <ElTableColumn label="创建时间" min-width="170">
        <template #default="scope">
          {{ formatDate(scope.row.created_at) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="处理说明" min-width="190" show-overflow-tooltip>
        <template #default="scope">
          <span v-if="scope.row.status === 'FAILED'" class="failure-message">
            {{ scope.row.error_message || '处理失败' }}
          </span>
          <span v-else-if="scope.row.status === 'PROCESSING'" class="muted-copy">正在解析并建立索引</span>
          <span v-else class="muted-copy">—</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="110" fixed="right">
        <template #default="scope">
          <ElButton
            v-if="scope.row.status === 'FAILED'"
            link
            type="primary"
            @click.stop="requestReimport(scope.row)"
          >
            重新导入
          </ElButton>
          <span v-else class="muted-copy">—</span>
        </template>
      </ElTableColumn>
    </ElTable>

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
