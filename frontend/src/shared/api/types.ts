/**
 * 后端统一响应契约的 TypeScript 镜像。
 *
 * 契约定义见 `docs/adr/0001-统一响应与异常契约.md`。类型在此手工维护而不是由 OpenAPI 生成：
 * 后端目前只有 `/health`，代码生成的产物为零，等到业务接口稳定后再评估引入生成器。
 */

/** 响应的追踪信息。 */
export interface ResponseMeta {
  request_id: string
}

/** 单项错误细节。 */
export interface ErrorDetail {
  /** 出错字段路径；非字段级错误为 null。 */
  field: string | null
  /** 面向用户的失败原因。 */
  reason: string
}

/** 错误对象。 */
export interface ApiErrorBody {
  /** 稳定错误码，取值见 ADR 0001 的错误码表。 */
  code: string
  /** 面向用户的安全提示，可直接展示。 */
  message: string
  details: ErrorDetail[]
}

/** 成功响应。 */
export interface ApiSuccess<T> {
  success: true
  data: T
  meta: ResponseMeta
}

/** 失败响应。 */
export interface ApiFailure {
  success: false
  error: ApiErrorBody
  meta: ResponseMeta
}

/** 统一响应包装。 */
export type ApiEnvelope<T> = ApiSuccess<T> | ApiFailure
