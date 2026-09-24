/**
 * 失败通知分流规则的单元测试。
 *
 * 覆盖需求 `docs/requirements/v1.md` 4.1 的分流口径：只有"无法定位字段且不阻断页面理解"的失败
 * 才弹全局通知；422 与 409 必须原样交回调用方内联展示。
 *
 * 注意:
 *     去重记录保存在模块级 Map 中，文件内的用例共享同一份状态。因此每个用例使用不同的动作名，
 *     只有专门验证去重的用例才重复使用同一个动作名，避免用例之间互相干扰。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { parseServerError } from '@/shared/forms/serverErrors'

const { errorMock, configMock } = vi.hoisted(() => ({ errorMock: vi.fn(), configMock: vi.fn() }))

vi.mock('ant-design-vue', () => ({ notification: { error: errorMock, config: configMock } }))

import {
  FAILURE_NOTICE_DEDUP_WINDOW_MS,
  FAILURE_NOTICE_DURATION_SECONDS,
  FAILURE_NOTICE_MAX_COUNT,
  isGlobalFailure,
  notifyFailure,
  resolveActionFailure,
} from './failureNotice'

/** 构造一个已解析的失败对象。 */
function parsedError(params: {
  code: string
  message: string
  requestId?: string | null
  fields?: Record<string, string>
}) {
  return parseServerError(
    new ApiError({
      code: params.code,
      message: params.message,
      status: 500,
      requestId: params.requestId ?? null,
      details: Object.entries(params.fields ?? {}).map(([field, reason]) => ({ field, reason })),
    }),
  )
}

beforeEach(() => {
  errorMock.mockClear()
  configMock.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('通知全局配置', () => {
  it('模块加载时调用组件库配置，固定右上角、5 秒、最多 3 条的展示口径', async () => {
    // 静态导入已执行过一次配置；重置模块缓存后重新导入，直接验证该副作用而非只验证常量。
    vi.resetModules()
    configMock.mockClear()
    await import('./failureNotice')

    expect(FAILURE_NOTICE_DURATION_SECONDS).toBe(5)
    expect(FAILURE_NOTICE_MAX_COUNT).toBe(3)
    expect(configMock).toHaveBeenCalledWith({
      placement: 'topRight',
      maxCount: FAILURE_NOTICE_MAX_COUNT,
      duration: FAILURE_NOTICE_DURATION_SECONDS,
    })
  })

  it('通知调用携带右上角与 5 秒，保证与全局口径一致', () => {
    const error = parsedError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' })

    notifyFailure(error, '保存个人资料')

    expect(errorMock).toHaveBeenCalledTimes(1)
    expect(errorMock.mock.calls[0][0]).toMatchObject({ placement: 'topRight', duration: 5 })
  })
})

describe('失败分流', () => {
  it('422 字段错误不触发通知，交回调用方内联展示', () => {
    const error = parsedError({
      code: 'VALIDATION_ERROR',
      message: '提交的数据未通过校验。',
      fields: { title: '不能为空。' },
    })

    expect(isGlobalFailure(error)).toBe(false)
    const returned = resolveActionFailure(
      new ApiError({
        code: 'VALIDATION_ERROR',
        message: '提交的数据未通过校验。',
        status: 422,
        details: [{ field: 'title', reason: '不能为空。' }],
      }),
      '保存职位',
    )

    expect(errorMock).not.toHaveBeenCalled()
    expect(returned?.fields).toEqual({ title: '不能为空。' })
  })

  it('409 冲突不触发通知，保留操作上下文提示', () => {
    const error = parsedError({ code: 'CONFLICT', message: '该服务商下存在默认模型。' })

    expect(isGlobalFailure(error)).toBe(false)
    const returned = resolveActionFailure(
      new ApiError({ code: 'CONFLICT', message: '该服务商下存在默认模型。', status: 409 }),
      '归档简历',
    )

    expect(errorMock).not.toHaveBeenCalled()
    expect(returned?.message).toBe('该服务商下存在默认模型。')
  })

  it('网络错误只弹一次通知，且返回 null 表示无需内联展示', () => {
    const returned = resolveActionFailure(
      new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' }),
      '保存职位',
    )

    expect(errorMock).toHaveBeenCalledTimes(1)
    expect(returned).toBeNull()

    // 同一动作的相同失败在窗口内重复出现时不再叠加第二条通知。
    resolveActionFailure(
      new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' }),
      '保存职位',
    )
    expect(errorMock).toHaveBeenCalledTimes(1)
  })

  it('超时与服务端错误同样走通知，并带上错误编号', () => {
    const timeout = resolveActionFailure(
      new ApiError({ code: 'TIMEOUT', message: '请求超时（15000 毫秒），请稍后重试。' }),
      '记录变更',
    )
    const internal = resolveActionFailure(
      new ApiError({
        code: 'INTERNAL_ERROR',
        message: '服务器内部错误，请稍后重试。',
        status: 500,
        requestId: 'req-500',
      }),
      '保存资料',
    )

    expect(timeout).toBeNull()
    expect(internal).toBeNull()
    expect(errorMock).toHaveBeenCalledTimes(2)
    expect(errorMock.mock.calls[0][0]).toMatchObject({ message: '记录变更失败' })
    expect(errorMock.mock.calls[1][0].description).toContain('服务器内部错误，请稍后重试。')
    expect(errorMock.mock.calls[1][0].description).toContain('req-500')
  })

  it('去重窗口只压制窗口内的重复提示，窗口过后允许再次提示', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-24T00:00:00Z'))
    const build = () => new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' })

    resolveActionFailure(build(), '去重用例')
    resolveActionFailure(build(), '去重用例')
    expect(errorMock).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(FAILURE_NOTICE_DEDUP_WINDOW_MS)

    resolveActionFailure(build(), '去重用例')
    expect(errorMock).toHaveBeenCalledTimes(2)
  })

  it('不同动作的相同失败各自提示，不会被去重吞掉', () => {
    const build = () => new ApiError({ code: 'TIMEOUT', message: '请求超时（15000 毫秒），请稍后重试。' })

    resolveActionFailure(build(), '刷新职位详情')
    resolveActionFailure(build(), '刷新简历详情')

    expect(errorMock).toHaveBeenCalledTimes(2)
  })
})
