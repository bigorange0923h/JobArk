/** 流式预览必须报告真实阶段，并在缺少最终事件时安全失败。 */
import { afterEach, expect, it, vi } from 'vitest'

import { ApiError } from './client'
import { previewProfileImportStream } from './profile'

afterEach(() => vi.unstubAllGlobals())

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(body, {
    headers: { 'Content-Type': 'text/event-stream', 'X-Request-ID': 'stream-1' },
  })
}

it('跨网络分块读取阶段和最终候选', async () => {
  const result = {
    success: true,
    data: { filename: 'sample.html', source_hash: 'a'.repeat(64), candidate: { full_name: '张三' } },
    meta: { request_id: 'stream-1' },
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
    'event: progress\ndata: {"stage":"received"}\n\nevent: pro',
    'gress\ndata: {"stage":"ai_request_started"}\n\n',
    `event: result\ndata: ${JSON.stringify(result)}\n\n`,
  ])))
  const stages: string[] = []
  const preview = await previewProfileImportStream('sample.html', 'base64', true, stage => stages.push(stage))
  expect(stages).toEqual(['received', 'ai_request_started'])
  expect(preview.candidate.full_name).toBe('张三')
})

it('流提前结束时报告失败而非返回空候选', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse(['event: progress\ndata: {"stage":"received"}\n\n'])))
  await expect(previewProfileImportStream('sample.html', 'base64', true, () => undefined)).rejects.toMatchObject({
    code: 'UNEXPECTED_RESPONSE', requestId: 'stream-1',
  } satisfies Partial<ApiError>)
})

it('最终错误事件保留后端错误码和请求编号', async () => {
  const error = {
    success: false, error: { code: 'VALIDATION_ERROR', message: '候选校验失败', details: [] },
    meta: { request_id: 'stream-1' }, http_status: 422,
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([`event: error\ndata: ${JSON.stringify(error)}\n\n`])))
  await expect(previewProfileImportStream('sample.html', 'base64', true, () => undefined)).rejects.toMatchObject({
    code: 'VALIDATION_ERROR', status: 422, requestId: 'stream-1',
  } satisfies Partial<ApiError>)
})
