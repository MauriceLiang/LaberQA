<script setup lang="ts">
import { nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'

import MessageList from '@/components/chat/MessageList.vue'
import QuestionInput from '@/components/chat/QuestionInput.vue'
import SessionHeader from '@/components/chat/SessionHeader.vue'
import { getChatApiError, streamChat } from '@/api/chat'
import { createSession, getSessionMessages } from '@/api/sessions'
import { ApiError } from '@/api/http'
import { useSessionStore } from '@/stores/session'
import type { UiMessage } from '@/types/chat'

const sessionStore = useSessionStore()
const messages = ref<UiMessage[]>([])
const question = ref('')
const chatError = ref('')
const streaming = ref(false)
const historyLoading = ref(false)
const conversation = ref<HTMLElement | null>(null)

let activeController: AbortController | null = null
let activeRequestId = 0
let scrollFrame: number | null = null
let restoreRequestId = 0
let skipSessionRestoreFor: string | null = null

const suggestions = [
  '公司拖欠工资，我应该准备什么材料？',
  '没有签劳动合同，我可以怎么处理？',
  '试用期被辞退，工资应该怎么算？',
]

onBeforeUnmount(() => {
  activeController?.abort()
  sessionStore.setStreaming(false)
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
})

watch(
  () => sessionStore.sessionId,
  (sessionId) => {
    if (sessionId && sessionId === skipSessionRestoreFor) {
      skipSessionRestoreFor = null
      return
    }
    const requestId = ++restoreRequestId
    resetConversation()
    if (sessionId) void restoreSession(sessionId, requestId)
  },
  { immediate: true },
)

watch(
  messages,
  async () => {
    await nextTick()
    scheduleConversationScroll()
  },
  { deep: true },
)

function scheduleConversationScroll() {
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)

  if (typeof window.requestAnimationFrame !== 'function') {
    scrollConversationToBottom()
    return
  }

  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = null
    scrollConversationToBottom()
  })
}

function scrollConversationToBottom() {
  if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight
}

async function restoreSession(sessionId: string, requestId: number) {
  historyLoading.value = true
  chatError.value = ''
  try {
    const history = await getSessionMessages(sessionId)
    if (requestId !== restoreRequestId || sessionStore.sessionId !== sessionId) return
    messages.value = history.map((message) => ({
      key: String(message.id),
      id: message.id,
      role: message.role,
      content: message.content,
      citations: message.citations,
      toolExecutions: message.tool_executions,
      answerStyle: message.answer_style,
      refused: message.refused ?? false,
      status: 'complete',
    }))
  } catch (error) {
    if (requestId !== restoreRequestId || sessionStore.sessionId !== sessionId) return
    messages.value = []
    if (error instanceof ApiError && error.code === 40402) sessionStore.clearSession()
    chatError.value = `无法恢复上次对话：${getChatApiError(error)}`
  } finally {
    if (requestId === restoreRequestId) historyLoading.value = false
  }
}

function resetConversation() {
  activeRequestId += 1
  activeController?.abort()
  activeController = null
  streaming.value = false
  sessionStore.setStreaming(false)
  messages.value = []
  question.value = ''
  chatError.value = ''
}

async function startNewSession() {
  if (streaming.value || historyLoading.value) return
  const saved = await sessionStore.refreshRecentSessions()
  if (!saved) {
    chatError.value = `无法保存当前对话：${sessionStore.sessionsError}`
    return
  }
  sessionStore.clearSession()
}

function setQuestion(value: string) {
  question.value = value
  if (chatError.value) chatError.value = ''
}

