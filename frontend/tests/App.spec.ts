import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'

import * as sessionsApi from '@/api/sessions'
import App from '@/App.vue'

vi.mock('@/api/sessions', () => ({
  createSession: vi.fn(),
  listSessions: vi.fn(),
  getSessionMessages: vi.fn(),
}))

const session = {
  id: '7ad8c9e1-62b2-4d40-9c6f-c48657f901d0',
  title: '公司拖欠工资怎么处理',
  created_at: '2026-09-15T00:00:00Z',
  updated_at: '2026-09-15T00:00:00Z',
}

const secondSession = {
  ...session,
  id: '88f4d026-b4d1-4128-8213-87663049e775',
  title: '未签劳动合同怎么办',
}

const page = { template: '<div />' }

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: page },
      { path: '/system', name: 'system', component: page },
      { path: '/documents', name: 'documents', component: page },
      { path: '/missing-knowledge', name: 'missing-knowledge', component: page },
      { path: '/evaluations', name: 'evaluations', component: page },
      { path: '/retrieval-experiments', name: 'retrieval-experiments', component: page },
    ],
  })
}

async function mountApp(path = '/system') {
  const router = createTestRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(sessionsApi.listSessions).mockResolvedValue([session, secondSession])
})

describe('App session navigation', () => {
  it('uses the correct LaborQA product name', async () => {
    const { wrapper } = await mountApp()

    expect(wrapper.get('.brand-lockup').text()).toContain('LaborQA')
    wrapper.unmount()
  })

  it('loads recent sessions and selects the clicked conversation', async () => {
    const { wrapper, router } = await mountApp()

    const recentItems = wrapper.findAll('.recent-conversation')
    expect(recentItems).toHaveLength(2)
    expect(recentItems[1].text()).toContain(secondSession.title)

    await recentItems[1].trigger('click')
    await flushPromises()

    expect(localStorage.getItem('labor-rights-qa.session-id')).toBe(secondSession.id)
    expect(router.currentRoute.value.name).toBe('chat')
    wrapper.unmount()
  })

  it('does not clear the active session until recent sessions are refreshed', async () => {
    localStorage.setItem('labor-rights-qa.session-id', session.id)
    const { wrapper } = await mountApp()
    let release!: (value: typeof session[]) => void
    vi.mocked(sessionsApi.listSessions).mockImplementationOnce(
      () => new Promise((resolve) => { release = resolve }),
    )

    await wrapper.get('.recent-add').trigger('click')
    await Promise.resolve()
    expect(localStorage.getItem('labor-rights-qa.session-id')).toBe(session.id)

    release([session])
    await flushPromises()
    expect(localStorage.getItem('labor-rights-qa.session-id')).toBeNull()
    wrapper.unmount()
  })

  it('keeps the active session and reports a refresh failure', async () => {
    localStorage.setItem('labor-rights-qa.session-id', session.id)
    const { wrapper } = await mountApp()
    vi.mocked(sessionsApi.listSessions).mockRejectedValueOnce(new Error('保存失败'))

    await wrapper.get('.recent-add').trigger('click')
    await flushPromises()

    expect(localStorage.getItem('labor-rights-qa.session-id')).toBe(session.id)
    expect(wrapper.get('[role="alert"]').text()).toContain('保存失败')
    wrapper.unmount()
  })
})
