/**
 * 与后端统一响应契约对接的薄传输层。
 *
 * 三条边界（见 `docs/adr/0001` 与 `docs/adr/0002`）：
 * - 解包只发生在这里：调用点拿到业务数据或抛出的 `ApiError`，不再关心 `success`/`meta`。
 * - 不自动重试：写操作重试可能造成重复提交，是否重试由调用方显式决定。
 * - 不复制后端错误文案，也不枚举后端错误码：`code` 原样透传供调用方分支，展示默认用后端 `message`。
 */

import type { ErrorDetail } from './types'

/** 业务领域接口前缀，与后端 `settings.api_v1_prefix` 保持一致。 */
export const API_V1_PREFIX = '/api/v1'

/** 默认超时（毫秒）：外部依赖异常时避免请求悬挂。 */
export const DEFAULT_TIMEOUT_MS = 15_000

/** 传输层自行产生的错误码；后端错误码不在此枚举，避免与后端错误码表漂移。 */
export type TransportErrorCode = 'NETWORK_ERROR' | 'TIMEOUT' | 'UNEXPECTED_RESPONSE'

/** 请求选项。 */
export interface RequestOptions {
  /** 覆盖默认超时（毫秒）。 */
  timeoutMs?: number
  /** 透传给 fetch 的选项，例如 method、body、headers。 */
  init?: RequestInit
}

/**
 * 统一的失败对象。
 *
 * 调用方用 `code` 决定交互（例如跳登录、弹确认），用 `message` 直接展示；
 * `requestId` 对应服务端日志，出错时可展示为"错误编号"以便排查。
 */
export class ApiError extends Error {
  /** 后端返回的稳定错误码，或传输层的 `NETWORK_ERROR`/`TIMEOUT`/`UNEXPECTED_RESPONSE`。 */
  readonly code: string
  /** HTTP 状态码；网络层失败时为 null。 */
  readonly status: number | null
  /** 服务端请求标识；缺失时为 null。 */
  readonly requestId: string | null
  /** 结构化的失败细节，例如字段级校验原因。 */
  readonly details: readonly ErrorDetail[]

  constructor(params: {
    code: string
    message: string
    status?: number | null
    requestId?: string | null
    details?: readonly ErrorDetail[]
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.code = params.code
    this.status = params.status ?? null
    this.requestId = params.requestId ?? null
    this.details = params.details ?? []
  }
}

/** 发起根路径请求（用于 `/health` 这类不带版本前缀的运维接口）。 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  return unwrap<T>(response)
}

/** 发起业务接口请求，自动拼接 `/api/v1` 前缀。 */
export async function requestV1<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return request<T>(`${API_V1_PREFIX}${path}`, options)
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const headers = new Headers(options.init?.headers)
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  try {
    return await fetch(path, {
      ...options.init,
      headers,
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (error: unknown) {
    throw toTransportError(error, timeoutMs)
  }
}

function toTransportError(error: unknown, timeoutMs: number): ApiError {
  if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
    return new ApiError({ code: 'TIMEOUT', message: `请求超时（${timeoutMs} 毫秒），请稍后重试。` })
  }
  return new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' })
}

async function unwrap<T>(response: Response): Promise<T> {
  const headerRequestId = response.headers.get('X-Request-ID')
  const raw = await response.text()

  let parsed: unknown
  try {
    parsed = raw === '' ? null : JSON.parse(raw)
  } catch {
    // 例如反向代理返回的 HTML 错误页：不能当作本应用的契约处理。
    throw unexpectedResponse(response.status, headerRequestId, '服务返回了无法解析的响应。')
  }

  if (!isRecord(parsed) || typeof parsed['success'] !== 'boolean') {
    throw unexpectedResponse(response.status, headerRequestId, '服务返回了不符合统一契约的响应。')
  }

  const requestId = readRequestId(parsed) ?? headerRequestId

  if (parsed['success'] === false) {
    const rawError = parsed['error']
    throw new ApiError({
      code: readString(rawError, 'code') ?? 'UNEXPECTED_RESPONSE',
      message: readString(rawError, 'message') ?? '请求失败，请稍后重试。',
      status: response.status,
      requestId,
      details: readDetails(rawError),
    })
  }

  if (!('data' in parsed)) {
    throw unexpectedResponse(response.status, requestId, '成功响应缺少 data 字段。')
  }
  return parsed['data'] as T
}

function unexpectedResponse(status: number, requestId: string | null, message: string): ApiError {
  return new ApiError({ code: 'UNEXPECTED_RESPONSE', message, status, requestId })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function readString(source: unknown, key: string): string | null {
  if (!isRecord(source)) {
    return null
  }
  const value = source[key]
  return typeof value === 'string' && value !== '' ? value : null
}

function readRequestId(envelope: Record<string, unknown>): string | null {
  const meta = envelope['meta']
  return isRecord(meta) ? readString(meta, 'request_id') : null
}

function readDetails(rawError: unknown): ErrorDetail[] {
  if (!isRecord(rawError)) {
    return []
  }
  const details = rawError['details']
  if (!Array.isArray(details)) {
    return []
  }
  return details.filter(isRecord).map((item) => ({
    field: typeof item['field'] === 'string' ? item['field'] : null,
    reason: typeof item['reason'] === 'string' ? item['reason'] : '',
  }))
}
