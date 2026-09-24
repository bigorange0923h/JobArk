/**
 * @vitest-environment jsdom
 *
 * AI 模型配置页的状态与写入测试。
 *
 * 覆盖计划要求的全部界面状态：加载中、空态、加载失败（带错误编号）、正常展示、
 * 保存忙碌、表单校验、默认切换、连接测试失败、删除确认与窄窗口布局类。
 *
 * 断言重点放在两类容易出错的地方：
 * - 页面只显示掩码，绝不出现真实 Key 或密文；
 * - 默认状态完全以后端为准：任何写操作后都重新拉取，而不是本地猜测。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import {
  createAiModel,
  createAiProvider,
  deleteAiProvider,
  listAiProviders,
  setDefaultAiModel,
  testAiModel,
  type AiModel,
  type AiProvider,
} from '@/shared/api/ai'

import AiModelConfigView from './AiModelConfigView.vue'

vi.mock('@/shared/api/ai', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/ai')>()
  return {
    ...actual,
    listAiProviders: vi.fn(),
    createAiProvider: vi.fn(),
    updateAiProvider: vi.fn(),
    deleteAiProvider: vi.fn(),
    createAiModel: vi.fn(),
    updateAiModel: vi.fn(),
    setDefaultAiModel: vi.fn(),
    testAiModel: vi.fn(),
    deleteAiModel: vi.fn(),
  }
})

/** 一个模型配置。 */
function modelFixture(overrides: Partial<AiModel> = {}): AiModel {
  return {
    id: 'model-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    provider_id: 'provider-1',
    name: '本地模型',
    remote_model_id: 'qwen3',
    is_enabled: true,
    is_default: true,
    ...overrides,
  }
}

/** 一个服务商配置。 */
function providerFixture(overrides: Partial<AiProvider> = {}): AiProvider {
  return {
    id: 'provider-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    name: '本地兼容服务',
    base_url: 'http://localhost:11434/v1',
    api_key_configured: true,
    api_key_mask: '••••alue',
    description: null,
    is_enabled: true,
    has_default_model: true,
    models: [modelFixture()],
    ...overrides,
  }
}

function mountView(): VueWrapper {
  return mount(AiModelConfigView)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listAiProviders).mockResolvedValue([providerFixture()])
  vi.mocked(createAiProvider).mockResolvedValue(providerFixture())
  vi.mocked(deleteAiProvider).mockResolvedValue({ id: 'provider-1' })
  vi.mocked(createAiModel).mockResolvedValue(modelFixture())
  vi.mocked(setDefaultAiModel).mockResolvedValue(modelFixture())
  vi.mocked(testAiModel).mockResolvedValue({ ok: true })
})

enableAutoUnmount(afterEach)

