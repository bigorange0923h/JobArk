<script setup lang="ts">
/**
 * 简历详情页：一份简历方向的版本与候选稿。
 *
 * 两条与后端契约直接相关的界面规则：
 *
 * - **确认候选稿必须显式选择资料修订**。后端要求提交 `profile_revision_id`，界面不用"最新修订"
 *   悄悄兜底：资料可能在候选稿生成之后被改过，静默沿用会让新版本指向不准确的输入，
 *   而"这个版本依据的是什么"正是修订存在的意义。
 * - **档案未创建时不提供"新建候选稿"**。候选稿起初稿的内容来自档案事实，没有档案就没有可填的
 *   内容；此时给出引导，而不是让用户点一个必然失败的按钮。
 *
 * 版本一经创建不可修改，因此版本列表只提供查看与预览；所有编辑都发生在候选稿上，
 * 确认之后才产生新版本。
 */

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchProfile, listRevisions, type Profile, type Revision } from '@/shared/api/profile'
import {
  confirmDraft,
  createDraft,
  discardDraft,
  fetchResume,
  listDrafts,
  listVersions,
  type DraftStatus,
  type Resume,
  type ResumeDraft,
  type ResumeVersion,
} from '@/shared/api/resume'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import { createDocumentFromProfile } from './document'

const props = defineProps<{ resumeId: string }>()

const router = useRouter()

const resume = ref<Resume | null>(null)
const versions = ref<ResumeVersion[]>([])
const drafts = ref<ResumeDraft[]>([])
const revisions = ref<Revision[]>([])
const profile = ref<Profile | null>(null)
const profileMissing = ref(false)
const selectedRevisionId = ref<string | null>(null)
const loading = ref(false)
const busy = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const actionError = ref<ParsedServerError | null>(null)
/** 本地规则产生的提示（例如"还没选资料修订"）；与后端错误共用一个提示区，但来源不同。 */
const localNotice = ref<string | null>(null)

const DRAFT_STATUS_LABEL: Record<DraftStatus, string> = {
  DRAFT: '待确认',
  CONFIRMED: '已确认',
  DISCARDED: '已丢弃',
  FAILED: '生成失败',
}

const versionColumns = [
  { key: 'version_no', title: '版本', dataIndex: 'version_no' },
  { key: 'created_reason', title: '创建原因', dataIndex: 'created_reason' },
  { key: 'created_at', title: '创建时间', dataIndex: 'created_at' },
  { key: 'actions', title: '操作' },
]

const draftColumns = [
  { key: 'status', title: '状态', dataIndex: 'status' },
  { key: 'generator_name', title: '来源', dataIndex: 'generator_name' },
  { key: 'updated_at', title: '最后修改', dataIndex: 'updated_at' },
  { key: 'actions', title: '操作' },
]

/** 候选稿是否仍可编辑、确认或丢弃；已处理的候选稿是一次历史决定。 */
function isPending(draft: ResumeDraft): boolean {
  return draft.status === 'DRAFT'
}

const revisionOptions = computed(() =>
  revisions.value.map((revision) => ({
    value: revision.id,
    label: `修订 ${revision.revision_no}：${revision.reason}`,
  })),
)

const actionMessage = computed(() => actionError.value?.message ?? localNotice.value)

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

/** 拉取简历、版本与候选稿；任一处失败都按页面级错误处理。 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    resume.value = await fetchResume(props.resumeId)
    versions.value = await listVersions(props.resumeId)
    drafts.value = await listDrafts(props.resumeId)
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
    loading.value = false
    return
  }

  await loadProfileContext()
  loading.value = false
}

/**
 * 读取"新建候选稿"与"确认"所需的档案上下文。
 *
 * 注意:
 *     档案未创建时后端返回 404。这不是加载失败，而是引导用户先建档案，
 *     因此单独处理为 `profileMissing`，不与页面级错误共用展示路径。
 */
async function loadProfileContext(): Promise<void> {
  try {
    profile.value = await fetchProfile()
    profileMissing.value = false
    revisions.value = await listRevisions()
  } catch (error: unknown) {
    const parsed = parseServerError(error)
    if (parsed.code === 'RESOURCE_NOT_FOUND') {
      profile.value = null
      profileMissing.value = true
      revisions.value = []
      return
    }
    loadError.value = parsed
  }
}

/** 用当前档案事实生成初稿，然后进入编辑器。 */
async function createDraftFromProfile(): Promise<void> {
  if (profile.value === null) {
    return
  }

  busy.value = true
  actionError.value = null
  localNotice.value = null
  try {
    const draft = await createDraft(props.resumeId, { document: createDocumentFromProfile(profile.value) })
    await router.push({
      name: 'resume-draft-edit',
      params: { resumeId: props.resumeId, draftId: draft.id },
    })
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    busy.value = false
  }
}

/** 确认候选稿并生成新版本。 */
async function confirm(draft: ResumeDraft): Promise<void> {
  if (selectedRevisionId.value === null) {
    localNotice.value = '请先选择该候选稿依据的资料修订。'
    return
  }

  busy.value = true
  actionError.value = null
  localNotice.value = null
  try {
    await confirmDraft(props.resumeId, draft.id, {
      version: draft.version,
      profile_revision_id: selectedRevisionId.value,
    })
    selectedRevisionId.value = null
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    busy.value = false
  }
}

