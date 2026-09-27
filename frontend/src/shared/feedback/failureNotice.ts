/**
 * 操作失败的统一反馈分流。
 *
 * 为什么需要分流，而不是"所有失败都弹通知"：字段校验失败、版本冲突和页面加载失败都必须留在
 * 用户当时的上下文里（字段下方、表单摘要、页面重试入口）。一旦统一替换成会自动消失的通知，
 * 用户既看不到该改哪个字段，也无法在通知消失后重试。因此这里只把**无法定位到字段、且不会让
 * 页面失去理解**的失败交给全局通知，其余失败原样返回给调用方内联展示。
 *
 * 通知口径集中在本模块：右上角、约 5 秒自动关闭、同屏最多 3 条、相同错误短时间内只提示一次。
 * 页面不直接调用组件库的通知 API，否则每处的时长、位置与去重规则会各自漂移。
 */

import { notification } from 'ant-design-vue'

import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

/** 错误通知停留时长（秒）：过短来不及读，过长会持续遮挡页面内容。 */
export const FAILURE_NOTICE_DURATION_SECONDS = 5

/** 同屏最多可见的错误通知数量；超出上限时由组件库关闭最早的一条。 */
export const FAILURE_NOTICE_MAX_COUNT = 3

/** 相同错误的去重窗口（毫秒）：窗口内的重复失败不再弹第二条通知。 */
export const FAILURE_NOTICE_DEDUP_WINDOW_MS = 5000

/** 去重记录的清理阈值：超过后丢弃过期项，避免长时间运行后记录无界增长。 */
const DEDUP_CACHE_LIMIT = 50

/**
 * 适合走全局通知的错误码白名单。
 *
 * 刻意用白名单而不是"除 422/409 之外都弹"：新增的错误码默认留在内联上下文里。
 * 宁可少弹一条通知，也不要把需要用户就地处理的失败从页面上挪走。
 */
const GLOBAL_FAILURE_CODES: ReadonlySet<string> = new Set([
  'NETWORK_ERROR',
  'TIMEOUT',
  'INTERNAL_ERROR',
  'UNEXPECTED_RESPONSE',
])

/** 最近提示过的失败：去重键 → 上次提示时间戳（毫秒）。 */
const recentFailures = new Map<string, number>()

// 全局通知口径只在这里设置一次；静态方法共享同一份配置。
notification.config({
  placement: 'topRight',
  maxCount: FAILURE_NOTICE_MAX_COUNT,
  duration: FAILURE_NOTICE_DURATION_SECONDS,
})

/**
 * 判断失败是否应交给全局通知。
 *
 * 参数:
 *     error: 已解析的失败对象。
 *
 * 返回:
 *     boolean: 无法定位到字段、且页面本身仍能被理解时返回 true。
 */
export function isGlobalFailure(error: ParsedServerError): boolean {
  return GLOBAL_FAILURE_CODES.has(error.code)
}

/**
 * 弹出错误通知。
 *
 * 参数:
 *     error: 已解析的失败对象。
 *     action: 用户正在做的动作，例如"保存职位"；用于通知标题与去重键。
 *
 * 注意:
 *     去重键包含动作名：同一动作的相同失败在窗口内只提示一次，而不同动作各自保留提示，
 *     因为它们对应两次不同的操作失败。错误编号会一并展示，便于用户报错时检索服务端日志。
 */
export function notifyFailure(error: ParsedServerError, action: string): void {
  const now = Date.now()
  const key = `${error.code}|${error.message}|${action}`
  const lastShownAt = recentFailures.get(key)
  if (lastShownAt !== undefined && now - lastShownAt < FAILURE_NOTICE_DEDUP_WINDOW_MS) {
    return
  }
  pruneDedupCache(now)
  recentFailures.set(key, now)

  const description = error.requestId === null ? error.message : `${error.message} 错误编号：${error.requestId}`
  notification.error({
    key,
    message: `${action}失败`,
    description,
    class: 'ja-form-notice ja-form-notice--error',
    placement: 'topRight',
    duration: FAILURE_NOTICE_DURATION_SECONDS,
  })
}

/**
 * 处理"用户操作失败"的统一入口。
 *
 * 参数:
 *     error: 捕获到的异常，通常是 `ApiError`。
 *     action: 用户正在做的动作，例如"保存职位"。
 *
 * 返回:
 *     ParsedServerError | null: 需要内联展示时返回解析结果（422 字段错误、409 冲突等）；
 *     已用全局通知反馈过时返回 null，调用方不需要再内联渲染。
 *
 * 注意:
 *     需要同时检查字段级错误或错误码调用方（例如表单面板）应改用 `isGlobalFailure` 与
 *     `notifyFailure` 的组合，以免为了分流而丢掉 `fields`。
 */
export function resolveActionFailure(error: unknown, action: string): ParsedServerError | null {
  const parsed = parseServerError(error)
  if (!isGlobalFailure(parsed)) {
    return parsed
  }
  notifyFailure(parsed, action)
  return null
}

/**
 * 清理过期的去重记录。
 *
 * 参数:
 *     now: 当前时间戳（毫秒）。
 *
 * 注意:
 *     只有记录数超过阈值时才扫描，使常见路径保持常数开销。
 */
function pruneDedupCache(now: number): void {
  if (recentFailures.size < DEDUP_CACHE_LIMIT) {
    return
  }
  for (const [key, shownAt] of recentFailures) {
    if (now - shownAt >= FAILURE_NOTICE_DEDUP_WINDOW_MS) {
      recentFailures.delete(key)
    }
  }
}