describe('AiModelConfigView', () => {
  it('加载中显示进度指示', async () => {
    vi.mocked(listAiProviders).mockReturnValue(new Promise(() => {}))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(true)
  })

  it('空配置显示空态而不是错误', async () => {
    vi.mocked(listAiProviders).mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="load-error"]').exists()).toBe(false)
  })

  it('加载失败显示后端安全文案与错误编号', async () => {
    vi.mocked(listAiProviders).mockRejectedValue(
      new ApiError({
        code: 'NETWORK_ERROR',
        message: '无法连接到服务，请确认后端是否已启动。',
        requestId: 'req-ai',
      }),
    )

    const wrapper = mountView()
    await flushPromises()

    const alert = wrapper.find('[data-testid="load-error"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('无法连接到服务，请确认后端是否已启动。')
    expect(alert.text()).toContain('req-ai')
  })

  it('首个模型读取为默认模型，并显示掩码而非明文', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('默认启用')
    expect(wrapper.text()).toContain('••••alue')
    expect(wrapper.text()).not.toContain('secret-value')
  })

  it('新增服务商提交明文凭据、重新拉取并清空输入', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="provider-name"]').setValue('云端服务')
    await wrapper.find('[data-testid="provider-base-url"]').setValue('https://example.test/v1')
    await wrapper.find('[data-testid="provider-api-key"]').setValue('secret-value')
    await wrapper.find('[data-testid="create-provider"]').trigger('click')
    await flushPromises()

    expect(createAiProvider).toHaveBeenCalledWith({
      name: '云端服务',
      base_url: 'https://example.test/v1',
      api_key: 'secret-value',
      description: null,
    })
    expect(listAiProviders).toHaveBeenCalledTimes(2)
    expect((wrapper.find('[data-testid="provider-name"]').element as HTMLInputElement).value).toBe('')
  })

  it('不安全的基地址在前端就拒绝提交', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="provider-name"]').setValue('不安全服务')
    await wrapper.find('[data-testid="provider-base-url"]').setValue('http://example.com/v1')
    await wrapper.find('[data-testid="create-provider"]').trigger('click')
    await flushPromises()

    expect(createAiProvider).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('HTTPS')
  })

  it('保存期间重复点击只提交一次', async () => {
    let resolveCreate: ((provider: AiProvider) => void) | undefined
    vi.mocked(createAiProvider).mockReturnValue(
      new Promise<AiProvider>((resolve) => {
        resolveCreate = resolve
      }),
    )

    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('[data-testid="provider-name"]').setValue('云端服务')
    await wrapper.find('[data-testid="provider-base-url"]').setValue('https://example.test/v1')

    await wrapper.find('[data-testid="create-provider"]').trigger('click')
    await wrapper.find('[data-testid="create-provider"]').trigger('click')

    expect(createAiProvider).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="create-provider"]').classes()).toContain('ant-btn-loading')

    resolveCreate?.(providerFixture())
    await flushPromises()
  })

  it('新增模型只提交名称与远端标识', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="model-name-provider-1"]').setValue('轻量模型')
    await wrapper.find('[data-testid="model-remote-id-provider-1"]').setValue('gpt-4.1-mini')
    await wrapper.find('[data-testid="create-model-provider-1"]').trigger('click')
    await flushPromises()

    expect(createAiModel).toHaveBeenCalledWith('provider-1', {
      name: '轻量模型',
      remote_model_id: 'gpt-4.1-mini',
    })
    expect(listAiProviders).toHaveBeenCalledTimes(2)
  })

  it('切换默认模型后重新拉取，以后端状态为准', async () => {
    vi.mocked(listAiProviders).mockResolvedValue([
      providerFixture({ has_default_model: false, models: [modelFixture({ is_default: false })] }),
    ])
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="set-default-model-1"]').trigger('click')
    await flushPromises()

    expect(setDefaultAiModel).toHaveBeenCalledWith('model-1')
    expect(listAiProviders).toHaveBeenCalledTimes(2)
  })

  it('连接测试失败显示后端安全文案与错误编号', async () => {
    const wrapper = mountView()
    await flushPromises()
    vi.mocked(testAiModel).mockRejectedValue(
      new ApiError({
        code: 'VALIDATION_ERROR',
        message: 'AI 请求失败或结果无效，原始资料已保留，请稍后手动重试。',
        status: 422,
        requestId: 'req-test',
      }),
    )

    await wrapper.find('[data-testid="test-model-1"]').trigger('click')
    await flushPromises()

    const alert = wrapper.find('[data-testid="form-error"]')
    expect(alert.text()).toContain('AI 请求失败或结果无效')
    expect(alert.text()).toContain('req-test')
  })

  it('删除服务商必须确认后才调用接口并重新拉取', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="delete-provider-1"]').exists()).toBe(true)
    await wrapper.findComponent({ name: 'APopconfirm' }).vm.$emit('confirm')
    await flushPromises()

    expect(deleteAiProvider).toHaveBeenCalledWith('provider-1')
    expect(listAiProviders).toHaveBeenCalledTimes(2)
  })

  it('窄窗口使用可换行的栅格类，避免页面横向溢出', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.ai-config-grid').exists()).toBe(true)
  })
})
