<script setup lang="ts">
/**
 * 个人资料页：档案根信息、六类事实与资料修订的汇总入口。
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
import ProfileBasicsPanel from './components/ProfileBasicsPanel.vue'
import ProfileManualFacts from './components/ProfileManualFacts.vue'
import ProfileImportPanel from './components/ProfileImportPanel.vue'
import RevisionPanel from './components/RevisionPanel.vue'
import {
  languageDescriptor,
} from './descriptors'

const profile = ref<Profile | null>(null)
const notCreated = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const conflictMessage = ref<string | null>(null)
const loading = ref(false)

/** 导入弹窗实例；入口位于核心表单的标题右侧。 */
const importPanel = ref<InstanceType<typeof ProfileImportPanel> | null>(null)

/** 打开文件选择或尚未保存的候选核对弹窗，不改变手动表单。 */
function startImport(): void {
  importPanel.value?.open()
}

/**
 * 可被新事实引用的证据候选。
 *
 * 证据记录由导入与"本人填写"流程自动创建，档案页不提供独立的证据管理面板：一块写着
 * "证据／可核验程度／已验证"的表格很容易被读成"系统已经核实了这些能力"，而事实上它只是
 * 来源记录。这里只把候选喂给需要它的字段，让来源在**单条事实**的上下文里可查看。
 */
const evidences = computed(() => profile.value?.evidences ?? [])

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

    <ProfileBasicsPanel
      v-if="notCreated || profile !== null"
      :profile="profile"
      @changed="reload"
      @conflict="onConflict"
    >
      <template #header-extra>
        <a-button data-testid="start-resume-import" @click="startImport">从已有简历导入</a-button>
      </template>
      <ProfileManualFacts :profile="profile" @changed="reload" @conflict="onConflict" />
    </ProfileBasicsPanel>

    <ProfileImportPanel
      v-if="notCreated || profile !== null"
      ref="importPanel"
      :has-profile="profile !== null"
      :show-entry="false"
      @changed="reload"
    />

    <template v-if="profile !== null">
      <a-collapse class="advanced-profile">
        <a-collapse-panel key="advanced" header="其他资料与历史记录">
      <FactPanel :descriptor="languagesDescriptor" :items="profile.languages" @changed="reload" @conflict="onConflict" />

      <RevisionPanel />
        </a-collapse-panel>
      </a-collapse>
    </template>
  </section>
</template>

<style scoped>
.conflict-banner {
  max-width: 60rem;
  margin-bottom: 1rem;
}

</style>
