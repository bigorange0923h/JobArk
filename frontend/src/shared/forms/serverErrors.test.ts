/**
 * 服务端错误解析的测试。
 *
 * 覆盖正常路径（字段级原因、非字段级原因、请求标识）与兜底路径（无法识别的异常、
 * 同字段多条原因），因为这些分支直接决定用户看到什么提示。
 */

import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { parseServerError } from './serverErrors'

describe('parseServerError', () => {
  it('把带字段名的细节归到对应字段，非字段级细节单独收集', () => {
    const error = new ApiError({
      code: 'CONFLICT',
      message: '该记录已被资料修订引用，不能删除。',
      status: 409,
      requestId: 'req-1',
      details: [
        { field: null, reason: '被修订 1、2 引用；请先处理相关修订。' },
        { field: 'version', reason: '当前版本为 2，提交的是 1。' },
      ],
    })

    const parsed = parseServerError(error)

    expect(parsed.code).toBe('CONFLICT')
    expect(parsed.message).toBe('该记录已被资料修订引用，不能删除。')
    expect(parsed.fields).toEqual({ version: '当前版本为 2，提交的是 1。' })
    expect(parsed.general).toEqual(['被修订 1、2 引用；请先处理相关修订。'])
    expect(parsed.requestId).toBe('req-1')
  })

  it('同一字段的多条原因合并展示，不丢弃后面的条目', () => {
    const error = new ApiError({
      code: 'VALIDATION_ERROR',
      message: '提交的数据未通过校验。',
      details: [
        { field: 'end_date', reason: '不得早于开始日期。' },
        { field: 'end_date', reason: '日期格式非法。' },
      ],
    })

    expect(parseServerError(error).fields['end_date']).toBe('不得早于开始日期。；日期格式非法。')
  })

  it('对非 ApiError 给出兜底提示且不产生字段级错误', () => {
    const parsed = parseServerError(new TypeError('Failed to fetch'))

    expect(parsed.code).toBe('UNKNOWN_ERROR')
    expect(parsed.message).toBe('发生未知错误，请重试。')
    expect(parsed.fields).toEqual({})
    expect(parsed.general).toEqual([])
    expect(parsed.requestId).toBeNull()
  })

  it('传输层失败同样可解析，保持错误码可用于分支', () => {
    const parsed = parseServerError(new ApiError({ code: 'TIMEOUT', message: '请求超时（15000 毫秒），请稍后重试。' }))

    expect(parsed.code).toBe('TIMEOUT')
    expect(parsed.fields).toEqual({})
  })
})
