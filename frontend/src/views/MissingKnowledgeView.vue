<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton, ElInput, ElOption, ElSelect } from 'element-plus'
import { Filter, Search } from '@element-plus/icons-vue'

import {
  getMissingKnowledge,
  updateMissingKnowledge,
  type MissingKnowledgeItem,
  type MissingKnowledgeQuery,
  type MissingKnowledgeStatus,
  type MissingKnowledgeSort,
} from '@/api/missingKnowledge'
import { getErrorMessage } from '@/api/http'

interface Draft {
  status: MissingKnowledgeStatus
  note: string
}

const items = ref<MissingKnowledgeItem[]>([])
const drafts = ref<Record<number, Draft>>({})
const keywordInput = ref('')
const statusFilter = ref<MissingKnowledgeStatus | ''>('PENDING')
const sortFilter = ref<MissingKnowledgeSort>('count_desc')
const page = ref(1)
const size = ref(20)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const savingId = ref<number>()
const pageError = ref('')
const actionError = ref('')
let requestId = 0
const topicLabels: Record<string, string> = {
  wage_payment: '工资支付与欠薪',
  termination: '劳动关系解除与经济补偿',
  labor_contract: '劳动合同与劳动关系',
  social_insurance: '社会保险与住房公积金',
  working_time: '工作时间与休息休假',
  work_injury: '工伤认定与待遇',
  other: '其他劳动权益问题',
}

