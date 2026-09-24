<script setup lang="ts">
/**
 * AI 模型配置页。
 *
 * 服务商持有 OpenAI 兼容基地址与加密后的 API Key，模型只持有远端标识并复用服务商凭据；
 * 页面只消费掩码 DTO，**永不接收或缓存明文 Key**，编辑时的提示也只用后端返回的掩码。
 *
 * 默认状态完全以后端为准：任何写操作后重新 `load()`，而不是本地推断"第一个就是默认"。
 * 这与后端的部分唯一索引是同一套事实来源，避免界面与数据库各说一套。
 *
 * 删除走 Popconfirm 明确确认；后端还会校验默认模型不可删除、未确认删除返回 422，
 * 两处共同兜底：确认解决"误触"，后端校验解决"绕过页面直接调用接口"。
 */

import { computed, onMounted, ref } from 'vue'

import {
  createAiModel,
  createAiProvider,
  deleteAiModel,
  deleteAiProvider,
  listAiProviders,
  setDefaultAiModel,
  testAiModel,
  updateAiModel,
  updateAiProvider,
  type AiModel,
  type AiProvider,
  type AiProviderUpdateInput,
} from '@/shared/api/ai'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

/** 每个服务商的行内模型表单状态。 */
interface ModelForm {
  name: string
  remoteModelId: string
}

/**
 * 服务商编辑器的目标与凭据展示信息。
 *
 * 只保留"服务端才知道的事实"（主键、版本、掩码、是否已配置）；
 * 凭据只以 `mask` 作为提示展示，绝不承载明文或密文。
 */
interface ProviderEditorTarget {
  id: string
  version: number
  mask: string | null
  configured: boolean
}

/** 模型编辑器的目标。 */
interface ModelEditorTarget {
  id: string
  version: number
}

const providers = ref<AiProvider[]>([])
const loading = ref(false)
const submitting = ref(false)
/** 正在测试连接的模型主键；同时只允许一个测试在进行。 */
const testingModelId = ref<string | null>(null)
const loadError = ref<ParsedServerError | null>(null)
const actionError = ref<ParsedServerError | null>(null)
const actionNotice = ref<string | null>(null)

const providerName = ref('')
const providerBaseUrl = ref('')
const providerApiKey = ref('')
const providerDescription = ref('')
const modelForms = ref<Record<string, ModelForm>>({})

// 服务商编辑器：`editorApiKey` 恒以空串开始，绝不回填已保存凭据。
const providerEditorTarget = ref<ProviderEditorTarget | null>(null)
const editorName = ref('')
const editorBaseUrl = ref('')
const editorDescription = ref('')
const editorApiKey = ref('')
const editorEnabled = ref(true)

// 模型编辑器。
const modelEditorTarget = ref<ModelEditorTarget | null>(null)
const editorModelName = ref('')
const editorModelRemoteId = ref('')
const editorModelEnabled = ref(true)

/** 编辑器内的失败提示；与页面级 `actionError` 分开，避免弹窗打开时提示被挡在后面。 */
const editorError = ref<ParsedServerError | null>(null)
const savingEditor = ref(false)

const columns = [
  { key: 'name', title: '模型', dataIndex: 'name' },
  { key: 'remote_model_id', title: '远端标识', dataIndex: 'remote_model_id' },
  { key: 'status', title: '状态' },
  { key: 'actions', title: '操作' },
]

/** 把解析后的错误拼成"补充原因 + 错误编号"的说明文本。 */
function describeError(error: ParsedServerError | null): string | undefined {
  if (error === null) {
    return undefined
  }
  const parts = [...error.general]
  if (error.requestId !== null) {
    parts.push(`错误编号：${error.requestId}`)
  }
  return parts.length === 0 ? undefined : parts.join(' ')
}

const loadErrorDescription = computed(() => describeError(loadError.value))
const actionErrorDescription = computed(() => describeError(actionError.value))
const editorErrorDescription = computed(() => describeError(editorError.value))

/** 构造前端本地校验错误；字段级原因留空，整体提示即可定位。 */
function localError(message: string): ParsedServerError {
  return { code: 'VALIDATION_ERROR', message, fields: {}, general: [], requestId: null }
}

