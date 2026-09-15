import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { AnswerStyle } from '@/types/sse'

const SESSION_STORAGE_KEY = 'labor-rights-qa.session-id'

export const useSessionStore = defineStore('session', () => {
  const sessionId = ref(localStorage.getItem(SESSION_STORAGE_KEY) ?? '')
  const answerStyle = ref<AnswerStyle>('plain')

  function setSessionId(value: string) {
    sessionId.value = value
    localStorage.setItem(SESSION_STORAGE_KEY, value)
  }

  function clearSession() {
    sessionId.value = ''
    localStorage.removeItem(SESSION_STORAGE_KEY)
  }

  return { sessionId, answerStyle, setSessionId, clearSession }
})
