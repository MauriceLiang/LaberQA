<script setup lang="ts">
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
    <div>
      <p class="eyebrow">AI 劳动权益咨询</p>
      <h2>把遇到的问题说清楚</h2>
      <p class="session-status">
        <span v-if="historyLoading">正在恢复会话记录…</span>
        <span v-else-if="streaming">正在生成回答</span>
        <span v-else-if="sessionId">当前对话已保存，可刷新后继续</span>
        <span v-else>回答将结合已导入的法规与政策资料</span>
      </p>
    </div>
    <button
      class="secondary-button new-session-button"
      type="button"
      :disabled="historyLoading"
      @click="$emit('newSession')"
    >
      新建对话
    </button>
  </header>
</template>
