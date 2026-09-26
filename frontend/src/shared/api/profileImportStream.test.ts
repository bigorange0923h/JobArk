/**
 * 流式预览必须报告真实阶段与真实上传进度，并在缺少最终事件时安全失败。
 *
 * 传输层用 `XMLHttpRequest`（`fetch` 观察不到请求体发送过程），因此这里替身也换成 XHR：
 * 由测试精确控制"上传了多少字节""到达了哪一段响应文本"，避免用真实网络时序碰运气。
 */
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { ApiError } from './client'
import { previewProfileImportStream } from './profile'

/** 受控的 `XMLHttpRequest` 替身：只实现被测代码实际用到的那部分接口。 */
class FakeXhr {
  /** 最近一次创建的实例，供测试驱动。 */
  static last: FakeXhr | null = null

  method = ''
  url = ''
  headers: Record<string, string> = {}
  body: string | null = null
  timeout = 0
  readyState = 0
  status = 0
  responseText = ''
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
  onprogress: (() => void) | null = null
  onreadystatechange: (() => void) | null = null
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  ontimeout: (() => void) | null = null

  private responseHeaders: Record<string, string> = {}

  constructor() {
    FakeXhr.last = this
  }

  open(method: string, url: string): void {
    this.method = method
    this.url = url
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value
  }

  getResponseHeader(name: string): string | null {
    return this.responseHeaders[name] ?? null
  }

  send(body: string): void {
    this.body = body
  }

  /** 预设响应头；增量读取期间也可能需要（错误要带上 requestId）。 */
  respond(contentType: string, requestId: string): void {
    this.responseHeaders = { 'Content-Type': contentType, 'X-Request-ID': requestId }
  }

  /** 模拟请求体上传进度；`lengthComputable` 由总字节数是否可得决定。 */
  emitUpload(loaded: number, total: number, lengthComputable = true): void {
    this.upload.onprogress?.({ lengthComputable, loaded, total } as ProgressEvent)
  }

  /** 模拟响应文本的分块到达。 */
  emitChunk(text: string): void {
    this.readyState = 3
    this.responseText += text
    this.onreadystatechange?.()
    this.onprogress?.()
  }

  /** 模拟请求结束。 */
  emitLoad(status: number, contentType = 'text/event-stream', requestId = 'stream-1'): void {
    this.status = status
    this.readyState = 4
    this.respond(contentType, requestId)
    this.onload?.()
  }

  emitError(): void {
    this.onerror?.()
  }

  emitTimeout(): void {
    this.ontimeout?.()
  }
}

/** 取最近一次请求；未发起请求时直接失败，避免测试读到陈旧实例。 */
function lastRequest(): FakeXhr {
  if (FakeXhr.last === null) {
    throw new Error('尚未发起请求')
  }
  return FakeXhr.last
}

beforeEach(() => {
  FakeXhr.last = null
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
})

afterEach(() => vi.unstubAllGlobals())

it('跨网络分块读取上传进度、阶段和最终候选', async () => {
  const result = {
    success: true,
    data: { filename: 'sample.html', source_hash: 'a'.repeat(64), candidate: { full_name: '张三' } },
    meta: { request_id: 'stream-1' },
  }
  const stages: string[] = []
  const uploads: number[] = []
  const pending = previewProfileImportStream('sample.html', 'base64', true, {
    onStage: (stage) => stages.push(stage),
    onUploadProgress: (loaded, total) => uploads.push(Math.round((loaded / total) * 100)),
  })

  const request = lastRequest()
  request.respond('text/event-stream', 'stream-1')
  request.emitUpload(1, 4)
  request.emitChunk('event: progress\ndata: {"stage":"received"}\n\nevent: pro')
  request.emitUpload(4, 4)
  request.emitChunk('gress\ndata: {"stage":"ai_request_started"}\n\n')
  request.emitChunk(`event: result\ndata: ${JSON.stringify(result)}\n\n`)

  const preview = await pending

  expect(uploads).toEqual([25, 100])
  expect(stages).toEqual(['received', 'ai_request_started'])
  expect(preview.candidate.full_name).toBe('张三')
  // 请求形状：固定路径、SSE 接受头、90 秒超时，文件名与同意标记原样提交。
  expect(request.method).toBe('POST')
  expect(request.url).toBe('/api/v1/profile/import-preview-stream')
  expect(request.headers['Accept']).toBe('text/event-stream')
  expect(request.timeout).toBe(90_000)
  expect(request.body).toContain('"confirm_external":true')
})

it('浏览器不提供总字节数时不上报上传进度，避免虚构百分比', async () => {
  const uploads: number[] = []
  const pending = previewProfileImportStream('sample.html', 'base64', true, {
    onStage: () => undefined,
    onUploadProgress: (loaded) => uploads.push(loaded),
  })

  const request = lastRequest()
  request.respond('text/event-stream', 'stream-1')
  request.emitUpload(10, 0, false)
  request.emitChunk(
    `event: result\ndata: ${JSON.stringify({ success: true, data: {}, meta: { request_id: 'stream-1' } })}\n\n`,
  )
  await pending

  expect(uploads).toEqual([])
})

it('流提前结束时报告失败而非返回空候选', async () => {
  const pending = previewProfileImportStream('sample.html', 'base64', true, { onStage: () => undefined })
  const request = lastRequest()
  request.respond('text/event-stream', 'stream-1')
  request.emitChunk('event: progress\ndata: {"stage":"received"}\n\n')
  request.emitLoad(200, 'text/event-stream', 'stream-1')

  await expect(pending).rejects.toMatchObject({
    code: 'UNEXPECTED_RESPONSE',
    requestId: 'stream-1',
  } satisfies Partial<ApiError>)
})

it('最终错误事件保留后端错误码和请求编号', async () => {
  const error = {
    success: false, error: { code: 'VALIDATION_ERROR', message: '候选校验失败', details: [] },
    meta: { request_id: 'stream-1' }, http_status: 422,
  }
  const pending = previewProfileImportStream('sample.html', 'base64', true, { onStage: () => undefined })
  const request = lastRequest()
  request.respond('text/event-stream', 'stream-1')
  request.emitChunk(`event: error\ndata: ${JSON.stringify(error)}\n\n`)

  await expect(pending).rejects.toMatchObject({
    code: 'VALIDATION_ERROR', status: 422, requestId: 'stream-1',
  } satisfies Partial<ApiError>)
})

it('超时与连接失败映射为可理解的安全错误', async () => {
  const timedOut = previewProfileImportStream('sample.html', 'base64', true, { onStage: () => undefined })
  lastRequest().emitTimeout()
  await expect(timedOut).rejects.toMatchObject({ code: 'TIMEOUT' } satisfies Partial<ApiError>)

  const offline = previewProfileImportStream('sample.html', 'base64', true, { onStage: () => undefined })
  lastRequest().emitError()
  await expect(offline).rejects.toMatchObject({ code: 'NETWORK_ERROR' } satisfies Partial<ApiError>)
})
