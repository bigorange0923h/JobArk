<script setup lang="ts">
/**
 * AI 服务商列表页。
 *
 * 页面只做两件事：如实展示已保存的配置，以及在用户明确操作后触发生效的写请求。
 * 新增服务商与其模型在独立页面（`/ai-models/new`）一次提交：服务端在同一个事务里
 * 落库，避免"先建服务商、再回来逐个补模型"的两步流程与半成品状态。
 *
 * 列表顺序完全以后端为准（最新创建在前），页面不做本地排序——排序规则只存在一处。
 * 模型管理收在展开行里：列表保持清爽，同时设置默认、测试连接、编辑与删除一个都不少。
 *
 * 凭据只以掩码展示：读取接口不返回明文或密文，编辑输入框恒为空，页面永不接收真实 Key。
 */

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { PlusOutlined } from '@ant-design/icons-vue'

import {
  createAiModel,
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
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { isSafeBaseUrl } from '@/shared/forms/baseUrl'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

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

const router = useRouter()

const providers = ref<AiProvider[]>([])
const loading = ref(false)
const submitting = ref(false)
/** 正在测试连接的模型主键；同时只允许一个测试在进行。 */
const testingModelId = ref<string | null>(null)
const loadError = ref<ParsedServerError | null>(null)
const actionError = ref<ParsedServerError | null>(null)
const actionNotice = ref<string | null>(null)

/** 各服务商展开行里"追加模型"的输入；按服务商主键保存，避免刷新时清空用户输入。 */
const newModelNames = ref<Record<string, string>>({})
/** 当前展开"追加模型"表单的服务商主键；同时只有一个表单可见，初始为收起状态。 */
const addingModelFor = ref<string | null>(null)

// 服务商编辑器：`editorApiKey` 恒以空串开始，绝不回填已保存凭据。
const providerEditorTarget = ref<ProviderEditorTarget | null>(null)
const editorName = ref('')
const editorBaseUrl = ref('')
const editorDescription = ref('')
const editorApiKey = ref('')
const editorEnabled = ref(true)

// 模型编辑器：界面只有一个「模型名称」，因此只用一份输入状态。
const modelEditorTarget = ref<ModelEditorTarget | null>(null)
const editorModelName = ref('')
const editorModelEnabled = ref(true)

/** 编辑器内的失败提示；与页面级 `actionError` 分开，避免弹窗打开时提示被挡在后面。 */
const editorError = ref<ParsedServerError | null>(null)
const savingEditor = ref(false)

const providerColumns = [
  { key: 'name', title: '服务商', dataIndex: 'name' },
  { key: 'base_url', title: '接口地址', dataIndex: 'base_url' },
  { key: 'credential', title: '凭据' },
  { key: 'models', title: '模型' },
  { key: 'actions', title: '操作' },
]

const modelColumns = [
  // 展示真正发给服务商的模型名称；显示名称与它同值，无需重复一列。
  { key: 'name', title: '模型名称', dataIndex: 'remote_model_id' },
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
/** 编辑器始终从最新列表读取服务商，单项模型操作刷新后不会继续操作过期快照。 */
const editingProvider = computed(() => {
  if (providerEditorTarget.value === null) return null
  return providers.value.find(provider => provider.id === providerEditorTarget.value?.id) ?? null
})

/** 构造前端本地校验错误；字段级原因留空，整体提示即可定位。 */
function localError(message: string): ParsedServerError {
  return { code: 'VALIDATION_ERROR', message, fields: {}, general: [], requestId: null }
}

/** 服务商下的默认模型；用于在列表里直接指出"当前用的是哪个"。 */
function defaultModelOf(provider: AiProvider): AiModel | undefined {
  return provider.models.find((model) => model.is_default)
}

/** 进入新增页；新增与模型配置在一次提交里完成。 */
function openCreatePage(): void {
  void router.push({ name: 'ai-provider-new' })
}

/** 加载配置；写入成功后也走这里，使界面与后端完全一致。 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const loaded = await listAiProviders()
    providers.value = loaded
    const nextNames: Record<string, string> = {}
    for (const provider of loaded) {
      // 保留用户已输入但尚未提交的内容，避免每次刷新把表单清空。
      nextNames[provider.id] = newModelNames.value[provider.id] ?? ''
    }
    newModelNames.value = nextNames
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  } finally {
    loading.value = false
  }
}

/** 打开当前编辑服务商下的"追加模型"表单；先清掉页面级错误，避免旧提示挡在新输入前面。 */
function openAddModelForm(provider: AiProvider): void {
  actionError.value = null
  addingModelFor.value = provider.id
}

/** 关闭"追加模型"表单并丢弃未保存输入；下次再打开时输入框为空。 */
function closeAddModelForm(): void {
  const provider = editingProvider.value
  addingModelFor.value = null
  if (provider !== null) {
    newModelNames.value[provider.id] = ''
  }
}

/** 在某个服务商下追加模型；只提交名称，凭据始终复用所属服务商。 */
async function submitModel(provider: AiProvider): Promise<void> {
  if (submitting.value) {
    return
  }
  const name = (newModelNames.value[provider.id] ?? '').trim()
  if (name === '') {
    actionError.value = localError('请填写模型名称。')
    return
  }

  submitting.value = true
  actionError.value = null
  actionNotice.value = null
  try {
    await createAiModel(provider.id, { name })
    // 提交成功后再收起表单并清空输入：UI 进入"未在追加模型"的可继续状态。
    closeAddModelForm()
    await load()
  } catch (error: unknown) {
    actionError.value = resolveActionFailure(error, '追加模型')
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
    actionError.value = resolveActionFailure(error, '设置默认模型')
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
    actionError.value = resolveActionFailure(error, '测试模型连接')
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
    actionError.value = resolveActionFailure(error, '删除服务商')
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
    actionError.value = resolveActionFailure(error, '删除模型')
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
  // 切换服务商时重置表单展开状态，避免看到上一个服务商的陈旧输入与错误提示。
  addingModelFor.value = null
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
  addingModelFor.value = null
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

/** 打开模型编辑器；名称取真正生效的模型名称，保证与列表展示一致。 */
function openModelEditor(model: AiModel): void {
  editorError.value = null
  modelEditorTarget.value = { id: model.id, version: model.version }
  editorModelName.value = model.remote_model_id
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
  if (name === '') {
    editorError.value = localError('请填写模型名称。')
    return
  }

  savingEditor.value = true
  editorError.value = null
  try {
    await updateAiModel(target.id, {
      version: target.version,
      name,
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
      <a-space>
        <a-button type="primary" size="small" data-testid="create-provider-link" @click="openCreatePage">
          新增服务商
        </a-button>
        <a-button size="small" :loading="loading" data-testid="reload" @click="load">刷新</a-button>
      </a-space>
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

    <a-table
      v-else
      :data-source="providers"
      :columns="providerColumns"
      row-key="id"
      size="small"
      :pagination="false"
      :scroll="{ x: 'max-content' }"
      data-testid="providers"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'">
          <span>{{ (record as AiProvider).name }}</span>
          <a-tag v-if="!(record as AiProvider).is_enabled" color="default" class="row-tag">已停用</a-tag>
        </template>
        <template v-else-if="column.key === 'base_url'">
          <span class="provider-url">{{ (record as AiProvider).base_url }}</span>
        </template>
        <template v-else-if="column.key === 'credential'">
          <span>{{ (record as AiProvider).api_key_configured ? (record as AiProvider).api_key_mask : '未配置' }}</span>
        </template>
        <template v-else-if="column.key === 'models'">
          <span>{{ (record as AiProvider).models.length }} 个</span>
          <a-tag v-if="defaultModelOf(record as AiProvider)" color="blue" class="row-tag">
            默认：{{ defaultModelOf(record as AiProvider)?.remote_model_id }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'actions'">
          <a-space>
            <a-button size="small" :data-testid="`edit-${(record as AiProvider).id}`" @click="openProviderEditor(record as AiProvider)">
              配置
            </a-button>
            <a-popconfirm
              title="删除后将永久移除该服务商的 API Key；此操作不可恢复。"
              ok-text="确认删除"
              cancel-text="取消"
              @confirm="removeProvider(record as AiProvider)"
            >
              <a-button
                danger
                size="small"
                :disabled="(record as AiProvider).has_default_model"
                :data-testid="`delete-${(record as AiProvider).id}`"
              >
                删除服务商
              </a-button>
            </a-popconfirm>
          </a-space>
        </template>
      </template>

    </a-table>

    <!--
      编辑弹窗的可见性由 `v-if` 控制，并关闭到 body 的传送门（`:get-container="false"`）：
      关闭时直接卸载，既避免 jdom 下的传送门移除报错，也让"弹窗是否打开"成为可直接断言的渲染事实。
      代价是每次打开都是新实例，因此表单状态必须在 open* 中显式初始化。
    -->
    <a-modal
      v-if="providerEditorTarget && modelEditorTarget === null"
      :open="true"
      data-testid="provider-editor"
      title="配置服务商"
      :width="860"
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
      <template v-if="editingProvider">
        <a-divider>模型配置</a-divider>
        <p class="model-hint">模型操作会立即单项保存并刷新配置；这避免多个模型同时修改时出现部分保存的误导。</p>
        <div class="provider-models" :data-testid="`models-${editingProvider.id}`">
          <a-table :data-source="editingProvider.models" :columns="modelColumns" row-key="id" size="small" :pagination="false" :scroll="{ x: 'max-content' }">
            <template #bodyCell="{ column, record: model }">
              <template v-if="column.key === 'status'">
                <a-tag v-if="(model as AiModel).is_default" color="blue">默认启用</a-tag>
                <a-tag v-else-if="!(model as AiModel).is_enabled" color="default">已停用</a-tag>
                <span v-else>启用</span>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" size="small" :disabled="(model as AiModel).is_default" :data-testid="`set-default-${(model as AiModel).id}`" @click="makeDefault(model as AiModel)">设为默认</a-button>
                  <a-button type="link" size="small" :loading="testingModelId === (model as AiModel).id" :data-testid="`test-${(model as AiModel).id}`" @click="checkModel(model as AiModel)">测试连接</a-button>
                  <a-button type="link" size="small" :data-testid="`edit-${(model as AiModel).id}`" @click="openModelEditor(model as AiModel)">编辑</a-button>
                  <a-popconfirm title="删除后不可恢复；默认模型需先切换为其他模型。" ok-text="确认删除" cancel-text="取消" @confirm="removeModel(model as AiModel)">
                    <a-button type="link" size="small" danger :disabled="(model as AiModel).is_default" :data-testid="`delete-model-${(model as AiModel).id}`">删除</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
          <!--
            默认只显示"添加模型"按钮，避免无意义的输入框一直占用列表底部。
            点击后展开输入框与"确定 / 取消"按钮：确定才提交，取消仅关闭并清空。
          -->
          <div class="model-add-area" :data-testid="`model-add-${editingProvider.id}`">
            <a-button
              v-if="addingModelFor !== editingProvider.id"
              type="primary"
              shape="circle"
              size="small"
              title="添加模型"
              aria-label="添加模型"
              :data-testid="`open-add-model-${editingProvider.id}`"
              @click="openAddModelForm(editingProvider)"
            >
              <template #icon><PlusOutlined /></template>
            </a-button>
            <a-form
              v-else
              layout="inline"
              class="model-form"
              @submit.prevent="submitModel(editingProvider)"
            >
              <a-form-item label="模型名称">
                <a-input
                  v-model:value="newModelNames[editingProvider.id]"
                  :maxlength="100"
                  placeholder="如 deepseek-chat"
                  :data-testid="`model-name-${editingProvider.id}`"
                />
              </a-form-item>
              <a-form-item>
                <a-space>
                  <a-button
                    type="primary"
                    size="small"
                    :loading="submitting"
                    :disabled="submitting"
                    :data-testid="`confirm-add-model-${editingProvider.id}`"
                    @click="submitModel(editingProvider)"
                  >
                    确定
                  </a-button>
                  <a-button
                    size="small"
                    :disabled="submitting"
                    :data-testid="`cancel-add-model-${editingProvider.id}`"
                    @click="closeAddModelForm"
                  >
                    取消
                  </a-button>
                </a-space>
              </a-form-item>
            </a-form>
          </div>
        </div>
      </template>
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
          <a-input
            v-model:value="editorModelName"
            :maxlength="100"
            placeholder="如 deepseek-chat"
            data-testid="editor-model-name"
          />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="editorModelEnabled" data-testid="editor-model-enabled" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped>
.provider-url {
  overflow-wrap: anywhere;
}

.row-tag {
  margin-left: 8px;
}

.provider-models { padding-top: 4px; }

.model-hint { margin: 0 0 12px; color: var(--ja-color-muted); font-size: 12px; }

.model-form {
  margin-top: 12px;
  row-gap: 8px;
}

/*
 * 添加按钮与展开后的表单都需要跟上方模型表明显分开：
 * 之前紧贴表尾，操作模型时容易误点"添加模型"，现在固定 12px 间距。
 */
.model-add-area {
  margin-top: 12px;
}

.editor-alert {
  margin-bottom: 16px;
}
</style>
