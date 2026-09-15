<script setup lang="ts">
import { onMounted } from 'vue'

import { useSystemStore } from '@/stores/system'

const system = useSystemStore()

onMounted(() => {
  void system.refreshHealth()
})
</script>

<template>
  <section class="welcome-card">
    <div>
      <p class="eyebrow">项目初始化</p>
      <h2>前后端骨架已就绪</h2>
      <p class="welcome-copy">
        这里会逐步接入法规资料管理、知识库检索和有来源依据的劳动权益问答。
      </p>
    </div>
    <el-button type="primary" :loading="system.loading" @click="system.refreshHealth">
      检查后端连接
    </el-button>
  </section>

  <el-alert
    v-if="system.error"
    class="health-alert"
    :title="system.error"
    type="error"
    show-icon
    :closable="false"
  />

  <el-card class="status-card" shadow="never">
    <template #header>
      <div class="card-heading">
        <span>系统健康状态</span>
        <el-tag v-if="system.health?.service === 'ok'" type="success">API 已连接</el-tag>
        <el-tag v-else-if="!system.loading" type="danger">未连接</el-tag>
      </div>
    </template>

    <el-skeleton v-if="system.loading && !system.health" :rows="4" animated />
    <el-descriptions v-else-if="system.health" :column="2" border>
      <el-descriptions-item label="SQLite">
        {{ system.health.database }}
      </el-descriptions-item>
      <el-descriptions-item label="向量索引">
        {{ system.health.vector_store }}
      </el-descriptions-item>
      <el-descriptions-item label="本地 Embedding">
        {{ system.health.embedding_ready ? '模型已缓存' : '模型尚未缓存' }}
      </el-descriptions-item>
      <el-descriptions-item label="Embedding Provider">
        {{ system.health.embedding_provider }}
      </el-descriptions-item>
      <el-descriptions-item label="Embedding 模型">
        {{ system.health.embedding_model }}
      </el-descriptions-item>
      <el-descriptions-item label="索引兼容性">
        {{
          system.health.vector_store === 'not_initialized'
            ? '尚未建立'
            : system.health.embedding_index_compatible
              ? '兼容'
              : '需要重建'
        }}
      </el-descriptions-item>
      <el-descriptions-item label="旧版 DOC 转换">
        {{ system.health.doc_converter }}
      </el-descriptions-item>
      <el-descriptions-item label="LLM API">
        {{ system.health.llm_configured ? '已配置' : '尚未配置' }}
      </el-descriptions-item>
    </el-descriptions>
    <el-empty v-else description="连接后端后显示初始化状态" :image-size="72" />
  </el-card>
</template>
