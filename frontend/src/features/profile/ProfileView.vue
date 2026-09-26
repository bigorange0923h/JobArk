<script setup lang="ts">
/**
 * 个人资料页：档案根信息、六类事实、求职偏好与资料修订的汇总入口。
 *
 * 状态模型刻意保持简单——页面只有四种状态：加载中、加载失败、尚未创建、可就绪展示。
 * "尚未创建"是其中一等状态：后端对未创建的档案返回 404，这不是错误，而是引导用户创建，
 * 因此不能与加载失败共用同一条展示路径，否则用户会看到"请求失败"而不知道下一步该做什么。
 *
 * 写入后的刷新策略是**整页重载聚合**而不是就地合并返回值：一次 `GET /profile` 就能保证界面
 * 与后端完全一致，而就地合并需要在每个面板里各写一遍合并逻辑，且很难保证跨字段约束
 * （例如"标为已验证必须挂证据"）在合并后仍然自洽。数据量是单人级别，多一次往返不值得为此冒险。
 */

import { computed, nextTick, onMounted, ref } from 'vue'

import { fetchProfile, type Profile } from '@/shared/api/profile'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import FactPanel from './components/FactPanel.vue'
import PreferencePanel from './components/PreferencePanel.vue'
import ProfileBasicsPanel from './components/ProfileBasicsPanel.vue'
import ProfileImportPanel from './components/ProfileImportPanel.vue'
import RevisionPanel from './components/RevisionPanel.vue'
import {
  educationDescriptor,
  evidenceDescriptor,
  experienceDescriptor,
  languageDescriptor,
  projectDescriptor,
  skillDescriptor,
} from './descriptors'

const profile = ref<Profile | null>(null)
const notCreated = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const conflictMessage = ref<string | null>(null)
const loading = ref(false)

/**
 * 尚未创建档案时的路径选择。
 *
 * 先选路径、再只显示对应表单：导入候选与手动创建表单同时堆叠会让用户不知道该填哪一个。
 * 两条路径都保持挂载（模板里用 `v-show`），这样"从导入返回手动创建"不会清空已选文件与内存候选。
 */
type StartMode = 'choose' | 'manual' | 'import'
const startMode = ref<StartMode>('choose')
/** 导入面板实例；用于在用户"选择从已有简历导入"后直接打开文件选择弹窗。 */
const importPanel = ref<InstanceType<typeof ProfileImportPanel> | null>(null)

/**
 * 进入导入路径并立即弹出文件选择弹窗。
 *
 * 先切状态再 `await nextTick()`：面板由 `v-show` 控制、切换后才挂载出实例，
 * 等一个 tick 再调用它的 `open()`，避免拿到 null 而表现为"点了没反应"。
 */
async function startImport(): Promise<void> {
  startMode.value = 'import'
  await nextTick()
  importPanel.value?.open()
}

/** 可被新事实引用的证据候选；描述符需要它来渲染"来源证据"下拉与证据标题列。 */
const evidences = computed(() => profile.value?.evidences ?? [])

const evidencesDescriptor = computed(() => evidenceDescriptor())
const skillsDescriptor = computed(() => skillDescriptor(evidences.value))
const experiencesDescriptor = computed(() => experienceDescriptor(evidences.value))
const projectsDescriptor = computed(() => projectDescriptor(evidences.value))
const educationsDescriptor = computed(() => educationDescriptor(evidences.value))
const languagesDescriptor = computed(() => languageDescriptor(evidences.value))

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

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    profile.value = await fetchProfile()
    notCreated.value = false
  } catch (error: unknown) {
    const parsed = parseServerError(error)
    if (parsed.code === 'RESOURCE_NOT_FOUND') {
      // 档案尚未创建：进入创建引导，而不是错误页。
      profile.value = null
      notCreated.value = true
    } else {
      loadError.value = parsed
    }
  } finally {
    loading.value = false
  }
}

/** 任一面板写入成功后调用：重新加载聚合，使所有面板看到同一份最新数据。 */
function reload(): void {
  void load()
}

/**
 * 处理"需要刷新才能继续"的冲突。
 *
 * 典型来源是乐观锁版本过期：用户在别处（另一个标签页、或刚刚的另一次编辑）改过同一条记录，
 * 就地重试一定失败，因此必须刷新后由用户重新编辑。提示信息用后端文案，不改写成"请刷新页面"
 * 这类含糊说法，因为后端已经说明了具体原因。
 */