async function sendQuestion() {
  const content = question.value.trim()
  if (!content || content.length > 2000 || streaming.value || historyLoading.value) return

  chatError.value = ''
  question.value = ''
  const requestId = ++activeRequestId
  const userMessage: UiMessage = {
    key: `user-${requestId}`,
    id: null,
    role: 'user',
    content,
    citations: [],
    toolExecutions: [],
    answerStyle: null,
    refused: false,
    status: 'complete',
  }
  const assistantMessage = reactive<UiMessage>({
    key: `assistant-${requestId}`,
    id: null,
    role: 'assistant',
    content: '',
    citations: [],
    toolExecutions: [],
    answerStyle: sessionStore.answerStyle,
    refused: false,
    status: 'streaming',
  })
  messages.value.push(userMessage, assistantMessage)
  streaming.value = true
  sessionStore.setStreaming(true)

  const controller = new AbortController()
  activeController = controller

  try {
    let sessionId = sessionStore.sessionId
    if (!sessionId) {
      const session = await createSession(content.slice(0, 100))
      if (requestId !== activeRequestId) return
      sessionId = session.id
      skipSessionRestoreFor = sessionId
      sessionStore.setSessionId(sessionId)
    }
    if (controller.signal.aborted) {
      removeEmptyAssistant(assistantMessage)
      return
    }

    await streamChat(
      {
        session_id: sessionId,
        question: content,
        answer_style: sessionStore.answerStyle,
      },
      {
        onTool: (execution) => {
          if (requestId === activeRequestId) assistantMessage.toolExecutions.push(execution)
        },
        onToken: ({ content: token }) => {
          if (requestId === activeRequestId) assistantMessage.content += token
        },
        onSources: ({ items }) => {
          if (requestId === activeRequestId) assistantMessage.citations = items
        },
        onDone: ({ message_id, answer_style, refused }) => {
          if (requestId !== activeRequestId) return
          assistantMessage.id = message_id
          assistantMessage.answerStyle = answer_style
          assistantMessage.refused = refused
          assistantMessage.status = 'complete'
        },
        onError: ({ message }) => {
          if (requestId !== activeRequestId) return
          assistantMessage.status = 'error'
          chatError.value = message
        },
      },
      controller.signal,
    )

    if (requestId === activeRequestId && controller.signal.aborted) {
      removeEmptyAssistant(assistantMessage)
      return
    }
    if (requestId === activeRequestId && assistantMessage.status === 'streaming') {
      assistantMessage.status = 'error'
      chatError.value = '回答流未正常结束，请重试。'
    }
  } catch (error) {
    if (requestId !== activeRequestId) return
    if (controller.signal.aborted || (error instanceof Error && error.name === 'AbortError')) {
      if (assistantMessage.content) assistantMessage.status = 'stopped'
      else removeEmptyAssistant(assistantMessage)
    } else {
      assistantMessage.status = 'error'
      chatError.value = getChatApiError(error)
    }
  } finally {
    if (requestId === activeRequestId) {
      streaming.value = false
      sessionStore.setStreaming(false)
      activeController = null
      void sessionStore.refreshRecentSessions()
    }
  }
}

function stopGeneration() {
  activeController?.abort()
}

function removeEmptyAssistant(message: UiMessage) {
  if (!message.content) {
    messages.value = messages.value.filter((item) => item.key !== message.key)
  } else {
    message.status = 'stopped'
  }
}

function useSuggestion(value: string) {
  question.value = value
}
</script>

<template>
  <section class="chat-page">
    <SessionHeader
      :session-id="sessionStore.sessionId"
      :history-loading="historyLoading"
      :streaming="streaming"
      @new-session="startNewSession"
    />

    <div class="chat-workspace">
      <p v-if="chatError" class="chat-error" role="alert">{{ chatError }}</p>

      <div ref="conversation" class="chat-conversation">
        <MessageList :messages="messages" :history-loading="historyLoading">
          <template #suggestions>
            <button
              v-for="suggestion in suggestions"
              :key="suggestion"
              type="button"
              class="suggestion-button"
              @click="useSuggestion(suggestion)"
            >
              {{ suggestion }}
              <ArrowRight aria-hidden="true" />
            </button>
          </template>
        </MessageList>
      </div>

      <QuestionInput
        :model-value="question"
        :disabled="historyLoading"
        :streaming="streaming"
        :answer-style="sessionStore.answerStyle"
        @update:model-value="setQuestion"
        @update:answer-style="sessionStore.answerStyle = $event"
        @submit="sendQuestion"
        @stop="stopGeneration"
      />
    </div>
  </section>
</template>
