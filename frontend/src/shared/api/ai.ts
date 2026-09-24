/**
 * AI 模型配置的接口调用与类型。
 *
 * 类型是后端 schema 的**手工镜像**（对应 `backend/app/ai/schemas/config.py`）：只列界面实际用到的字段。
 * 三条边界由后端保证，前端不复制：
 * - 读取响应只含掩码与"是否已配置"，永不包含明文或密文；
 * - 默认模型至多一个，因此任何写操作后都必须重新读取，而不是本地推断；
 * - 删除必须显式确认，本模块统一携带 `confirmed: true`，避免"点了删除就没了"。
 *
 * 界面上的模型只有一个「模型名称」，而后端分别保存显示名称与发送给服务商的模型名称，
 * 因此写请求统一由本模块的 `toModelPayload` 补成同值：这是该约定的唯一落点，
 * 散到各调用点后总会有某个入口漏填，表现为"某个模型调不通但看不出原因"。
 */

import { requestV1 } from './client'
import type { EditableResource } from './types'

/** 一个模型配置；凭据始终来自其所属服务商。 */
export interface AiModel extends EditableResource {
  provider_id: string
  name: string
  remote_model_id: string
  is_enabled: boolean
  is_default: boolean
}

/** 一个服务商配置；只暴露掩码与"是否已配置"。 */
export interface AiProvider extends EditableResource {
  name: string
  base_url: string
  api_key_configured: boolean
  /** 供展示的固定掩码；未配置凭据时为 null。 */
  api_key_mask: string | null
  description: string | null
  is_enabled: boolean
  /** 其下是否存在默认模型；为真时不能停用或删除该服务商。 */
  has_default_model: boolean
  models: AiModel[]
}

/** 创建服务商的请求体；`api_key` 只在创建或替换时提交。 */
export interface AiProviderCreateInput {
  name: string
  base_url: string
  api_key?: string | null
  description?: string | null
  /** 随服务商一并创建的模型；省略表示先只建服务商，之后再追加。 */
  models?: AiModelCreateInput[]
}

/** 局部更新服务商；`version` 必须原样回传，提交空 `api_key` 表示保留已有密文。 */
export interface AiProviderUpdateInput {
  version: number
  name?: string
  base_url?: string
  api_key?: string
  description?: string | null
  is_enabled?: boolean
}

/** 创建模型的请求体；不携带 API Key，模型名称即服务商文档里的模型 ID。 */
export interface AiModelCreateInput {
  name: string
  is_enabled?: boolean
}

/** 局部更新模型；`is_default` 只能通过设为默认接口变更。 */
export interface AiModelUpdateInput {
  version: number
  name?: string
  is_enabled?: boolean
}

/** 连接测试结果。 */
export interface AiConnectionTest {
  ok: boolean
}

/** 删除结果。 */
export interface AiDeleted {
  id: string
}

/** 列出全部服务商及其模型配置。 */
export function listAiProviders(): Promise<AiProvider[]> {
  return requestV1<AiProvider[]>('/ai/providers')
}

/** 新增服务商，可同时提交其模型；服务端在同一事务内落库，失败不会只建服务商。 */
export function createAiProvider(payload: AiProviderCreateInput): Promise<AiProvider> {
  const { models, ...rest } = payload
  const body = models === undefined ? rest : { ...rest, models: models.map(toModelPayload) }
  return requestV1<AiProvider>('/ai/providers', { init: jsonInit('POST', body) })
}

/** 局部更新服务商；省略或留空的 `api_key` 不会清空已有凭据。 */
export function updateAiProvider(providerId: string, payload: AiProviderUpdateInput): Promise<AiProvider> {
  return requestV1<AiProvider>(`/ai/providers/${providerId}`, { init: jsonInit('PATCH', payload) })
}

/** 删除服务商及其模型配置；API Key 不可恢复。 */
export function deleteAiProvider(providerId: string): Promise<AiDeleted> {
  return requestV1<AiDeleted>(`/ai/providers/${providerId}`, { init: jsonInit('DELETE', { confirmed: true }) })
}

/** 在服务商下新增模型；首个启用模型会成为唯一默认模型。 */
export function createAiModel(providerId: string, payload: AiModelCreateInput): Promise<AiModel> {
  return requestV1<AiModel>(`/ai/providers/${providerId}/models`, { init: jsonInit('POST', toModelPayload(payload)) })
}

/** 局部更新模型；停用默认模型会被后端拒绝（409）。 */
export function updateAiModel(modelId: string, payload: AiModelUpdateInput): Promise<AiModel> {
  const { name, ...rest } = payload
  // 未改名时不提交名称字段：只有用户真的改了名称，才需要同步模型 ID。
  const body = name === undefined ? rest : { ...rest, name, remote_model_id: name }
  return requestV1<AiModel>(`/ai/models/${modelId}`, { init: jsonInit('PATCH', body) })
}

/** 把模型设为唯一默认模型。 */
export function setDefaultAiModel(modelId: string): Promise<AiModel> {
  return requestV1<AiModel>(`/ai/models/${modelId}/default`, { init: jsonInit('POST', {}) })
}

/** 发送一次最小协议请求测试连通性；不发送任何业务数据。 */
export function testAiModel(modelId: string): Promise<AiConnectionTest> {
  return requestV1<AiConnectionTest>(`/ai/models/${modelId}/test`, { init: jsonInit('POST', {}) })
}

/** 删除模型；默认模型需先切换，否则后端返回 409。 */
export function deleteAiModel(modelId: string): Promise<AiDeleted> {
  return requestV1<AiDeleted>(`/ai/models/${modelId}`, { init: jsonInit('DELETE', { confirmed: true }) })
}

/**
 * 把界面上的「模型名称」展开成后端请求体。
 *
 * 后端分别保存显示名称（`name`）与发送给服务商的模型名称（`remote_model_id`），
 * 界面只让用户填一个值，因此在写请求里把两者写成同值。`is_enabled` 未显式给出时不提交，
 * 让后端的默认值（启用）生效，而不是在前端复制一份默认规则。
 */
function toModelPayload(input: AiModelCreateInput): Record<string, unknown> {
  const payload: Record<string, unknown> = { name: input.name, remote_model_id: input.name }
  if (input.is_enabled !== undefined) {
    payload.is_enabled = input.is_enabled
  }
  return payload
}

/** 构造 JSON 请求体；统一在此设置 Content-Type，避免每处调用重复。 */
function jsonInit(method: string, payload: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}
