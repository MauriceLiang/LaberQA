<script setup lang="ts">
import { ElDialog } from 'element-plus'

import type { ChunkItem } from '@/api/documents'

defineProps<{ chunk?: ChunkItem; modelValue: boolean }>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    :title="chunk ? `Chunk ${chunk.chunk_no} 原文` : 'Chunk 原文'"
    width="min(760px, 92vw)"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <pre v-if="chunk" class="chunk-content">{{ chunk.content }}</pre>
  </ElDialog>
</template>
