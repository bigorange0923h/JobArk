<script setup lang="ts">
/**
 * 简历预览页：把候选稿或某个已确认版本渲染成 A4 纸张。
 *
 * 导出方式刻意采用**浏览器打印**而不是服务端生成 PDF：预览与打印共用同一份 DOM 与同一套样式，
 * 因此"屏幕上看到的"与"另存为 PDF 的"不会出现两套排版；服务端导出要额外承担字体包、浏览器版本、
 * 容器运行时与可重复分页的测试成本，当前需求尚未证明值得。
 *
 * 来源由地址参数决定（`?draft=` 或 `?version=`），两者互斥：同时接受两种来源会引出
 * "两个都给了到底渲染哪个"的不确定，而这种不确定只能在出问题时才被发现。
 */

import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { fetchDraft, fetchVersion, type ResumeDocument } from '@/shared/api/resume'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import ResumePreview from './components/ResumePreview.vue'

const props = defineProps<{ resumeId: string }>()

const route = useRoute()

const previewDocument = ref<ResumeDocument | null>(null)
const sourceLabel = ref('')
const loading = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const missingSource = ref(false)

const canPrint = computed(() => previewDocument.value !== null)

/** 读取地址参数；空串按未提供处理。 */
function readQuery(key: string): string | null {
  const value = route.query[key]
  return typeof value === 'string' && value !== '' ? value : null
}

/** 按地址参数载入预览来源。 */
async function load(): Promise<void> {
  loadError.value = null
  previewDocument.value = null
  missingSource.value = false

  const draftId = readQuery('draft')
  const versionId = readQuery('version')
  if (draftId === null && versionId === null) {
    missingSource.value = true
    return
  }

  loading.value = true
  try {
    if (draftId !== null) {
      const draft = await fetchDraft(props.resumeId, draftId)
      previewDocument.value = draft.document_json
      sourceLabel.value = `来源：候选稿（草稿版本 ${draft.version}）`
    } else if (versionId !== null) {
      const version = await fetchVersion(versionId)
      previewDocument.value = version.document_json
      sourceLabel.value = `来源：已确认版本 v${version.version_no}`
    }
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  } finally {
    loading.value = false
  }
}

/**
 * 打印或另存为 PDF。
 *
 * 说明:
 *     调用浏览器自身的打印，页面样式由全局打印样式表处理（隐藏应用外壳、按 A4 分页）；
 *     正式导出的分页由用户在打印对话框中确认，因此这里不额外做"导出前检查"。
 */
function print(): void {
  window.print()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="resume-preview-view">
    <!-- 工具条在打印时由全局打印样式表隐藏：纸上不该出现"打印"按钮。 -->
    <header class="page-header no-print">
      <div>
        <h1>简历预览</h1>
        <p v-if="sourceLabel" class="subtitle" data-testid="source-label">{{ sourceLabel }}</p>
      </div>
      <a-space>
        <a-button size="small" :loading="loading" data-testid="reload" @click="load">重新加载</a-button>
        <a-button type="primary" size="small" :disabled="!canPrint" data-testid="print" @click="print">
          打印 / 另存为 PDF
        </a-button>
      </a-space>
    </header>

    <a-alert
      v-if="missingSource"
      type="info"
      show-icon
      class="hint no-print"
      message="缺少预览来源"
      description="请从候选稿或版本列表点击「预览」进入本页，地址中需要带有 draft 或 version 参数。"
      data-testid="missing-source"
    />

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      class="hint no-print"
      :message="loadError.message"
      data-testid="load-error"
    />

    <a-spin v-if="loading && previewDocument === null" data-testid="loading" />

    <ResumePreview v-if="previewDocument" :document="previewDocument" />
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  max-width: 210mm;
  margin: 0 auto 1rem;
}

.page-header h1 {
  font-size: 1.25rem;
  margin: 0 0 0.25rem;
}

.subtitle {
  color: #6b7280;
  font-size: 0.85rem;
  margin: 0;
}

.hint {
  max-width: 210mm;
  margin: 0 auto 1rem;
}
</style>
