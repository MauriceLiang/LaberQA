import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getErrorMessage } from '@/api/http'
import { listSessions, type SessionItem } from '@/api/sessions'
import type { AnswerStyle } from '@/types/sse'

const SESSION_STORAGE_KEY = 'labor-rights-qa.session-id'

export const useSessionStore = defineStore('session', () => {
  const sessionId = ref(localStorage.getItem(SESSION_STORAGE_KEY) ?? '')
  const answerStyle = ref<AnswerStyle>('plain')
  const recentSessions = ref<SessionItem[]>([])
  const streaming = ref(false)
  const sessionsError = ref('')
  let refreshPromise: Promise<boolean> | null = null

  function setSessionId(value: string) {
    sessionId.value = value
    localStorage.setItem(SESSION_STORAGE_KEY, value)
  }

  function clearSession() {
    sessionId.value = ''
    localStorage.removeItem(SESSION_STORAGE_KEY)
  }

  async function refreshRecentSessions(): Promise<boolean> {
    if (refreshPromise) return refreshPromise

    sessionsError.value = ''
    refreshPromise = listSessions()
      .then((sessions) => {
        recentSessions.value = sessions
        return true
      })
      .catch((error: unknown) => {
        sessionsError.value = getErrorMessage(error)
        return false
      })
      .finally(() => {
        refreshPromise = null
      })

    return refreshPromise
  }

  function setStreaming(value: boolean) {
    streaming.value = value
  }

  return {
    sessionId,
    answerStyle,
    recentSessions,
    streaming,
    sessionsError,
    setSessionId,
    clearSession,
    refreshRecentSessions,
    setStreaming,
  }
})
