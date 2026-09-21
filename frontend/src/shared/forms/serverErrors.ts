/**
 * 把后端失败响应转换成界面可直接使用的形态。
 *
 * 解析只在这里做一次：页面与表单拿到的是"总体提示 / 字段级原因 / 请求标识"，
 * 不需要各自深入 `ApiError.details` 的结构。同一段解析散落在多处的后果是它们会慢慢出现
 * 细微差异（例如某处过滤了空原因、某处没有合并同字段的多条原因），最终表现为同类错误在不同
 * 表单上提示不一致。
 */

import { ApiError } from '../api/client'

/** 解析后的服务端错误。 */
export interface ParsedServerError {
  /** 稳定错误码；传输层失败时为 `NETWORK_ERROR`/`TIMEOUT` 等传输码。 */
  code: string
  /** 可直接展示的提示文案（来自后端，已保证不含内部细节）。 */
  message: string
  /** 字段名 → 原因。字段名与后端请求体字段名一致，因此可直接用于表单定位。 */
  fields: Record<string, string>
  /** 非字段级原因，例如"该记录已被资料修订引用"。 */
  general: string[]
  /** 服务端请求标识，便于用户报错时提供，用来检索服务端日志。 */
  requestId: string | null
}

/** 无法识别的异常使用的兜底提示。 */
const UNKNOWN_ERROR_MESSAGE = '发生未知错误，请重试。'

/**
 * 解析异常对象。
 *
 * 参数:
 *     error: 捕获到的异常；通常是 `ApiError`。
 *
 * 返回:
 *     ParsedServerError: 界面可直接消费的结构；非 `ApiError` 时给出兜底提示且不含字段级错误。
 *
 * 约定:
 *     同一字段出现多条原因时按出现顺序用"；"合并，而不是只保留第一条——例如"结束日期早于开始
 *     日期"与"日期格式非法"可能同时成立，只显示一条会让用户改完一处后再次失败。
 */
export function parseServerError(error: unknown): ParsedServerError {
  if (!(error instanceof ApiError)) {
    return { code: 'UNKNOWN_ERROR', message: UNKNOWN_ERROR_MESSAGE, fields: {}, general: [], requestId: null }
  }

  const fields: Record<string, string> = {}
  const general: string[] = []
  for (const detail of error.details) {
    if (detail.field === null) {
      general.push(detail.reason)
      continue
    }
    const existing = fields[detail.field]
    fields[detail.field] = existing === undefined ? detail.reason : `${existing}；${detail.reason}`
  }

  return { code: error.code, message: error.message, fields, general, requestId: error.requestId }
}
