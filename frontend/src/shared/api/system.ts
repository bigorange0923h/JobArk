/**
 * 系统级接口封装。
 *
 * `/health` 是可运维探针的根路径接口，不带 `/api/v1` 前缀，因此使用 `request` 而非 `requestV1`。
 */

import { request } from './client'

/** 健康检查载荷，对应后端 `HealthResponse`。 */
export interface HealthPayload {
  status: 'ok'
}

/**
 * 查询后端进程存活状态。
 *
 * 返回:
 *     后端健康载荷；失败时抛出 `ApiError`。
 */
export async function fetchHealth(): Promise<HealthPayload> {
  return request<HealthPayload>('/health')
}