async function loadItems() {
  const currentRequest = ++requestId
  const query: MissingKnowledgeQuery = {
    page: page.value,
    size: size.value,
    status: statusFilter.value || undefined,
    keyword: keywordInput.value.trim() || undefined,
    sort: sortFilter.value,
  }
  loading.value = true
  pageError.value = ''
  try {
    const result = await getMissingKnowledge(query)
    if (currentRequest !== requestId) return
    items.value = result.items
    total.value = result.total
    pages.value = result.pages
    drafts.value = Object.fromEntries(
      result.items.map((item) => [item.id, { status: item.status, note: item.note ?? '' }]),
    )
  } catch (error) {
    if (currentRequest === requestId) pageError.value = getErrorMessage(error)
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void loadItems()
}

function changePage(nextPage: number) {
  page.value = nextPage
  void loadItems()
}

function changeSize(nextSize: number | string) {
  size.value = Number(nextSize)
  page.value = 1
  void loadItems()
}

async function save(item: MissingKnowledgeItem) {
  const draft = drafts.value[item.id]
  if (!draft) return
  savingId.value = item.id
  actionError.value = ''
  try {
    const updated = await updateMissingKnowledge(item.id, {
      status: draft.status,
      note: draft.note.trim() || null,
    })
    if (statusFilter.value && updated.status !== statusFilter.value) {
      await loadItems()
    } else {
      items.value = items.value.map((current) => current.id === updated.id ? updated : current)
      drafts.value[updated.id] = { status: updated.status, note: updated.note ?? '' }
    }
  } catch (error) {
    actionError.value = `更新失败：${getErrorMessage(error)}`
  } finally {
    savingId.value = undefined
  }
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function topicLabel(topicKey: string) {
  return topicLabels[topicKey] ?? topicKey
}

onMounted(() => void loadItems())
</script>

<template>
  <section class="missing-knowledge-page" aria-labelledby="missing-knowledge-title">
    <div class="page-intro documents-page-intro">
      <div>
        <h1 id="missing-knowledge-title">知识缺口</h1>
        <p>查看因缺少可靠依据而拒答的高频问题，并维护处理状态与备注。</p>
      </div>
      <div class="missing-knowledge-total" aria-label="知识缺口主题数量">
        <strong>{{ total }}</strong>
        <span>个主题</span>
      </div>
    </div>

    <p v-if="pageError" class="missing-knowledge-error" role="alert">{{ pageError }}</p>
    <p v-if="actionError" class="missing-knowledge-error" role="alert">{{ actionError }}</p>

    <section class="missing-knowledge-panel" aria-label="知识缺口列表">
      <form class="missing-knowledge-filters" @submit.prevent="applyFilters">
        <label class="missing-filter-control missing-filter-search">
          <span class="sr-only">关键词</span>
          <ElInput
            v-model="keywordInput"
            class="missing-filter-input"
            type="search"
            aria-label="搜索问题或缺失方向"
            placeholder="搜索问题或缺失方向"
          >
            <template #prefix><Search aria-hidden="true" /></template>
          </ElInput>
        </label>
        <label class="missing-filter-control">
          <span class="sr-only">状态</span>
          <ElSelect v-model="statusFilter" class="missing-filter-select" aria-label="按状态筛选" placeholder="全部状态" clearable>
            <ElOption label="待补充" value="PENDING" />
            <ElOption label="已补充" value="RESOLVED" />
            <ElOption label="忽略" value="IGNORED" />
          </ElSelect>
        </label>
        <label class="missing-filter-control">
          <span class="sr-only">排序</span>
          <ElSelect v-model="sortFilter" class="missing-filter-select" aria-label="按拒答次数排序">
            <ElOption label="拒答次数" value="count_desc" />
            <ElOption label="最近出现" value="last_seen_desc" />
          </ElSelect>
        </label>
        <ElButton type="primary" native-type="submit" class="missing-knowledge-primary missing-filter-submit">
          <Filter aria-hidden="true" />
          <span>筛选</span>
        </ElButton>
      </form>

      <div class="missing-knowledge-table-wrap" :aria-busy="loading">
        <table class="missing-knowledge-table">
          <thead>
            <tr>
              <th scope="col">主题</th>
              <th scope="col">典型问题</th>
              <th scope="col">次数</th>
              <th scope="col">缺失资料方向</th>
              <th scope="col">首次 / 最近出现</th>
              <th scope="col">状态与备注</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>{{ topicLabel(item.topic_key) }}</td>
              <td class="question-cell">{{ item.sample_question }}</td>
              <td class="missing-knowledge-row-count">{{ item.count }} 次</td>
              <td>{{ item.missing_area }}</td>
              <td class="date-cell">
                <span>{{ formatDate(item.first_seen_at) }} <b>/</b></span>
                <span>{{ formatDate(item.last_seen_at) }}</span>
              </td>
              <td class="edit-cell">
                <ElSelect
                  v-model="drafts[item.id].status"
                  class="missing-status-select"
                  :aria-label="`更新 ${topicLabel(item.topic_key)} 的状态`"
                >
                  <ElOption label="待补充" value="PENDING" />
                  <ElOption label="已补充" value="RESOLVED" />
                  <ElOption label="忽略" value="IGNORED" />
                </ElSelect>
                <ElInput
                  v-model="drafts[item.id].note"
                  class="missing-note-input"
                  type="textarea"
                  :aria-label="`更新 ${topicLabel(item.topic_key)} 的备注`"
                  :rows="1"
                  placeholder="添加处理备注"
                />
              </td>
              <td>
                <ElButton
                  type="primary"
                  class="missing-knowledge-primary"
                  :loading="savingId === item.id"
                  :disabled="savingId === item.id"
                  @click="save(item)"
                >{{ savingId === item.id ? '保存中…' : '保存' }}</ElButton>
              </td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="7" class="empty-copy">暂无符合条件的知识缺口</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="missing-knowledge-pagination">
        <span>共 {{ total }} 条，第 {{ page }} / {{ pages || 1 }} 页</span>
        <label>
          每页
          <ElSelect
            :model-value="size"
            class="missing-page-size"
            aria-label="每页条数"
            @update:model-value="changeSize"
          >
            <ElOption :value="10" label="10" />
            <ElOption :value="20" label="20" />
            <ElOption :value="50" label="50" />
          </ElSelect>
        </label>
        <ElButton class="missing-page-previous" native-type="button" :disabled="page <= 1 || loading" @click="changePage(page - 1)">上一页</ElButton>
        <ElButton class="missing-page-next" native-type="button" :disabled="page >= pages || loading" @click="changePage(page + 1)">下一页</ElButton>
      </div>
    </section>
  </section>
</template>
