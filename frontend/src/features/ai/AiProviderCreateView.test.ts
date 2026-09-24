/**
 * @vitest-environment jsdom
 *
 * 新增 AI 服务商页的测试。
 *
 * 覆盖一次提交多个模型、本地校验、空行忽略、失败保留输入与成功返回列表这几条关键行为。
 * 断言重点：保存只会发出一次请求（服务端在同一事务内落库），失败时不得丢失用户已填内容。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { createAiProvider, type AiProvider } from '@/shared/api/ai'

import AiProviderCreateView from './AiProviderCreateView.vue'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

vi.mock('@/shared/api/ai', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/ai')>()
  return { ...actual, createAiProvider: vi.fn() }
})

/** 一个服务商配置，作为创建成功的返回值。 */
function providerFixture(): AiProvider {
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
    models: [],
  }
}

function mountView(): VueWrapper {
  return mount(AiProviderCreateView)
}

/** 填好服务商必填项，供多个用例复用。 */
async function fillProvider(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-testid="provider-name"]').setValue('本地兼容服务')
  await wrapper.find('[data-testid="provider-base-url"]').setValue('http://localhost:11434/v1')
}

beforeEach(() => {
  vi.clearAllMocks()
  pushMock.mockReset()
  vi.mocked(createAiProvider).mockResolvedValue(providerFixture())
})

enableAutoUnmount(afterEach)

describe('AiProviderCreateView', () => {
  it('默认给出一行空模型行，且删除按钮不可用', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="model-name-0"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="model-name-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="remove-model-0"]').attributes('disabled')).toBeDefined()
  })

  it('服务商名称或地址为空时不发请求', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="provider-name"]').setValue('本地兼容服务')
    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await flushPromises()

    expect(createAiProvider).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('接口地址')
  })

  it('不安全的基地址在前端就拒绝提交', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="provider-name"]').setValue('不安全服务')
    await wrapper.find('[data-testid="provider-base-url"]').setValue('http://example.com/v1')
    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await flushPromises()

    expect(createAiProvider).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('HTTPS')
  })

  it('一次提交服务商与多个模型，空行被忽略，成功后返回列表', async () => {
    const wrapper = mountView()
    await flushPromises()
    await fillProvider(wrapper)
    await wrapper.find('[data-testid="provider-api-key"]').setValue('secret-value')

    await wrapper.find('[data-testid="model-name-0"]').setValue('qwen3')
    await wrapper.find('[data-testid="add-model"]').trigger('click')
    await wrapper.find('[data-testid="model-name-1"]').setValue('qwen2.5')
    await wrapper.find('[data-testid="model-enabled-1"]').trigger('click')
    // 第三行保持为空：留空代表"这次不建这个模型"，不应拦下整个表单。
    await wrapper.find('[data-testid="add-model"]').trigger('click')

    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await flushPromises()

    expect(createAiProvider).toHaveBeenCalledTimes(1)
    expect(createAiProvider).toHaveBeenCalledWith({
      name: '本地兼容服务',
      base_url: 'http://localhost:11434/v1',
      api_key: 'secret-value',
      description: null,
      models: [
        { name: 'qwen3', is_enabled: true },
        { name: 'qwen2.5', is_enabled: false },
      ],
    })
    expect(pushMock).toHaveBeenCalledWith({ name: 'ai-models' })
  })

  it('未填写凭据时不提交该字段内容', async () => {
    const wrapper = mountView()
    await flushPromises()
    await fillProvider(wrapper)

    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await flushPromises()

    expect(vi.mocked(createAiProvider).mock.calls[0][0]).toMatchObject({ api_key: null, models: [] })
  })

  it('表单内模型名称重复时本地拦截', async () => {
    const wrapper = mountView()
    await flushPromises()
    await fillProvider(wrapper)

    await wrapper.find('[data-testid="model-name-0"]').setValue('qwen3')
    await wrapper.find('[data-testid="add-model"]').trigger('click')
    await wrapper.find('[data-testid="model-name-1"]').setValue('qwen3')
    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await flushPromises()

    expect(createAiProvider).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('重复')
  })

  it('失败时保留输入并展示后端文案与错误编号', async () => {
    vi.mocked(createAiProvider).mockRejectedValue(
      new ApiError({
        code: 'CONFLICT',
        message: '服务商名称已存在，请更换后重试。',
        status: 409,
        requestId: 'req-create',
      }),
    )
    const wrapper = mountView()
    await flushPromises()
    await fillProvider(wrapper)
    await wrapper.find('[data-testid="model-name-0"]').setValue('qwen3')

    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await flushPromises()

    const alert = wrapper.find('[data-testid="form-error"]')
    expect(alert.text()).toContain('服务商名称已存在')
    expect(alert.text()).toContain('req-create')
    expect((wrapper.find('[data-testid="provider-name"]').element as HTMLInputElement).value).toBe('本地兼容服务')
    expect((wrapper.find('[data-testid="model-name-0"]').element as HTMLInputElement).value).toBe('qwen3')
    expect(pushMock).not.toHaveBeenCalled()
  })

  it('可以删除中间一行模型', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="model-name-0"]').setValue('qwen3')
    await wrapper.find('[data-testid="add-model"]').trigger('click')
    await wrapper.find('[data-testid="model-name-1"]').setValue('qwen2.5')
    await wrapper.find('[data-testid="remove-model-0"]').trigger('click')
    await flushPromises()

    expect((wrapper.find('[data-testid="model-name-0"]').element as HTMLInputElement).value).toBe('qwen2.5')
    expect(wrapper.find('[data-testid="model-name-1"]').exists()).toBe(false)
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
    await fillProvider(wrapper)

    await wrapper.find('[data-testid="submit-provider"]').trigger('click')
    await wrapper.find('[data-testid="submit-provider"]').trigger('click')

    expect(createAiProvider).toHaveBeenCalledTimes(1)

    resolveCreate?.(providerFixture())
    await flushPromises()
  })

  it('表单为空时取消直接返回，不会多一次确认', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="cancel"]').trigger('click')

    expect(pushMock).toHaveBeenCalledWith({ name: 'ai-models' })
  })

  it('已填写内容时取消需要确认，避免误丢输入', async () => {
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('[data-testid="provider-name"]').setValue('本地兼容服务')

    await wrapper.find('[data-testid="cancel"]').trigger('click')
    expect(pushMock).not.toHaveBeenCalled()

    await wrapper.findComponent({ name: 'APopconfirm' }).vm.$emit('confirm')
    await flushPromises()
    expect(pushMock).toHaveBeenCalledWith({ name: 'ai-models' })
  })
})
