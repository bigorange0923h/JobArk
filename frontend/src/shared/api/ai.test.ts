/**
 * AI 配置 API 封装测试。
 *
 * 只验证"路径 + 方法 + 载荷"这一层：默认模型唯一性、凭据掩码、删除确认等业务规则都由后端裁决，
 * 前端不复制一份。最关键的断言是"新增模型不携带服务商凭据"——把 `api_key` 混进模型请求会让凭据
 * 出现在本不该出现的位置，而页面看起来完全正常，属于难以察觉的越界。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createAiModel,
  createAiProvider,
  deleteAiModel,
  deleteAiProvider,
  listAiProviders,
  setDefaultAiModel,
  testAiModel,
  updateAiModel,
  updateAiProvider,
} from './ai'

const { requestV1Mock } = vi.hoisted(() => ({
  requestV1Mock: vi.fn<(path: string, options?: unknown) => Promise<unknown>>(),
}))

vi.mock('./client', () => ({ requestV1: requestV1Mock }))

interface CapturedRequest {
  path: string
  init: RequestInit
}

/** 取出最近一次请求的路径与 init，避免在断言里反复做非空判断。 */
function lastRequest(): CapturedRequest {
  const calls = requestV1Mock.mock.calls
  const call = calls[calls.length - 1]
  const path = call?.[0]
  const init = (call?.[1] as { init?: RequestInit } | undefined)?.init
  if (typeof path !== 'string' || init === undefined) {
    throw new Error('未捕获到带 init 的请求。')
  }
  return { path, init }
}

/** 解析最近一次请求的 JSON 请求体。 */
function lastBody(): unknown {
  return JSON.parse(String(lastRequest().init.body))
}

beforeEach(() => {
  requestV1Mock.mockReset()
  requestV1Mock.mockResolvedValue(undefined)
})

describe('AI 配置 API', () => {
  it('读取服务商列表只依赖配置接口', async () => {
    await listAiProviders()

    expect(requestV1Mock).toHaveBeenCalledWith('/ai/providers')
  })

  it('新增服务商提交显示名称、基地址与可选凭据', async () => {
    await createAiProvider({ name: '本地兼容服务', base_url: 'http://localhost:11434/v1', api_key: 'secret' })

    expect(lastRequest().path).toBe('/ai/providers')
    expect(lastRequest().init.method).toBe('POST')
    expect(lastBody()).toEqual({ name: '本地兼容服务', base_url: 'http://localhost:11434/v1', api_key: 'secret' })
  })

  it('新增模型不把服务商凭据重复提交', async () => {
    await createAiModel('provider-1', { name: '轻量模型', remote_model_id: 'gpt-4.1-mini' })

    expect(lastRequest().path).toBe('/ai/providers/provider-1/models')
    expect(lastRequest().init.method).toBe('POST')
    expect(lastBody()).toEqual({ name: '轻量模型', remote_model_id: 'gpt-4.1-mini' })
  })

  it('设为默认与连接测试使用模型级路径', async () => {
    await setDefaultAiModel('model-1')

    expect(lastRequest().path).toBe('/ai/models/model-1/default')
    expect(lastRequest().init.method).toBe('POST')

    await testAiModel('model-1')

    expect(lastRequest().path).toBe('/ai/models/model-1/test')
    expect(lastRequest().init.method).toBe('POST')
  })

  it('删除必须携带显式确认，避免误删凭据', async () => {
    await deleteAiModel('model-1')

    expect(lastRequest().path).toBe('/ai/models/model-1')
    expect(lastRequest().init.method).toBe('DELETE')
    expect(lastBody()).toEqual({ confirmed: true })

    await deleteAiProvider('provider-1')

    expect(lastRequest().path).toBe('/ai/providers/provider-1')
    expect(lastBody()).toEqual({ confirmed: true })
  })

  it('更新服务商与模型使用 PATCH 并原样回传版本号', async () => {
    await updateAiProvider('provider-1', { version: 2, name: '新名称' })

    expect(lastRequest().path).toBe('/ai/providers/provider-1')
    expect(lastRequest().init.method).toBe('PATCH')
    expect(lastBody()).toEqual({ version: 2, name: '新名称' })

    await updateAiModel('model-1', { version: 3, is_enabled: false })

    expect(lastRequest().path).toBe('/ai/models/model-1')
    expect(lastBody()).toEqual({ version: 3, is_enabled: false })
  })
})
