<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatLineRound,
  CirclePlus,
  Document,
  Histogram,
  Monitor,
  Reading,
  Search,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const navItems = [
  { name: 'chat', label: 'AI 咨询', to: '/', icon: ChatLineRound },
  { name: 'system', label: '系统状态', to: '/system', icon: Monitor },
  { name: 'documents', label: '资料管理', to: '/documents', icon: Document },
  { name: 'missing-knowledge', label: '知识缺口', to: '/missing-knowledge', icon: Reading },
  { name: 'evaluations', label: '问答评测', to: '/evaluations', icon: Histogram },
  { name: 'retrieval-experiments', label: '检索实验', to: '/retrieval-experiments', icon: Search },
]

const recentConversations = [
  { id: 'wage', title: '公司拖欠工资怎么处理' },
  { id: 'contract', title: '未签劳动合同怎么办' },
  { id: 'probation', title: '试用期被辞退怎么算' },
]

const isChatRoute = computed(() => route.name === 'chat')

function openRecentConversation() {
  if (!isChatRoute.value) void router.push('/')
}

function startNewConversation() {
  void router.push('/')
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar" aria-label="应用导航">
      <div class="brand-lockup">
        <div class="brand-symbol" aria-hidden="true">
          <img src="/assets/brand-mark.png" alt="" />
        </div>
        <div>
          <strong>劳动权益咨询问答台</strong>
          <span>LaberQA</span>
        </div>
      </div>

      <nav class="app-nav" aria-label="主导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          :to="item.to"
          class="nav-item"
          :class="{ 'nav-item-active': route.name === item.name }"
        >
          <component :is="item.icon" class="nav-item-icon" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <section class="recent-conversations" aria-labelledby="recent-conversations-title">
        <div class="recent-heading">
          <h2 id="recent-conversations-title">最近对话</h2>
          <button class="recent-add" type="button" aria-label="新建对话" @click="startNewConversation">
            <CirclePlus aria-hidden="true" />
          </button>
        </div>
        <button
          v-for="(conversation, index) in recentConversations"
          :key="conversation.id"
          type="button"
          class="recent-conversation"
          :class="{ 'recent-conversation-active': isChatRoute && index === 0 }"
          @click="openRecentConversation"
        >
          <span>{{ conversation.title }}</span>
        </button>
      </section>

      <p class="legal-note">信息辅助，不替代正式法律意见</p>
    </aside>

    <section class="app-content">
      <header v-if="!isChatRoute" class="app-topbar">
        <div class="app-topbar-left">
          <button class="topbar-new-chat" type="button" @click="startNewConversation">
            <CirclePlus aria-hidden="true" />
            <span>新建对话</span>
          </button>
          <span class="knowledge-pill">
            <Document aria-hidden="true" />
            <span>基于已导入资料回答</span>
          </span>
        </div>
      </header>
      <main class="app-main">
        <router-view />
      </main>
    </section>
  </div>
</template>
