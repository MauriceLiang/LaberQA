<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElButton } from 'element-plus'
import { Document, FolderOpened } from '@element-plus/icons-vue'

import { getDocument, uploadDocument, type DocumentItem, type DocumentUploadAccepted } from '@/api/documents'
import { getErrorMessage } from '@/api/http'

const acceptedExtensions = ['pdf', 'doc', 'docx', 'md', 'txt']
const maxFileSize = 20 * 1024 * 1024
const importPollIntervalMs = 2000

const selectedFiles = ref<File[]>([])
const uploading = ref(false)
const uploadIndex = ref(0)
const uploadTotal = ref(0)
const errorMessage = ref('')
const fileInput = ref<HTMLInputElement>()
const selectedFileNames = computed(() => selectedFiles.value.map((file) => file.name).join('、'))
const emit = defineEmits<{ uploaded: [document: DocumentUploadAccepted] }>()

function chooseFile() {
  fileInput.value?.click()
}

function validateFile(file: File): string {
  if (file.size === 0) return '文件内容为空，请选择其他文件。'
  if (file.size > maxFileSize) return '文件不能超过 20 MB。'
  const extension = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() : undefined
  if (!extension || !acceptedExtensions.includes(extension)) return '仅支持 PDF、DOC、DOCX、MD 或 TXT 文件。'
  return ''
}

async function waitForImport(documentId: number): Promise<DocumentItem> {
  let document = await getDocument(documentId)
  while (document.status === 'PROCESSING') {
    await new Promise((resolve) => setTimeout(resolve, importPollIntervalMs))
    document = await getDocument(documentId)
  }
  return document
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  errorMessage.value = ''
  selectedFiles.value = []

  for (const file of files) {
    const validationMessage = validateFile(file)
    if (validationMessage) {
      errorMessage.value = file.name + '：' + validationMessage
      return
    }
  }

  selectedFiles.value = files
}

async function submitUpload() {
  if (selectedFiles.value.length === 0 || uploading.value) return
  const files = selectedFiles.value
  uploading.value = true
  uploadIndex.value = 0
  uploadTotal.value = files.length
  errorMessage.value = ''

  const failedImports: string[] = []
  try {
    for (const [index, file] of files.entries()) {
      uploadIndex.value = index + 1
      const uploaded = await uploadDocument(file)
      emit('uploaded', uploaded)
      const completed = await waitForImport(uploaded.document_id)
      if (completed.status === 'FAILED') {
        failedImports.push(file.name + '：' + (completed.error_message || '资料处理失败'))
      }
    }
    selectedFiles.value = []
    if (failedImports.length > 0) {
      errorMessage.value = '以下文件处理失败：' + failedImports.join('；')
    }
  } catch (error) {
    const failedIndex = Math.max(uploadIndex.value - 1, 0)
    selectedFiles.value = files.slice(failedIndex)
    errorMessage.value = '第 ' + uploadIndex.value + ' 个文件“' + files[failedIndex].name + '”上传失败：' + getErrorMessage(error)
  } finally {
    uploading.value = false
    uploadIndex.value = 0
    uploadTotal.value = 0
  }
}
</script>

<template>
  <section class="document-upload" aria-labelledby="upload-title">
    <div class="document-upload-copy">
      <h2 id="upload-title">导入资料</h2>
      <p>支持一次选择多个 PDF、DOC、DOCX、MD、TXT 文件，系统按顺序逐个解析、切块并向量化；单个文件不超过 20 MB。</p>
    </div>
    <div class="upload-controls">
      <input
        ref="fileInput"
        class="file-input"
        type="file"
        accept=".pdf,.doc,.docx,.md,.txt"
        multiple
        aria-label="选择要导入的资料（可多选）"
        :disabled="uploading"
        @change="onFileChange"
      />
      <ElButton class="file-picker-button" :disabled="uploading" @click="chooseFile">
        <FolderOpened aria-hidden="true" />
        <span>选择文件（可多选）</span>
      </ElButton>
      <ElButton class="upload-submit-button" type="primary" :disabled="selectedFiles.length === 0 || uploading" :loading="uploading" @click="submitUpload">
        <Document aria-hidden="true" />
        上传资料
      </ElButton>
    </div>
    <p v-if="selectedFiles.length > 0" class="upload-file-name">已选择 {{ selectedFiles.length }} 个文件：{{ selectedFileNames }}</p>
    <p v-if="uploading" class="upload-progress" role="status">正在处理第 {{ uploadIndex }} / {{ uploadTotal }} 个文件…</p>
    <p v-if="errorMessage" class="inline-error" role="alert">{{ errorMessage }}</p>
  </section>
</template>
