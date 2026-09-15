import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import ChatView from '@/views/ChatView.vue'

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
  ],
})

export default router
