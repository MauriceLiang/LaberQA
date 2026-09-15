<script setup lang="ts">
import { ElPagination } from 'element-plus'

import type { ChunkItem } from '@/api/documents'

defineProps<{
  chunks: ChunkItem[]
  loading: boolean
  page: number
  size: number
  total: number
  selectedId?: number
}>()

const emit = defineEmits<{
  select: [chunk: ChunkItem]
  page: [page: number]
  size: [size: number]
}>()

function summarize(content: string) {
  const compact = content.replace(/\s+/g, ' ').trim()
  return compact.length > 180 ? `${compact.slice(0, 180)}…` : compact
}
</script>

<template>
  <section class="chunk-list" aria-labelledby="chunks-title">
    <div class="section-heading">
      <div>
        <h2 id="chunks-title">文本分块</h2>
        <p>共 {{ total }} 个分块，选择一项查看完整原文。</p>
      </div>
    </div>

    <div v-loading="loading" class="chunk-items">
      <p v-if="!loading && chunks.length === 0" class="empty-copy">该资料尚无可查看的分块。</p>
      <button
        v-for="chunk in chunks"
        :key="chunk.id"
        class="chunk-item"
        :class="{ 'chunk-item-selected': chunk.id === selectedId }"
        type="button"
        @click="emit('select', chunk)"
      >
        <span class="chunk-number">Chunk {{ chunk.chunk_no }}</span>
        <span class="chunk-summary">{{ summarize(chunk.content) }}</span>
      </button>
    </div>

    <ElPagination
      v-if="total > 0"
      class="chunk-pagination"
      background
      layout="prev, pager, next, sizes"
      :current-page="page"
      :page-size="size"
      :page-sizes="[10, 20, 50]"
      :total="total"
      @current-change="(nextPage: number) => emit('page', nextPage)"
      @size-change="(nextSize: number) => emit('size', nextSize)"
    />
  </section>
</template>
