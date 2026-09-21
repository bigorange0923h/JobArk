/**
 * API Client 契约测试。
 *
 * 覆盖正常路径与关键失败路径：成功解包、业务接口前缀、失败响应的错误码与请求标识透传、
 * 非契约响应、网络失败、超时，以及"不自动重试"这一写操作安全约束。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, DEFAULT_TIMEOUT_MS, request, requestV1 } from './client'

const SUCCESS_ENVELOPE = {
  success: true,
  data: { status: 'ok' },
  meta: { request_id: 'req-success' },
}

const FAILURE_ENVELOPE = {
  success: false,
  error: { code: 'ROUTE_NOT_FOUND', message: '请求的接口不存在。', details: [] },
  meta: { request_id: 'req-failure' },
}

const VALIDATION_ENVELOPE = {
  success: false,
  error: {
    code: 'VALIDATION_ERROR',
    message: '提交的数据未通过校验。',
    details: [{ field: 'query.limit', reason: '不是整数' }],
  },
  meta: { request_id: 'req-validation' },
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function stubFetch(response: Response | Error): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() => (response instanceof Error ? Promise.reject(response) : Promise.resolve(response)))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function captureError(action: Promise<unknown>): Promise<ApiError> {
  try {
    await action
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      return error
    }
    throw error
  }
  throw new Error('预期抛出 ApiError，但请求成功了。')
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request', () => {
  it('成功响应只返回 data，不把包装结构泄漏给调用方', async () => {
    stubFetch(jsonResponse(SUCCESS_ENVELOPE))

    await expect(request<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' })
  })

  it('requestV1 会拼接业务接口前缀', async () => {
    const fetchMock = stubFetch(jsonResponse(SUCCESS_ENVELOPE))

    await requestV1('/jobs')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs', expect.anything())
  })

  it('失败响应抛出携带错误码、提示与请求标识的 ApiError', async () => {
    stubFetch(jsonResponse(FAILURE_ENVELOPE, 404))

    const error = await captureError(request('/nope'))

    expect(error.code).toBe('ROUTE_NOT_FOUND')
    expect(error.message).toBe('请求的接口不存在。')
    expect(error.status).toBe(404)
    expect(error.requestId).toBe('req-failure')
  })

  it('保留字段级失败细节，供表单定位问题字段', async () => {
    stubFetch(jsonResponse(VALIDATION_ENVELOPE, 422))

    const error = await captureError(request('/_probe'))

    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.details).toEqual([{ field: 'query.limit', reason: '不是整数' }])
  })

  it('未知错误码原样透传，不做猜测', async () => {
    stubFetch(
      jsonResponse({
        success: false,
        error: { code: 'SOME_FUTURE_CODE', message: '未来新增的失败类别。', details: [] },
        meta: { request_id: 'req-future' },
      }),
    )

    const error = await captureError(request('/health'))

    expect(error.code).toBe('SOME_FUTURE_CODE')
  })

  it('响应体不是契约结构时抛出 UNEXPECTED_RESPONSE', async () => {
    // 反向代理返回 HTML 错误页是线上最常见的情形。
    stubFetch(new Response('<html>Bad Gateway</html>', { status: 502 }))

    const error = await captureError(request('/health'))

    expect(error.code).toBe('UNEXPECTED_RESPONSE')
    expect(error.status).toBe(502)
  })

  it('网络失败抛出 NETWORK_ERROR', async () => {
    stubFetch(new TypeError('Failed to fetch'))

    const error = await captureError(request('/health'))

    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.status).toBeNull()
  })

  it('超时抛出 TIMEOUT 并说明超时阈值', async () => {
    stubFetch(new DOMException('signal timed out', 'TimeoutError'))

    const error = await captureError(request('/health'))

    expect(error.code).toBe('TIMEOUT')
    expect(error.message).toContain(String(DEFAULT_TIMEOUT_MS))
  })

  it('失败请求不重试，避免写操作重复提交', async () => {
    const fetchMock = stubFetch(jsonResponse(FAILURE_ENVELOPE, 409))

    await captureError(request('/applications', { init: { method: 'POST' } }))

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('响应体缺少请求标识时回落到响应头', async () => {
    stubFetch(
      jsonResponse({ success: false, error: { code: 'CONFLICT', message: '冲突。', details: [] } }, 409, {
        'X-Request-ID': 'header-request-id',
      }),
    )

    const error = await captureError(request('/health'))

    expect(error.requestId).toBe('header-request-id')
  })
})
