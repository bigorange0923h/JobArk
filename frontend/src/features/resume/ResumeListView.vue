<script setup lang="ts">
/**
 * 简历方向列表页。
 *
 * 方向是可持续维护的表达单位，不是某次投递的附件：投递记录引用的是**具体版本**，
 * 因此这里的删除是归档而不是物理删除，历史版本以及引用它们的记录都不受影响。
 *
 * 状态模型与个人资料页一致（加载中、加载失败、正常展示），并额外区分两类失败：
 * 加载失败展示在页面级提示里，写入失败（重名、校验不通过）展示在操作提示里——
 * 后者不该把整张列表替换成错误页，用户需要看着列表决定改什么名字。
 *
 * 列表为空是**正常**状态而不是错误：空态由表格自身呈现，不需要额外的分支。
 */

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { archiveResume, createResume, listResumes, type Resume, type ResumeStatus } from '@/shared/api/resume'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

const router = useRouter()

const resumes = ref<Resume[]>([])
const includeArchived = ref(false)
const loading = ref(false)
const submitting = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const actionError = ref<ParsedServerError | null>(null)
const name = ref('')
const targetDirection = ref('')

/** 状态的展示文案；归档不是删除，文案要如实反映"仍可查看"。 */
const STATUS_LABEL: Record<ResumeStatus, string> = {
  ACTIVE: '使用中',
  ARCHIVED: '已归档',
}

const columns = [
  { key: 'name', title: '名称', dataIndex: 'name' },
  { key: 'target_direction', title: '目标方向', dataIndex: 'target_direction' },
  { key: 'status', title: '状态', dataIndex: 'status' },
  { key: 'actions', title: '操作' },
]

const loadErrorDescription = computed(() => {
  if (loadError.value === null) {
    return undefined
  }
  const parts = [...loadError.value.general]
  if (loadError.value.requestId !== null) {
    parts.push(`错误编号：${loadError.value.requestId}`)
  }
  return parts.length === 0 ? undefined : parts.join(' ')
})

/** 加载列表；写入成功后也走这里，使界面与后端完全一致。 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    resumes.value = await listResumes(includeArchived.value)
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  } finally {
    loading.value = false
  }
}

/** 创建简历方向；失败时保留用户已填内容，只提示原因。 */
async function submit(): Promise<void> {
  const trimmedName = name.value.trim()
  if (trimmedName === '') {
    return
  }

  submitting.value = true
  actionError.value = null
  try {
    const trimmedDirection = targetDirection.value.trim()
    await createResume({
      name: trimmedName,
      target_direction: trimmedDirection === '' ? null : trimmedDirection,
    })
    name.value = ''
    targetDirection.value = ''
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}

/**
 * 归档简历方向。
 *
 * 参数:
 *     resume: 目标简历方向。
 *
 * 注意:
 *     归档后重新拉取列表，而不是就地移除那一行：是否还出现在列表里由后端的过滤规则决定，
 *     前端自己删一行就会与"包含已归档"这个条件各说一套。
 */
async function archive(resume: Resume): Promise<void> {
  actionError.value = null
  try {
    await archiveResume(resume.id)
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  }
}

/** 打开某份简历的详情页。 */
function open(resume: Resume): void {
  void router.push({ name: 'resume-detail', params: { resumeId: resume.id } })
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="resume-list-view">
    <header class="page-header">
      <h1>简历</h1>
      <a-space>
        <label class="archived-toggle">
          <input v-model="includeArchived" type="checkbox" data-testid="include-archived" @change="load" />
          包含已归档
        </label>
        <a-button size="small" :loading="loading" data-testid="reload" @click="load">刷新</a-button>
      </a-space>
    </header>

    <a-alert
      v-if="actionError"
      type="error"
      show-icon
      closable
      class="action-error"
      :message="actionError.message"
      data-testid="form-error"
      @close="actionError = null"
    />

    <a-card size="small" title="新建简历方向">
      <a-form layout="inline" @submit.prevent="submit">
        <a-form-item label="名称">
          <a-input
            v-model:value="name"
            :maxlength="200"
            placeholder="例如：Java 后端"
            data-testid="resume-name"
          />
        </a-form-item>
        <a-form-item label="目标方向">
          <a-input
            v-model:value="targetDirection"
            :maxlength="200"
            placeholder="例如：平台工程"
            data-testid="resume-direction"
          />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" :loading="submitting" data-testid="create-resume" @click="submit">创建</a-button>
        </a-form-item>
      </a-form>
    </a-card>

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      class="load-error"
      :message="loadError.message"
      :description="loadErrorDescription"
      data-testid="load-error"
    />

    <a-spin v-if="loading && resumes.length === 0 && loadError === null" data-testid="loading" />

    <a-table
      v-else
      :data-source="resumes"
      :columns="columns"
      row-key="id"
      size="small"
      :pagination="false"
      data-testid="resume-table"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">{{ STATUS_LABEL[(record as Resume).status] }}</template>
        <template v-else-if="column.key === 'actions'">
          <a-space>
            <a-button
              type="link"
              size="small"
              :data-testid="`open-${(record as Resume).id}`"
              @click="open(record as Resume)"
            >
              打开
            </a-button>
            <a-popconfirm
              title="归档后不再出现在默认列表，历史版本仍可查看。"
              ok-text="归档"
              cancel-text="取消"
              @confirm="archive(record as Resume)"
            >
              <a-button
                type="link"
                size="small"
                danger
                :disabled="(record as Resume).status === 'ARCHIVED'"
                :data-testid="`archive-${(record as Resume).id}`"
              >
                归档
              </a-button>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 60rem;
}

.page-header h1 {
  font-size: 1.25rem;
  margin: 0 0 1rem;
}

.archived-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: #4b5563;
}

.action-error,
.load-error {
  max-width: 60rem;
  margin-top: 1rem;
}
</style>
