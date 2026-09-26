/**
 * 服务商接口地址的本地前置校验。
 *
 * 只拦"明显不安全"的地址，权威规则仍在后端：这里提前拦是为了少一次往返与更快的反馈，
 * 不替代后端的 422。新增服务商页与编辑服务商弹窗共用同一份规则——各写一份的后果是
 * 同一地址在一处能存、在另一处被拒，用户无法从界面判断到底哪条规则有效。
 */

/** 允许使用明文 HTTP 的主机名；其余地址必须是 HTTPS。 */
const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '::1', '[::1]']

/**
 * 判断接口基地址是否明显不安全。
 *
 * 参数:
 *     value: 用户输入的接口基地址原文。
 *
 * 返回:
 *     boolean: 形如 `https://host/path`，或指向本机回环的 `http://host/path` 时返回 true。
 *
 * 注意:
 *     带用户名、密码、查询参数或片段的地址一律拒绝：它们既可能把凭据写进日志，
 *     也让"基地址"语义变得不确定（大模型服务适配器只在其后拼接固定路径）。
 */
export function isSafeBaseUrl(value: string): boolean {
  try {
    const url = new URL(value)
    if (url.username !== '' || url.password !== '' || url.search !== '' || url.hash !== '') {
      return false
    }
    if (url.protocol === 'https:') {
      return true
    }
    return url.protocol === 'http:' && LOOPBACK_HOSTS.includes(url.hostname)
  } catch {
    return false
  }
}
