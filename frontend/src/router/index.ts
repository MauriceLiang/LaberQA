import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import ChatView from '@/views/ChatView.vue'
import MissingKnowledgeView from '@/views/MissingKnowledgeView.vue'
import EvaluationView from '@/views/EvaluationView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: ChatView,
    },
    {
      path: '/system',
      name: 'system',
      component: HomeView,
    },
    {
      path: '/documents',
      name: 'documents',
      component: DocumentsView,
    },
    {
      path: '/missing-knowledge',
      name: 'missing-knowledge',
      component: MissingKnowledgeView,
    },
    {
      path: '/evaluations',
      name: 'evaluations',
      component: EvaluationView,
    },
  ],
})

export default router
