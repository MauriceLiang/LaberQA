<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { useSystemStore } from '@/stores/system'

type StatusState = 'ok' | 'warning' | 'error' | 'pending'

interface StatusRow {
  label: string
  value: string
  state: StatusState
}

const system = useSystemStore()
const lastCheckedAt = ref<string | null>(null)

const statusRows = computed<StatusRow[]>(() => {
  const health = system.health

  if (!health) {
    const state: StatusState = system.loading ? 'pending' : 'error'
    const value = system.loading ? '检查中…' : '未连接'
    return [
      { label: 'API 服务', value, state },
      { label: 'SQLite 数据库', value, state },
      { label: '向量索引', value, state },
      { label: '本地 Embedding', value, state },
      { label: 'Embedding Provider', value, state },
      { label: 'Embedding 模型', value, state },
      { label: '索引兼容性', value, state },
      { label: '旧版 DOC 转换', value, state },
      { label: 'LLM API', value, state },
    ]
  }

  return [
    {
      label: 'API 服务',
      value: health.service === 'ok' ? '已连接' : '异常',
      state: health.service === 'ok' ? 'ok' : 'error',
    },
    {
      label: 'SQLite 数据库',
      value: health.database === 'ok' ? '正常' : '不可用',
      state: health.database === 'ok' ? 'ok' : 'error',
    },
    {
      label: '向量索引',
      value: health.vector_store === 'ready' ? '已就绪' : formatStatus(health.vector_store),
      state: health.vector_store === 'ready' ? 'ok' : 'warning',
    },
    {
      label: '本地 Embedding',
      value: health.embedding_ready ? '模型已缓存' : '模型未缓存',
      state: health.embedding_ready ? 'ok' : 'warning',
    },
    {
      label: 'Embedding Provider',
      value: health.embedding_provider === 'local' ? '本地模型' : 'API 模型',
      state: 'ok',
    },
    {
      label: 'Embedding 模型',
      value: health.embedding_model,
      state: 'ok',
    },
    {
      label: '索引兼容性',
      value: health.embedding_index_compatible ? '兼容' : '需要重建',
      state: health.embedding_index_compatible ? 'ok' : 'warning',
    },
    {
      label: '旧版 DOC 转换',
      value: health.doc_converter === 'ready' ? '可用' : '不可用',
      state: health.doc_converter === 'ready' ? 'ok' : 'warning',
    },
    {
      label: 'LLM API',
      value: health.llm_configured ? '已配置' : '未配置',
      state: health.llm_configured ? 'ok' : 'warning',
    },
  ]
})

const overallStatus = computed(() => {
  if (system.loading && !system.health) return { label: '正在检查服务状态', state: 'pending' as StatusState }
  if (!system.health) return { label: '无法连接后端服务', state: 'error' as StatusState }

  const hasIssue = statusRows.value.some((row) => row.state === 'error' || row.state === 'warning')
  return {
    label: hasIssue ? '部分服务需要处理' : '服务运行正常',
    state: hasIssue ? 'warning' as StatusState : 'ok' as StatusState,
  }
})

const checkedAtLabel = computed(() => {
  if (!lastCheckedAt.value) return '尚未检查'

  const date = new Date(lastCheckedAt.value)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
})

function formatStatus(value: string) {
  const labels: Record<string, string> = {
    not_initialized: '未初始化',
    unavailable: '不可用',
    rebuilding: '重建中',
  }
  return labels[value] ?? value
}

async function checkHealth() {
  await system.refreshHealth()
  lastCheckedAt.value = new Date().toISOString()
}

onMounted(() => {
  void checkHealth()
})
</script>

<template>
  <section class="system-page" :aria-busy="system.loading">
    <header class="page-intro documents-page-intro">
      <div class="system-page-heading">
        <h1>系统运行状态</h1>
        <p class="system-description">查看 API、数据库、向量索引与模型配置是否正常。</p>
      </div>

      <div class="system-page-actions">
        <button class="system-check-button" type="button" :disabled="system.loading" @click="checkHealth">
          <Refresh :class="{ 'system-refresh-icon-spinning': system.loading }" aria-hidden="true" />
          <span>{{ system.loading ? '检查中…' : '检查后端连接' }}</span>
        </button>
        <p class="system-last-checked">最近检查 · {{ checkedAtLabel }}</p>
      </div>
    </header>

    <p v-if="system.error" class="system-error" role="alert">{{ system.error }}</p>

    <section class="system-overall-status" :class="`system-status-${overallStatus.state}`" aria-live="polite">
      <span class="system-overall-dot" aria-hidden="true"></span>
      <strong>{{ overallStatus.label }}</strong>
    </section>

    <div class="system-status-list" role="list" aria-label="系统组件状态">
      <div v-for="row in statusRows" :key="row.label" class="system-status-row" role="listitem">
        <span class="system-status-label">{{ row.label }}</span>
        <span class="system-status-value" :class="`system-status-${row.state}`">
          <span class="system-status-dot" aria-hidden="true"></span>
          <span>{{ row.value }}</span>
        </span>
      </div>
    </div>
  </section>
</template>
