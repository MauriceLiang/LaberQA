<script setup lang="ts">
import { ref } from 'vue'
import { ElButton } from 'element-plus'
import { Document, FolderOpened } from '@element-plus/icons-vue'

import { uploadDocument, type DocumentUploadAccepted } from '@/api/documents'
import { getErrorMessage } from '@/api/http'

const acceptedExtensions = ['pdf', 'doc', 'docx', 'txt']
const maxFileSize = 20 * 1024 * 1024

const selectedFile = ref<File>()
const uploading = ref(false)
const errorMessage = ref('')
const fileInput = ref<HTMLInputElement>()
const emit = defineEmits<{ uploaded: [document: DocumentUploadAccepted] }>()

function chooseFile() {
  fileInput.value?.click()
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  errorMessage.value = ''
  selectedFile.value = undefined

  if (!file) return
  if (file.size === 0) {
    errorMessage.value = '文件内容为空，请选择其他文件。'
    return
  }
  if (file.size > maxFileSize) {
    errorMessage.value = '文件不能超过 20 MB。'
    return
  }
  const extension = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() : undefined
  if (!extension || !acceptedExtensions.includes(extension)) {
    errorMessage.value = '仅支持 PDF、DOC、DOCX 或 TXT 文件。'
    return
  }
  selectedFile.value = file
}

async function submitUpload() {
  if (!selectedFile.value || uploading.value) return
  uploading.value = true
  errorMessage.value = ''
  try {
    const uploaded = await uploadDocument(selectedFile.value)
    selectedFile.value = undefined
    emit('uploaded', uploaded)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <section class="document-upload" aria-labelledby="upload-title">
    <div class="document-upload-copy">
      <h2 id="upload-title">导入资料</h2>
      <p>支持 PDF、DOC、DOCX、TXT，单个文件不超过 20 MB。</p>
    </div>
    <div class="upload-controls">
      <input
        ref="fileInput"
        class="file-input"
        type="file"
        accept=".pdf,.doc,.docx,.txt"
        aria-label="选择要导入的资料"
        :disabled="uploading"
        @change="onFileChange"
      />
      <button class="file-picker-button" type="button" :disabled="uploading" @click="chooseFile">
        <FolderOpened aria-hidden="true" />
        <span>选择文件</span>
      </button>
      <ElButton class="upload-submit-button" type="primary" :disabled="!selectedFile" :loading="uploading" @click="submitUpload">
        <Document aria-hidden="true" />
        上传资料
      </ElButton>
    </div>
    <p v-if="selectedFile" class="upload-file-name">已选择：{{ selectedFile.name }}</p>
    <p v-if="errorMessage" class="inline-error" role="alert">{{ errorMessage }}</p>
  </section>
</template>
