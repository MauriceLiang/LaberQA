<script setup lang="ts">
defineProps<{
  modelValue: string
  disabled: boolean
  streaming: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  stop: []
}>()

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    emit('submit')
  }
}
</script>

<template>
  <form class="question-input" @submit.prevent="emit('submit')">
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
      <span class="input-hint">Enter 发送 · Shift+Enter 换行 · 最多 2000 字</span>
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
      </span>
    </div>
  </form>
</template>