/**
 * 前端只拦截明显不安全的地址，完整规则仍以后端 422 为准。
 *
 * 这里提前拦截是为了少一次往返与更快的反馈，不替代后端的权威校验。
 */
function isSafeBaseUrl(value: string): boolean {
  try {
    const url = new URL(value)
    if (url.username !== '' || url.password !== '' || url.search !== '' || url.hash !== '') {
      return false
    }
    if (url.protocol === 'https:') {
      return true
    }
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname)
  } catch {
    return false
  }
}

/** 加载配置；写入成功后也走这里，使界面与后端完全一致。 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const loaded = await listAiProviders()
    providers.value = loaded
    const nextForms: Record<string, ModelForm> = {}
    for (const provider of loaded) {
      // 保留用户已输入但尚未提交的内容，避免每次刷新把表单清空。
      nextForms[provider.id] = modelForms.value[provider.id] ?? { name: '', remoteModelId: '' }
    }
    modelForms.value = nextForms
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  } finally {
    loading.value = false
  }
}

/** 新增服务商；成功后重新拉取并清空输入，失败时保留输入只提示原因。 */
async function submitProvider(): Promise<void> {
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

  submitting.value = true
  actionError.value = null
  actionNotice.value = null
  try {
    const description = providerDescription.value.trim()
    await createAiProvider({
      name,
      base_url: baseUrl,
      // 空输入不提交 api_key：服务端的空值语义是"保持已有密文"，这里保持一致。
      api_key: providerApiKey.value === '' ? null : providerApiKey.value,
      description: description === '' ? null : description,
    })
    providerName.value = ''
    providerBaseUrl.value = ''
    providerApiKey.value = ''
    providerDescription.value = ''
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}

/** 在某个服务商下新增模型；只提交名称与远端标识，绝不把凭据复制到这里。 */
async function submitModel(provider: AiProvider): Promise<void> {
  if (submitting.value) {
    return
  }
  const form = modelForms.value[provider.id]
  const name = form.name.trim()
  const remoteModelId = form.remoteModelId.trim()
  if (name === '' || remoteModelId === '') {
    actionError.value = localError('请填写模型名称与远端模型标识。')
    return
  }

  submitting.value = true
  actionError.value = null
  actionNotice.value = null
  try {
    await createAiModel(provider.id, { name, remote_model_id: remoteModelId })
    form.name = ''
    form.remoteModelId = ''
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}

/** 把模型设为唯一默认模型；成功后重新拉取，让默认标记以后端为准。 */
async function makeDefault(model: AiModel): Promise<void> {
  if (submitting.value) {
    return
  }
  submitting.value = true
  actionError.value = null
  actionNotice.value = null
  try {
    await setDefaultAiModel(model.id)
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}

/** 测试已保存配置的连通性；只显示后端返回的安全文案。 */
async function checkModel(model: AiModel): Promise<void> {
  if (testingModelId.value !== null) {
    return
  }
  testingModelId.value = model.id
  actionError.value = null
  actionNotice.value = null
  try {
    await testAiModel(model.id)
    actionNotice.value = '连接测试通过。'
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    testingModelId.value = null
  }
}

/** 删除服务商（含其模型与凭据）；后端会在仍有默认模型时返回 409。 */
async function removeProvider(provider: AiProvider): Promise<void> {
  if (submitting.value) {
    return
  }
  submitting.value = true
  actionError.value = null
  actionNotice.value = null
  try {
    await deleteAiProvider(provider.id)
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}

/** 删除模型；默认模型由后端拒绝，界面同时禁用按钮以减少无效操作。 */
async function removeModel(model: AiModel): Promise<void> {
  if (submitting.value) {
    return
  }
  submitting.value = true
  actionError.value = null
  actionNotice.value = null
  try {
    await deleteAiModel(model.id)
    await load()
  } catch (error: unknown) {
    actionError.value = parseServerError(error)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void load()
})

// --------------------------------------------------------------------------------------------
// 编辑服务商 / 模型
// --------------------------------------------------------------------------------------------

/** 打开服务商编辑器；凭据输入恒为空，已保存内容只以掩码提示展示。 */
function openProviderEditor(provider: AiProvider): void {
  editorError.value = null
  providerEditorTarget.value = {
    id: provider.id,
    version: provider.version,
    mask: provider.api_key_mask,
    configured: provider.api_key_configured,
  }
  editorName.value = provider.name
  editorBaseUrl.value = provider.base_url
  editorDescription.value = provider.description ?? ''
  editorApiKey.value = ''
  editorEnabled.value = provider.is_enabled
}

/** 关闭服务商编辑器并丢弃未保存内容。 */
function closeProviderEditor(): void {
  providerEditorTarget.value = null
  editorError.value = null
}

/**
 * 保存服务商编辑。
 *
 * 注意:
 *     只有输入了新明文时才提交 `api_key`；留空表示"保留已有密文"，因此界面无法意外清空凭据。
 *     停用仍在承载默认模型的服务商会被后端拒绝（409），这里就地展示后端文案。
 */
async function saveProviderEditor(): Promise<void> {
  const target = providerEditorTarget.value
  if (target === null || savingEditor.value) {
    return
  }
  const name = editorName.value.trim()
  const baseUrl = editorBaseUrl.value.trim()
  if (name === '' || baseUrl === '') {
    editorError.value = localError('请填写服务商名称与接口地址。')
    return
  }
  if (!isSafeBaseUrl(baseUrl)) {
    editorError.value = localError('服务商地址必须使用 HTTPS 或本地回环 HTTP（localhost、127.0.0.1、::1）。')
    return
  }

  savingEditor.value = true
  editorError.value = null
  try {
    const description = editorDescription.value.trim()
    const payload: AiProviderUpdateInput = {
      version: target.version,
      name,
      base_url: baseUrl,
      description: description === '' ? null : description,
      is_enabled: editorEnabled.value,
    }
    if (editorApiKey.value !== '') {
      payload.api_key = editorApiKey.value
    }
    await updateAiProvider(target.id, payload)
    closeProviderEditor()
    // 写入后统一重新加载：默认状态与掩码都以后端返回为准，不在本地推断。
    await load()
  } catch (error: unknown) {
    editorError.value = parseServerError(error)
  } finally {
    savingEditor.value = false
  }
}

/** 打开模型编辑器。 */
function openModelEditor(model: AiModel): void {
  editorError.value = null
  modelEditorTarget.value = { id: model.id, version: model.version }
  editorModelName.value = model.name
  editorModelRemoteId.value = model.remote_model_id
  editorModelEnabled.value = model.is_enabled
}

/** 关闭模型编辑器并丢弃未保存内容。 */
function closeModelEditor(): void {
  modelEditorTarget.value = null
  editorError.value = null
}

/** 保存模型编辑；停用默认模型会被后端拒绝（409），提示就地展示。 */
async function saveModelEditor(): Promise<void> {
  const target = modelEditorTarget.value
  if (target === null || savingEditor.value) {
    return
  }
  const name = editorModelName.value.trim()
  const remoteModelId = editorModelRemoteId.value.trim()
  if (name === '' || remoteModelId === '') {
    editorError.value = localError('请填写模型名称与远端模型标识。')
    return
  }

  savingEditor.value = true
  editorError.value = null
  try {
    await updateAiModel(target.id, {
      version: target.version,
      name,
      remote_model_id: remoteModelId,
      is_enabled: editorModelEnabled.value,
    })
    closeModelEditor()
    await load()
  } catch (error: unknown) {
    editorError.value = parseServerError(error)
  } finally {
    savingEditor.value = false
  }
}
</script>

<template>
  <section class="ai-model-config">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">AI</p>
        <h1>AI 模型配置</h1>
        <p class="page-subtitle">维护 OpenAI 兼容服务商与模型，并选择唯一默认启用模型。</p>
      </div>
      <a-button size="small" :loading="loading" data-testid="reload" @click="load">刷新</a-button>
    </header>

    <a-alert
      type="info"
      show-icon
      class="section-gap"
      message="凭据只以密文保存"
      description="页面与读取接口只显示掩码；连接测试只发送最小协议请求，不发送简历、档案或职位内容。"
    />

    <a-alert
      v-if="actionError"
      type="error"
      show-icon
      closable
      class="section-gap"
      :message="actionError.message"
      :description="actionErrorDescription"
      data-testid="form-error"
      @close="actionError = null"
    />

    <a-alert
      v-if="actionNotice"
      type="success"
      show-icon
      closable
      class="section-gap"
      :message="actionNotice"
      data-testid="action-notice"
      @close="actionNotice = null"
    />

    <a-card size="small" title="新增服务商" class="section-gap">
      <a-form layout="vertical" @submit.prevent="submitProvider">
        <div class="ai-config-grid">
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
              :maxlength="4096"
              autocomplete="off"
              placeholder="仅在创建或替换时提交，留空表示不设置"
              data-testid="provider-api-key"
            />
          </a-form-item>
          <a-form-item label="说明">
            <a-input v-model:value="providerDescription" :maxlength="500" data-testid="provider-description" />
          </a-form-item>
        </div>
        <a-button type="primary" :loading="submitting" data-testid="create-provider" @click="submitProvider">
          保存服务商
        </a-button>
      </a-form>
    </a-card>

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      class="section-gap"
      :message="loadError.message"
      :description="loadErrorDescription"
      data-testid="load-error"
    />

    <a-spin v-if="loading && providers.length === 0 && loadError === null" data-testid="loading" />

    <a-empty
      v-else-if="providers.length === 0 && loadError === null"
      data-testid="empty"
      description="尚未配置 AI 服务商"
    />

    <template v-else>
      <a-card v-for="provider in providers" :key="provider.id" size="small" :title="provider.name" class="section-gap">
        <template #extra>
          <a-space>
            <a-tag v-if="!provider.is_enabled" color="default">已停用</a-tag>
            <a-button size="small" :data-testid="`edit-${provider.id}`" @click="openProviderEditor(provider)">
              编辑
            </a-button>
            <a-popconfirm
              title="删除后将永久移除该服务商的 API Key；此操作不可恢复。"
              ok-text="确认删除"
              cancel-text="取消"
              @confirm="removeProvider(provider)"
            >
              <a-button
                danger
                size="small"
                :disabled="provider.has_default_model"
                :data-testid="`delete-${provider.id}`"
              >
                删除服务商
              </a-button>
            </a-popconfirm>
          </a-space>
        </template>

        <p class="provider-meta">
          接口地址：{{ provider.base_url }} · 凭据：{{
            provider.api_key_configured ? provider.api_key_mask : '未配置'
          }}
        </p>

        <a-table
          :data-source="provider.models"
          :columns="columns"
          row-key="id"
          size="small"
          :pagination="false"
          :scroll="{ x: 'max-content' }"
          :data-testid="`models-${provider.id}`"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag v-if="(record as AiModel).is_default" color="blue">默认启用</a-tag>
              <a-tag v-else-if="!(record as AiModel).is_enabled" color="default">已停用</a-tag>
              <span v-else>启用</span>
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-space>
                <a-button
                  type="link"
                  size="small"
                  :disabled="(record as AiModel).is_default"
                  :data-testid="`set-default-${(record as AiModel).id}`"
                  @click="makeDefault(record as AiModel)"
                >
                  设为默认
                </a-button>
                <a-button
                  type="link"
                  size="small"
                  :loading="testingModelId === (record as AiModel).id"
                  :data-testid="`test-${(record as AiModel).id}`"
                  @click="checkModel(record as AiModel)"
                >
                  测试连接
                </a-button>
                <a-button
                  type="link"
                  size="small"
                  :data-testid="`edit-${(record as AiModel).id}`"
                  @click="openModelEditor(record as AiModel)"
                >
                  编辑
                </a-button>
                <a-popconfirm
                  title="删除后不可恢复；默认模型需先切换为其他模型。"
                  ok-text="确认删除"
                  cancel-text="取消"
                  @confirm="removeModel(record as AiModel)"
                >
                  <a-button
                    type="link"
                    size="small"
                    danger
                    :disabled="(record as AiModel).is_default"
                    :data-testid="`delete-model-${(record as AiModel).id}`"
                  >
                    删除
                  </a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </a-table>

        <a-form layout="inline" class="model-form" @submit.prevent="submitModel(provider)">
          <a-form-item label="模型名称">
            <a-input
              v-model:value="modelForms[provider.id].name"
              :maxlength="100"
              :data-testid="`model-name-${provider.id}`"
            />
          </a-form-item>
          <a-form-item label="远端模型标识">
            <a-input
              v-model:value="modelForms[provider.id].remoteModelId"
              :maxlength="200"
              :data-testid="`model-remote-id-${provider.id}`"
            />
          </a-form-item>
          <a-form-item>
            <a-button
              type="primary"
              :loading="submitting"
              :data-testid="`create-model-${provider.id}`"
              @click="submitModel(provider)"
            >
              新增模型
            </a-button>
          </a-form-item>
        </a-form>
      </a-card>
    </template>

    <!--
      编辑弹窗的可见性由 `v-if` 控制，并关闭到 body 的传送门（`:get-container="false"`）：
      关闭时直接卸载，既避免 jdom 下的传送门移除报错，也让"弹窗是否打开"成为可直接断言的渲染事实。
      代价是每次打开都是新实例，因此表单状态必须在 open* 中显式初始化。
    -->
    <a-modal
      v-if="providerEditorTarget"
      :open="true"
      data-testid="provider-editor"
      title="编辑服务商"
      :confirm-loading="savingEditor"
      :get-container="false"
      ok-text="保存"
      cancel-text="取消"
      @ok="saveProviderEditor"
      @cancel="closeProviderEditor"
    >
      <a-alert
        v-if="editorError"
        type="error"
        show-icon
        class="editor-alert"
        :message="editorError.message"
        :description="editorErrorDescription"
        data-testid="editor-error"
      />
      <a-form layout="vertical">
        <a-form-item label="显示名称" required>
          <a-input v-model:value="editorName" :maxlength="100" data-testid="editor-provider-name" />
        </a-form-item>
        <a-form-item label="接口基地址" required>
          <a-input v-model:value="editorBaseUrl" :maxlength="2048" data-testid="editor-provider-base-url" />
        </a-form-item>
        <a-form-item label="说明">
          <a-input v-model:value="editorDescription" :maxlength="500" data-testid="editor-provider-description" />
        </a-form-item>
        <a-form-item label="替换 API Key">
          <a-input
            v-model:value="editorApiKey"
            type="password"
            autocomplete="off"
            :maxlength="4096"
            :placeholder="
              providerEditorTarget.configured
                ? `留空表示保留现有凭据（${providerEditorTarget.mask ?? '已配置'}）`
                : '留空表示暂不配置凭据'
            "
            data-testid="editor-provider-api-key"
          />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="editorEnabled" data-testid="editor-provider-enabled" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-if="modelEditorTarget"
      :open="true"
      data-testid="model-editor"
      title="编辑模型"
      :confirm-loading="savingEditor"
      :get-container="false"
      ok-text="保存"
      cancel-text="取消"
      @ok="saveModelEditor"
      @cancel="closeModelEditor"
    >
      <a-alert
        v-if="editorError"
        type="error"
        show-icon
        class="editor-alert"
        :message="editorError.message"
        :description="editorErrorDescription"
        data-testid="editor-error"
      />
      <a-form layout="vertical">
        <a-form-item label="模型名称" required>
          <a-input v-model:value="editorModelName" :maxlength="100" data-testid="editor-model-name" />
        </a-form-item>
        <a-form-item label="远端模型标识" required>
          <a-input v-model:value="editorModelRemoteId" :maxlength="200" data-testid="editor-model-remote-id" />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="editorModelEnabled" data-testid="editor-model-enabled" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped>
/* 窄窗口自动收成单列：模型表单与新增服务商表单都不产生页面级横向溢出。 */
.ai-config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.provider-meta {
  margin: 0 0 12px;
  color: var(--ja-color-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.model-form {
  margin-top: 12px;
  row-gap: 8px;
}

.editor-alert {
  margin-bottom: 16px;
}

@media (max-width: 800px) {
  .ai-config-grid {
    grid-template-columns: 1fr;
  }
}
</style>
