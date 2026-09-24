<script setup lang="ts">
/**
 * 新增 AI 服务商页。
 *
 * 服务商与其模型在一次提交里创建：服务端在同一个事务内落库，任一模型冲突则整体回滚，
 * 因此不会留下"服务商建好了、模型没建成"的半成品，也不需要先去列表里再逐个补模型。
 *
 * 模型只让用户填一个「模型名称」（服务商文档里的模型 ID）；显示名称与模型 ID 的同值
 * 由 API 层统一补齐（见 `shared/api/ai.ts`），页面不复制这条约定。
 *
 * 凭据只在提交时作为明文交给后端一次；页面不保存、不回显，也不写日志。
 */

import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { createAiProvider } from '@/shared/api/ai'
import { isSafeBaseUrl } from '@/shared/forms/baseUrl'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

/** 表单里的一个模型行；`key` 只用于稳定渲染，不参与提交。 */
interface ModelRow {
  key: number
  name: string
  enabled: boolean
}

/** 模型行数上限，与服务端 `ProviderCreate.models` 的上限保持一致。 */
const MAX_MODELS = 20

const router = useRouter()

const providerName = ref('')
const providerBaseUrl = ref('')
const providerApiKey = ref('')
const providerDescription = ref('')
/** 默认给一行空行：多数情况下用户至少会配一个模型，但不强制填写。 */
const models = ref<ModelRow[]>([{ key: 0, name: '', enabled: true }])
const submitting = ref(false)
const actionError = ref<ParsedServerError | null>(null)

let nextRowKey = 1

const errorDescription = computed(() => {
  if (actionError.value === null) {
    return undefined
  }
  const parts = [...actionError.value.general]
  if (actionError.value.requestId !== null) {
    parts.push(`错误编号：${actionError.value.requestId}`)
  }
  return parts.length === 0 ? undefined : parts.join(' ')
})

/** 表单是否已有内容；用于在离开前提醒，避免误点取消丢掉刚填的东西。 */
const isDirty = computed(
  () =>
    providerName.value.trim() !== '' ||
    providerBaseUrl.value.trim() !== '' ||
    providerApiKey.value !== '' ||
    providerDescription.value.trim() !== '' ||
    models.value.some((row) => row.name.trim() !== ''),
)

/** 构造前端本地校验错误；字段级原因留空，整体提示即可定位。 */
function localError(message: string): ParsedServerError {
  return { code: 'VALIDATION_ERROR', message, fields: {}, general: [], requestId: null }
}

/** 找出表单内重复的模型名称；权威去重仍由服务端完成。 */
function firstDuplicateName(names: readonly string[]): string | null {
  const seen = new Set<string>()
  for (const name of names) {
    if (seen.has(name)) {
      return name
    }
    seen.add(name)
  }
  return null
}

/** 添加一个空的模型行；达到上限时按钮已禁用，这里再兜一次。 */
function addModel(): void {
  if (models.value.length >= MAX_MODELS) {
    return
  }
  models.value.push({ key: nextRowKey, name: '', enabled: true })
  nextRowKey += 1
}

/** 删除一行；只有一行时按钮被禁用，避免表单失去填写模型的入口。 */
function removeModel(index: number): void {
  models.value.splice(index, 1)
}

/** 返回列表页。 */
function goBack(): void {
  void router.push({ name: 'ai-models' })
}

/**
 * 提交表单：一次请求创建服务商与其全部模型。
 *
 * 注意:
 *     空模型行会被忽略而不是报错——"先只建服务商、之后再补模型"是合法用法。
 *     失败时保留全部输入并就地展示错误，用户改完即可重试，不需要重新填写。
 */