/** 丢弃候选稿；不产生版本。 */
async function discard(draft: ResumeDraft): Promise<void> {
  busy.value = true
  actionError.value = null
  localNotice.value = null
  try {
    await discardDraft(props.resumeId, draft.id, draft.version)
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    busy.value = false
  }
}

/** 进入候选稿编辑器。 */
function editDraft(draft: ResumeDraft): void {
  void router.push({
    name: 'resume-draft-edit',
    params: { resumeId: props.resumeId, draftId: draft.id },
  })
}

/** 预览候选稿内容。 */
function previewDraft(draft: ResumeDraft): void {
  void router.push({ name: 'resume-preview', params: { resumeId: props.resumeId }, query: { draft: draft.id } })
}

/** 预览某个已确认版本的内容。 */
function previewVersion(version: ResumeVersion): void {
  void router.push({ name: 'resume-preview', params: { resumeId: props.resumeId }, query: { version: version.id } })
}

/** 关闭操作提示；两类来源（后端错误与本地规则提示）都要清掉，否则会留下过期提示。 */
function clearActionMessage(): void {
  actionError.value = null
  localNotice.value = null
}

/** 给表格行加测试标识，使断言能定位到具体记录而不是整张表。 */
function versionRowProps(record: ResumeVersion): Record<string, string> {
  return { 'data-testid': `version-row-${record.id}` }
}

/** 同上，用于候选稿表格。 */
function draftRowProps(record: ResumeDraft): Record<string, string> {
  return { 'data-testid': `draft-row-${record.id}` }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="resume-detail-view">
    <header class="page-header">
      <div>
        <h1>{{ resume?.name ?? '简历' }}</h1>
        <p v-if="resume?.target_direction" class="target-direction">目标方向：{{ resume.target_direction }}</p>
      </div>
      <a-space>
        <a-button size="small" :loading="loading" data-testid="reload" @click="load">刷新</a-button>
        <a-button
          type="primary"
          :disabled="profileMissing"
          :loading="busy"
          data-testid="create-draft"
          @click="createDraftFromProfile"
        >
          新建候选稿
        </a-button>
      </a-space>
    </header>

    <a-alert
      v-if="profileMissing"
      type="info"
      show-icon
      class="hint"
      message="还没有个人档案"
      description="候选稿的初稿来自档案事实，请先在「个人资料」页创建档案。"
      data-testid="profile-missing-hint"
    />

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      class="hint"
      :message="loadError.message"
      :description="loadErrorDescription"
      data-testid="load-error"
    />

    <a-alert
      v-if="actionMessage"
      type="warning"
      show-icon
      closable
      class="hint"
      :message="actionMessage"
      data-testid="action-error"
      @close="clearActionMessage"
    />

    <a-card size="small" title="版本">
      <template #extra>
        <span class="card-hint">版本不可修改：投递记录会引用它们</span>
      </template>
      <a-table
        :data-source="versions"
        :columns="versionColumns"
        :custom-row="versionRowProps"
        row-key="id"
        size="small"
        :pagination="false"
        data-testid="version-table"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'version_no'">v{{ (record as ResumeVersion).version_no }}</template>
          <template v-else-if="column.key === 'actions'">
            <a-button
              type="link"
              size="small"
              :data-testid="`preview-version-${(record as ResumeVersion).id}`"
              @click="previewVersion(record as ResumeVersion)"
            >
              预览
            </a-button>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-card size="small" title="候选稿">
      <template #extra>
        <a-space>
          <span class="card-hint">确认时依据的资料修订</span>
          <a-select
            v-model:value="selectedRevisionId"
            :options="revisionOptions"
            :placeholder="profileMissing ? '请先创建档案' : '选择资料修订'"
            :disabled="profileMissing || revisionOptions.length === 0"
            style="min-width: 14rem"
            data-testid="revision-select"
          />
        </a-space>
      </template>

      <a-table
        :data-source="drafts"
        :columns="draftColumns"
        :custom-row="draftRowProps"
        row-key="id"
        size="small"
        :pagination="false"
        data-testid="draft-table"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">{{ DRAFT_STATUS_LABEL[(record as ResumeDraft).status] }}</template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button
                type="link"
                size="small"
                :disabled="!isPending(record as ResumeDraft)"
                :data-testid="`edit-draft-${(record as ResumeDraft).id}`"
                @click="editDraft(record as ResumeDraft)"
              >
                编辑
              </a-button>
              <a-button
                type="link"
                size="small"
                :disabled="!isPending(record as ResumeDraft)"
                :data-testid="`preview-draft-${(record as ResumeDraft).id}`"
                @click="previewDraft(record as ResumeDraft)"
              >
                预览
              </a-button>
              <a-button
                type="link"
                size="small"
                :disabled="!isPending(record as ResumeDraft)"
                :loading="busy"
                :data-testid="`confirm-draft-${(record as ResumeDraft).id}`"
                @click="confirm(record as ResumeDraft)"
              >
                确认
              </a-button>
              <a-button
                type="link"
                size="small"
                danger
                :disabled="!isPending(record as ResumeDraft)"
                :data-testid="`discard-draft-${(record as ResumeDraft).id}`"
                @click="discard(record as ResumeDraft)"
              >
                丢弃
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  max-width: 60rem;
}

.page-header h1 {
  font-size: 1.25rem;
  margin: 0 0 0.25rem;
}

.target-direction,
.card-hint {
  color: #6b7280;
  font-size: 0.85rem;
  margin: 0;
}

.hint {
  max-width: 60rem;
  margin: 1rem 0;
}
</style>
