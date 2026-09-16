<script setup lang="ts">
import { computed } from 'vue'

import MarkdownInline from '@/components/chat/MarkdownInline.vue'
import { parseMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
}>()

const blocks = computed(() => parseMarkdown(props.content))
</script>

<template>
  <div class="message-markdown">
    <template v-for="(block, index) in blocks" :key="`${block.type}-${index}`">
      <component :is="`h${block.level}`" v-if="block.type === 'heading'">
        <MarkdownInline :tokens="block.tokens" />
      </component>

      <p v-else-if="block.type === 'paragraph'">
        <MarkdownInline :tokens="block.tokens" />
      </p>

      <ul v-else-if="block.type === 'unordered-list'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <MarkdownInline :tokens="item" />
        </li>
      </ul>

      <ol v-else-if="block.type === 'ordered-list'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <MarkdownInline :tokens="item" />
        </li>
      </ol>

      <blockquote v-else-if="block.type === 'quote'">
        <MarkdownInline :tokens="block.tokens" />
      </blockquote>

      <pre v-else-if="block.type === 'code'"><code>{{ block.code }}</code></pre>
    </template>
  </div>
</template>