async function submit(): Promise<void> {
  if (submitting.value) {
    return
  }
  const name = providerName.value.trim()
  const baseUrl = providerBaseUrl.value.trim()
  if (name === '' || baseUrl === '') {
    actionError.value = localError('请填写服务商名称与接口地址。')
    return
  }
  if (!isSafeBaseUrl(baseUrl)) {
    actionError.value = localError('服务商地址必须使用 HTTPS 或本地回环 HTTP（localhost、127.0.0.1、::1）。')
    return
  }

  const filledModels = models.value
    .map((row) => ({ name: row.name.trim(), enabled: row.enabled }))
    .filter((row) => row.name !== '')
  const duplicated = firstDuplicateName(filledModels.map((row) => row.name))
  if (duplicated !== null) {
    actionError.value = localError(`模型名称「${duplicated}」重复，请修改后再保存。`)
    return
  }

  submitting.value = true
  actionError.value = null
  try {
    const description = providerDescription.value.trim()
    await createAiProvider({
      name,
      base_url: baseUrl,
      // 空输入不提交 api_key：服务端语义是"暂不配置凭据"，与"提交空的凭据"不是一件事。
      api_key: providerApiKey.value === '' ? null : providerApiKey.value,
      description: description === '' ? null : description,
      models: filledModels.map((row) => ({ name: row.name, is_enabled: row.enabled })),
    })
    // 成功后才离开页面：失败时停在原表单，用户不必重新输入。
    await router.push({ name: 'ai-models' })
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="ai-provider-create">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">AI</p>
        <h1>新增 AI 服务商</h1>
        <p class="page-subtitle">
          一次填写服务商信息与它的模型；服务端在同一事务里保存，任一模型冲突都会整体回滚。
        </p>
      </div>
    </header>

    <a-alert
      type="info"
      show-icon
      class="section-gap"
      message="凭据只以密文保存"
      description="API Key 提交后立即加密入库，之后页面与接口只显示掩码，无法再次读取明文。"
    />

    <a-alert
      v-if="actionError"
      type="error"
      show-icon
      closable
      class="section-gap"
      :message="actionError.message"
      :description="errorDescription"
      data-testid="form-error"
      @close="actionError = null"
    />

    <a-card size="small" title="服务商信息" class="section-gap">
      <a-form layout="vertical">
        <div class="provider-grid">
          <a-form-item label="显示名称" required>
            <a-input
              v-model:value="providerName"
              :maxlength="100"
              placeholder="例如：本地兼容服务"
              data-testid="provider-name"
            />
          </a-form-item>
          <a-form-item label="接口基地址" required>
            <a-input
              v-model:value="providerBaseUrl"
              :maxlength="2048"
              placeholder="https://api.example.com/v1"
              data-testid="provider-base-url"
            />
          </a-form-item>
          <a-form-item label="API Key">
            <a-input
              v-model:value="providerApiKey"
              type="password"
              autocomplete="off"
              :maxlength="4096"
              placeholder="留空表示暂不配置凭据"
              data-testid="provider-api-key"
            />
          </a-form-item>
          <a-form-item label="说明">
            <a-input v-model:value="providerDescription" :maxlength="500" data-testid="provider-description" />
          </a-form-item>
        </div>
      </a-form>
    </a-card>

    <a-card size="small" title="模型" class="section-gap">
      <p class="model-hint">
        模型名称就是服务商文档里的模型 ID（如 <code>deepseek-chat</code>）；同一服务商内不可重复。
        留空的模型行会被忽略，可以先只建服务商、之后再追加模型。
      </p>
      <div v-for="(model, index) in models" :key="model.key" class="model-row">
        <a-input
          v-model:value="model.name"
          :maxlength="100"
          placeholder="如 deepseek-chat"
          :data-testid="`model-name-${index}`"
        />
        <a-switch
          v-model:checked="model.enabled"
          checked-children="启用"
          un-checked-children="停用"
          :data-testid="`model-enabled-${index}`"
        />
        <a-button
          type="link"
          danger
          :disabled="models.length === 1"
          :data-testid="`remove-model-${index}`"
          @click="removeModel(index)"
        >
          删除
        </a-button>
      </div>
      <a-button :disabled="models.length >= MAX_MODELS" data-testid="add-model" @click="addModel">添加模型</a-button>
    </a-card>

    <a-space class="section-gap">
      <a-button type="primary" :loading="submitting" data-testid="submit-provider" @click="submit">保存</a-button>
      <a-popconfirm
        v-if="isDirty"
        title="表单尚未保存，确定离开吗？"
        ok-text="离开"
        cancel-text="继续填写"
        @confirm="goBack"
      >
        <a-button data-testid="cancel">取消</a-button>
      </a-popconfirm>
      <a-button v-else data-testid="cancel" @click="goBack">取消</a-button>
    </a-space>
  </section>
</template>

<style scoped>
/* 窄窗口自动收成单列：新增表单不产生页面级横向溢出。 */
.provider-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.model-hint {
  margin: 0 0 12px;
  color: var(--ja-color-muted);
  font-size: 12px;
}

.model-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

@media (max-width: 800px) {
  .provider-grid {
    grid-template-columns: 1fr;
  }
}
</style>
