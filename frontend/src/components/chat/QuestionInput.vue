<script setup lang="ts">
import { ref } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'

import AnswerStyleSwitch from '@/components/chat/AnswerStyleSwitch.vue'
import type { AnswerStyle } from '@/types/sse'

defineProps<{
  modelValue: string
  disabled: boolean
  streaming: boolean
  answerStyle: AnswerStyle
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:answerStyle': [value: AnswerStyle]
  'update:collapsed': [value: boolean]
  submit: []
  stop: []
}>()

const collapsed = ref(false)

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  emit('update:collapsed', collapsed.value)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    emit('submit')
  }
}
</script>

<template>
  <form
    v-if="!collapsed"
    class="question-input"
    @submit.prevent="emit('submit')"
  >
    <label class="sr-only" for="chat-question">输入你的劳动权益问题</label>
    <textarea
      id="chat-question"
      :value="modelValue"
      :disabled="disabled"
      maxlength="2000"
      rows="3"
      placeholder="描述你遇到的情况…"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      @keydown="handleKeydown"
    />
    <div class="question-input-footer">
      <div class="question-input-options">
        <AnswerStyleSwitch
          :model-value="answerStyle"
          :disabled="streaming"
          @update:model-value="emit('update:answerStyle', $event)"
        />
        <span class="input-hint">Enter 发送 · Shift+Enter 换行 · 最多 2000 字</span>
      </div>
      <span class="input-actions">
        <span class="question-count">{{ modelValue.trim().length }}/2000</span>
        <button v-if="streaming" class="secondary-button stop-button" type="button" @click="emit('stop')">
          停止生成
        </button>
        <button
          v-else
          class="primary-button send-button"
          type="submit"
          :disabled="disabled || !modelValue.trim() || modelValue.trim().length > 2000"
        >
          发送问题
        </button>
        <button
          class="question-input-collapse"
          type="button"
          :aria-expanded="!collapsed"
          aria-controls="chat-question"
          aria-label="收起输入框"
          title="收起输入框"
          :disabled="streaming"
          @click="toggleCollapsed"
        >
          <ArrowDown aria-hidden="true" />
        </button>
      </span>
    </div>
  </form>
  <button
    v-else
    class="question-input-expand"
    type="button"
    aria-expanded="false"
    aria-controls="chat-question"
    aria-label="展开输入框"
    title="展开输入框"
    @click="toggleCollapsed"
  >
    <ArrowUp aria-hidden="true" />
  </button>
</template>
