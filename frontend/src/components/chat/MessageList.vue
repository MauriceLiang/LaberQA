<script setup lang="ts">
import type { UiMessage } from '@/types/chat'

import SourcePanel from '@/components/chat/SourcePanel.vue'
import ToolPanel from '@/components/chat/ToolPanel.vue'

defineProps<{
  messages: UiMessage[]
  historyLoading: boolean
}>()
</script>

<template>
  <div class="message-list" role="log" aria-live="polite" aria-relevant="additions text">
    <div v-if="!messages.length && !historyLoading" class="chat-empty-state">
      <h3>你好，有什么劳动权益问题？</h3>
      <p>请描述你遇到的情况，我们会基于相关法律法规为你解答。</p>
      <div class="suggested-questions">
        <slot name="suggestions" />
      </div>
    </div>

    <div v-else-if="historyLoading" class="chat-loading-history" role="status">
      正在加载这段对话…
    </div>

    <article
      v-for="message in messages"
      :key="message.key"
      class="message-row"
      :class="`message-${message.role}`"
    >
      <div class="message-avatar" :aria-label="message.role === 'user' ? '我' : 'AI 助手'">
        {{ message.role === 'user' ? '我' : '答' }}
      </div>
      <div class="message-content">
        <p class="message-label">{{ message.role === 'user' ? '我' : '劳动权益助手' }}</p>
        <div class="message-bubble" :class="{ 'message-bubble-streaming': message.status === 'streaming' }">
          <p v-if="message.content" class="message-text">{{ message.content }}</p>
          <p v-else-if="message.status === 'streaming'" class="message-pending">正在整理资料并生成回答…</p>
        </div>
        <p v-if="message.refused" class="message-refusal-note">
          当前资料不足以支持可靠判断。
        </p>
        <p v-if="message.status === 'stopped'" class="message-state">已停止生成</p>
        <p v-if="message.status === 'error'" class="message-state message-state-error">
          回答未完成；可以重新提问。
        </p>
        <ToolPanel :executions="message.toolExecutions" />
        <SourcePanel :citations="message.citations" />
      </div>
    </article>
  </div>
</template>
