<script setup lang="ts">
import { CirclePlus, Document } from '@element-plus/icons-vue'

defineProps<{
  sessionId: string
  historyLoading: boolean
  streaming: boolean
}>()

defineEmits<{
  newSession: []
}>()
</script>

<template>
  <header class="session-header">
    <div class="session-header-actions">
      <button
        class="new-session-button"
        type="button"
        :disabled="historyLoading || streaming"
        @click="$emit('newSession')"
      >
        <CirclePlus aria-hidden="true" />
        <span>新建对话</span>
      </button>
      <span class="knowledge-pill">
        <Document aria-hidden="true" />
        <span>基于已导入资料回答</span>
      </span>
    </div>
    <span class="session-status" aria-live="polite">
      <span v-if="historyLoading">正在恢复会话记录…</span>
      <span v-else-if="streaming">正在生成回答</span>
      <span v-else-if="sessionId">当前对话已保存</span>
    </span>
  </header>
</template>
