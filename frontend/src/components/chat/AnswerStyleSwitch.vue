<script setup lang="ts">
import type { AnswerStyle } from '@/types/sse'

defineProps<{
  modelValue: AnswerStyle
  disabled: boolean
}>()

defineEmits<{
  'update:modelValue': [value: AnswerStyle]
}>()
</script>

<template>
  <div class="answer-style-switch" role="group" aria-label="回答风格">
    <button
      type="button"
      :aria-pressed="modelValue === 'plain'"
      :disabled="disabled"
      @click="$emit('update:modelValue', 'plain')"
    >
      通俗解释
    </button>
    <span class="answer-style-divider" aria-hidden="true">/</span>
    <button
      type="button"
      :aria-pressed="modelValue === 'legal'"
      :disabled="disabled"
      @click="$emit('update:modelValue', 'legal')"
    >
      法律条文风格
    </button>
  </div>
</template>
