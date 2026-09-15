<script setup lang="ts">
import type { ToolExecutionItem } from '@/types/sse'

defineProps<{
  executions: ToolExecutionItem[]
}>()
</script>

<template>
  <section v-if="executions.length" class="tool-panel" aria-label="辅助材料清单">
    <h3>材料清单</h3>
    <ul v-for="execution in executions" :key="`${execution.tool_name}-${execution.input.description}`">
      <li v-for="material in execution.output.materials" :key="material">{{ material }}</li>
      <li class="tool-note">{{ execution.output.note }}</li>
    </ul>
  </section>
</template>