function onConflict(message: string): void {
  conflictMessage.value = message
  void load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="profile-view">
    <header class="page-header">
      <div><p class="page-eyebrow">PROFILE</p><h1>个人资料</h1><p class="page-subtitle">维护可追溯的职业事实，供简历和匹配使用。</p></div>
      <a-button size="small" :loading="loading" data-testid="reload" @click="load">刷新</a-button>
    </header>

    <a-alert
      v-if="conflictMessage"
      type="warning"
      show-icon
      closable
      class="conflict-banner"
      message="记录已被其他操作更新，已重新加载最新数据"
      :description="`${conflictMessage} 请基于最新数据重新提交。`"
      data-testid="conflict-banner"
      @close="conflictMessage = null"
    />

    <a-spin v-if="loading && profile === null && !notCreated" data-testid="loading" />

    <a-alert
      v-else-if="loadError"
      type="error"
      show-icon
      :message="loadError.message"
      :description="loadErrorDescription"
      data-testid="load-error"
    />

    <template v-if="notCreated">
      <!--
        入口常驻、动态区在它下方展开：不整块替换视图，用户不会感觉"进到了另一个页面"。
        两个入口按钮互斥高亮，动态区只显示当前选择的那条路径，避免两个表单同时堆叠。
      -->
      <a-card data-testid="profile-start-choices">
        <template #title>尚未创建个人档案</template>
        <p class="card-hint">
          可以先从已有简历导入候选，也可以直接手动填写。导入不会自动写入档案：候选需你逐项核对并确认后才落库。
          创建后即可单独维护工作经历和教育经历。
        </p>
        <a-space wrap class="start-actions">
          <a-button
            :type="startMode === 'manual' ? 'primary' : 'default'"
            data-testid="start-manual-create"
            @click="startMode = 'manual'"
          >
            手动创建个人档案
          </a-button>
          <a-button
            :type="startMode === 'import' ? 'primary' : 'default'"
            data-testid="start-resume-import"
            @click="startImport"
          >
            从已有简历导入
          </a-button>
        </a-space>
      </a-card>

      <!--
        `v-show` 而不是 `v-if`：切换路径时不卸载组件，已选文件与内存候选不会丢
        （见 docs/requirements/v1.md 2.1）；互斥显示避免两个表单同时堆叠。
      -->
      <ProfileBasicsPanel
        v-show="startMode === 'manual'"
        :profile="null"
        @changed="reload"
        @conflict="onConflict"
      />
      <ProfileImportPanel
        ref="importPanel"
        v-show="startMode === 'import'"
        :has-profile="false"
        :show-entry="false"
        @changed="reload"
        @back="startMode = 'manual'"
      />
    </template>

    <template v-else-if="profile !== null">
      <ProfileImportPanel :has-profile="true" @changed="reload" />
      <ProfileBasicsPanel :profile="profile" @changed="reload" @conflict="onConflict" />
      <PreferencePanel :preference="profile.preference" @changed="reload" @conflict="onConflict" />

      <FactPanel
        :descriptor="evidencesDescriptor"
        :items="profile.evidences"
        @changed="reload"
        @conflict="onConflict"
      />
      <FactPanel :descriptor="skillsDescriptor" :items="profile.skills" @changed="reload" @conflict="onConflict" />
      <FactPanel
        :descriptor="experiencesDescriptor"
        :items="profile.experiences"
        @changed="reload"
        @conflict="onConflict"
      />
      <FactPanel
        :descriptor="educationsDescriptor"
        :items="profile.educations"
        @changed="reload"
        @conflict="onConflict"
      />
      <FactPanel :descriptor="projectsDescriptor" :items="profile.projects" @changed="reload" @conflict="onConflict" />
      <FactPanel :descriptor="languagesDescriptor" :items="profile.languages" @changed="reload" @conflict="onConflict" />

      <RevisionPanel />
    </template>
  </section>
</template>

<style scoped>
.conflict-banner {
  max-width: 60rem;
  margin-bottom: 1rem;
}

.start-actions { margin-top: 12px; }
</style>
