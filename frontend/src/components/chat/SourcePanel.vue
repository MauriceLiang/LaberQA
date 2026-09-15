<script setup lang="ts">
import type { CitationItem } from '@/types/sse'

defineProps<{
  citations: CitationItem[]
}>()
</script>

<template>
  <details v-if="citations.length" class="source-panel">
    <summary>参考资料（{{ citations.length }}）</summary>
    <article v-for="citation in citations" :key="citation.chunk_id" class="source-item">
      <div class="source-meta">
        <strong>{{ citation.file_name }}</strong>
        <span>第 {{ citation.chunk_no }} 段</span>
        <span>相关度 {{ citation.score.toFixed(2) }}</span>
      </div>
      <p>{{ citation.content }}</p>
    </article>
    <p class="source-footnote">相关度用于检索排序参考，不代表答案正确率。</p>
  </details>
</template>
