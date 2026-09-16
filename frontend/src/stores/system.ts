import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getErrorMessage, getHealth, type HealthData } from '@/api/http'

export const useSystemStore = defineStore('system', () => {
  const health = ref<HealthData | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function refreshHealth() {
    loading.value = true
    error.value = ''
    try {
      health.value = await getHealth()
    } catch (cause) {
      error.value = getErrorMessage(cause)
      health.value = null
    } finally {
      loading.value = false
    }
  }

  return { health, loading, error, refreshHealth }
})
