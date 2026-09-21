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

import { computed, onMounted, ref } from 'vue'

import { fetchProfile, type Profile } from '@/shared/api/profile'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import FactPanel from './components/FactPanel.vue'
import PreferencePanel from './components/PreferencePanel.vue'
import ProfileBasicsPanel from './components/ProfileBasicsPanel.vue'
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
      <h1>个人资料</h1>
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

    <ProfileBasicsPanel
      v-if="notCreated || profile !== null"
      :profile="profile"
      @changed="reload"
      @conflict="onConflict"
    />

    <template v-if="profile !== null">
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
      <FactPanel :descriptor="projectsDescriptor" :items="profile.projects" @changed="reload" @conflict="onConflict" />
      <FactPanel
        :descriptor="educationsDescriptor"
        :items="profile.educations"
        @changed="reload"
        @conflict="onConflict"
      />
      <FactPanel :descriptor="languagesDescriptor" :items="profile.languages" @changed="reload" @conflict="onConflict" />

      <RevisionPanel />
    </template>
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

.conflict-banner {
  max-width: 60rem;
  margin-bottom: 1rem;
}
</style>
