/**
 * @vitest-environment jsdom
 *
 * AI 服务商列表页的状态与写操作测试。
 *
 * 覆盖加载、空、失败、正常、忙碌状态，以及展开行里的模型管理与服务商编辑。
 *
 * 断言重点放在两类容易出错的地方：
 * - 页面只显示掩码，绝不出现真实 Key 或密文；
 * - 默认状态与列表顺序完全以后端为准：任何写操作后都重新拉取，本地不排序、不推断。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import {
  createAiModel,
  deleteAiProvider,
  listAiProviders,
  setDefaultAiModel,
  testAiModel,
  updateAiModel,
  updateAiProvider,
  type AiModel,
  type AiProvider,
} from '@/shared/api/ai'

import AiModelConfigView from './AiModelConfigView.vue'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

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

/** 一个模型配置；`name` 与 `remote_model_id` 同值，与后端写入约定一致。 */
function modelFixture(overrides: Partial<AiModel> = {}): AiModel {
  return {
    id: 'model-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    provider_id: 'provider-1',
    name: 'qwen3',
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

/**
 * 展开第 `index` 个服务商行。
 *
 * 直接点击 Ant Design 的展开按钮，而不是依赖内部状态：展开是用户真实操作，
 * 用同一入口驱动测试，才能同时验证"展开后模型区域确实出现"。
 */
async function expandRow(wrapper: VueWrapper, index = 0): Promise<void> {
  const icons = wrapper.findAll('.ant-table-row-expand-icon')
  const icon = icons[index]
  if (icon === undefined) {
    throw new Error('没有找到展开按钮。')
  }
  await icon.trigger('click')
  await flushPromises()
}

/**
 * 归一化按钮文案后按文案点击。
 *
 * Ant Design 会在两个汉字之间插入空格（渲染为 `保 存`），直接按原文案比较会失败，
 * 而失败信息看起来像是"按钮不存在"。
 */
async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const target = text.replace(/[\s\u200b]/g, '')
  const button = wrapper.findAll('button').find((candidate) => candidate.text().replace(/[\s\u200b]/g, '') === target)
  if (button === undefined) {
    const found = wrapper
      .findAll('button')
      .map((candidate) => JSON.stringify(candidate.text()))
      .join(', ')
    throw new Error(`没有找到按钮「${text}」；当前按钮为：${found}`)
  }
  await button.trigger('click')
}

beforeEach(() => {
  vi.clearAllMocks()
  pushMock.mockReset()
  vi.mocked(listAiProviders).mockResolvedValue([providerFixture()])
  vi.mocked(deleteAiProvider).mockResolvedValue({ id: 'provider-1' })
  vi.mocked(createAiModel).mockResolvedValue(modelFixture())
  vi.mocked(setDefaultAiModel).mockResolvedValue(modelFixture())
  vi.mocked(testAiModel).mockResolvedValue({ ok: true })
  vi.mocked(updateAiProvider).mockResolvedValue(providerFixture({ name: '改名后的服务商' }))
  vi.mocked(updateAiModel).mockResolvedValue(modelFixture())
})

enableAutoUnmount(afterEach)

describe('AiModelConfigView 列表', () => {
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

  it('列表顺序完全按接口返回，不在前端重排', async () => {
    vi.mocked(listAiProviders).mockResolvedValue([
      providerFixture({
        id: 'provider-2',
        name: '后创建的服务',
        models: [modelFixture({ id: 'model-2', provider_id: 'provider-2' })],
      }),
      providerFixture({ id: 'provider-1', name: '先创建的服务' }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text.indexOf('后创建的服务')).toBeLessThan(text.indexOf('先创建的服务'))
  })

  it('显示凭据掩码而非明文', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('••••alue')
    expect(wrapper.text()).not.toContain('secret-value')
  })

  it('点击「新增服务商」进入独立新增页', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="create-provider-link"]').trigger('click')

    expect(pushMock).toHaveBeenCalledWith({ name: 'ai-provider-new' })
  })

  it('展开服务商后才显示其模型与追加表单', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="models-provider-1"]').exists()).toBe(false)

    await expandRow(wrapper)

    expect(wrapper.find('[data-testid="models-provider-1"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('默认启用')
    // 模型名称列展示真正发给服务商的标识。
    expect(wrapper.text()).toContain('qwen3')
  })

  it('展开行追加模型只提交名称并重新拉取', async () => {
    const wrapper = mountView()
    await flushPromises()
    await expandRow(wrapper)

    await wrapper.find('[data-testid="model-name-provider-1"]').setValue('gpt-4.1-mini')
    await wrapper.find('[data-testid="create-model-provider-1"]').trigger('click')
    await flushPromises()

    expect(createAiModel).toHaveBeenCalledWith('provider-1', { name: 'gpt-4.1-mini' })
    expect(listAiProviders).toHaveBeenCalledTimes(2)
    expect((wrapper.find('[data-testid="model-name-provider-1"]').element as HTMLInputElement).value).toBe('')
  })

  it('模型名称为空时不发请求', async () => {
    const wrapper = mountView()
    await flushPromises()
    await expandRow(wrapper)

    await wrapper.find('[data-testid="create-model-provider-1"]').trigger('click')
    await flushPromises()

    expect(createAiModel).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('模型名称')
  })

  it('切换默认模型后重新拉取，以后端状态为准', async () => {
    vi.mocked(listAiProviders).mockResolvedValue([
      providerFixture({ has_default_model: false, models: [modelFixture({ is_default: false })] }),
    ])
    const wrapper = mountView()
    await flushPromises()
    await expandRow(wrapper)

    await wrapper.find('[data-testid="set-default-model-1"]').trigger('click')
    await flushPromises()

    expect(setDefaultAiModel).toHaveBeenCalledWith('model-1')
    expect(listAiProviders).toHaveBeenCalledTimes(2)
  })

  it('连接测试失败显示后端安全文案与错误编号', async () => {
    const wrapper = mountView()
    await flushPromises()
    await expandRow(wrapper)
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

  it('宽表格自身横向滚动，避免撑宽页面', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent({ name: 'ATable' }).props('scroll')).toEqual({ x: 'max-content' })
  })
})

describe('AiModelConfigView 编辑与启停', () => {
  it('打开服务商编辑器时不回填凭据，只在提示里显示掩码', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="edit-provider-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.ant-modal').exists()).toBe(true)
    const keyInput = wrapper.find('[data-testid="editor-provider-api-key"]')
    // 凭据输入只能为空或新明文：绝不能预填、也不能回显已保存内容。
    expect((keyInput.element as HTMLInputElement).value).toBe('')
    expect(keyInput.attributes('placeholder')).toContain('••••alue')
    expect(wrapper.text()).not.toContain('secret-value')
    expect(wrapper.html()).not.toContain('ciphertext')
    expect((wrapper.find('[data-testid="editor-provider-name"]').element as HTMLInputElement).value).toBe(
      '本地兼容服务',
    )
  })

  it('编辑服务商：未填 Key 时不提交凭据，保存后重新加载并关闭弹窗', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="edit-provider-1"]').trigger('click')
    await wrapper.find('[data-testid="editor-provider-name"]').setValue('改名后的服务商')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(updateAiProvider).toHaveBeenCalledTimes(1)
    const [providerId, payload] = vi.mocked(updateAiProvider).mock.calls[0]
    expect(providerId).toBe('provider-1')
    expect(payload).toEqual({
      version: 1,
      name: '改名后的服务商',
      base_url: 'http://localhost:11434/v1',
      description: null,
      is_enabled: true,
    })
    expect(payload).not.toHaveProperty('api_key')
    expect(listAiProviders).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.ant-modal').exists()).toBe(false)
  })

  it('替换 API Key 时提交新明文', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="edit-provider-1"]').trigger('click')
    await wrapper.find('[data-testid="editor-provider-api-key"]').setValue('new-secret')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(vi.mocked(updateAiProvider).mock.calls[0][1]).toHaveProperty('api_key', 'new-secret')
  })

  it('停用服务商时提交 is_enabled=false', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="edit-provider-1"]').trigger('click')
    await wrapper.find('[data-testid="editor-provider-enabled"]').trigger('click')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(vi.mocked(updateAiProvider).mock.calls[0][1].is_enabled).toBe(false)
  })

  it('编辑模型只提交一个模型名称与启停状态', async () => {
    const wrapper = mountView()
    await flushPromises()
    await expandRow(wrapper)

    await wrapper.find('[data-testid="edit-model-1"]').trigger('click')
    await flushPromises()
    // 编辑器以真正生效的模型名称预填，保证与列表一致。
    expect((wrapper.find('[data-testid="editor-model-name"]').element as HTMLInputElement).value).toBe('qwen3')

    await wrapper.find('[data-testid="editor-model-name"]').setValue('qwen3-max')
    await wrapper.find('[data-testid="editor-model-enabled"]').trigger('click')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(updateAiModel).toHaveBeenCalledWith('model-1', {
      version: 1,
      name: 'qwen3-max',
      is_enabled: false,
    })
    expect(listAiProviders).toHaveBeenCalledTimes(2)
  })

  it('停用默认模型冲突时展示后端文案与错误编号，并保持弹窗打开', async () => {
    vi.mocked(updateAiModel).mockRejectedValue(
      new ApiError({
        code: 'CONFLICT',
        message: '默认模型不能被停用，请先设置其他启用模型为默认。',
        status: 409,
        requestId: 'req-conflict',
      }),
    )
    const wrapper = mountView()
    await flushPromises()
    await expandRow(wrapper)

    await wrapper.find('[data-testid="edit-model-1"]').trigger('click')
    await wrapper.find('[data-testid="editor-model-enabled"]').trigger('click')
    await clickButton(wrapper, '保存')
    await flushPromises()

    const alert = wrapper.find('[data-testid="editor-error"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('默认模型不能被停用')
    expect(alert.text()).toContain('req-conflict')
    expect(wrapper.find('.ant-modal').exists()).toBe(true)
    // 冲突时不重新加载：界面保持用户已填内容，交由用户决定下一步。
    expect(listAiProviders).toHaveBeenCalledTimes(1)
  })

  it('停用承载默认模型的服务商时展示后端冲突文案', async () => {
    vi.mocked(updateAiProvider).mockRejectedValue(
      new ApiError({
        code: 'CONFLICT',
        message: '该服务商下存在默认模型，请先设置其他启用模型为默认，再停用服务商。',
        status: 409,
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="edit-provider-1"]').trigger('click')
    await wrapper.find('[data-testid="editor-provider-enabled"]').trigger('click')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(wrapper.find('[data-testid="editor-error"]').text()).toContain('该服务商下存在默认模型')
    expect(wrapper.find('.ant-modal').exists()).toBe(true)
  })

  it('删除服务商遇到后端冲突时展示安全文案', async () => {
    vi.mocked(listAiProviders).mockResolvedValue([
      providerFixture({ has_default_model: false, models: [modelFixture({ is_default: false })] }),
    ])
    vi.mocked(deleteAiProvider).mockRejectedValue(
      new ApiError({
        code: 'CONFLICT',
        message: '该服务商下存在默认模型，请先设置其他启用模型为默认，再删除服务商。',
        status: 409,
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.findComponent({ name: 'APopconfirm' }).vm.$emit('confirm')
    await flushPromises()

    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('该服务商下存在默认模型')
    expect(listAiProviders).toHaveBeenCalledTimes(1)
  })

  it('编辑保存期间重复点击只提交一次', async () => {
    let resolveUpdate: ((provider: AiProvider) => void) | undefined
    vi.mocked(updateAiProvider).mockReturnValue(
      new Promise<AiProvider>((resolve) => {
        resolveUpdate = resolve
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="edit-provider-1"]').trigger('click')
    await clickButton(wrapper, '保存')
    await clickButton(wrapper, '保存')

    expect(updateAiProvider).toHaveBeenCalledTimes(1)

    resolveUpdate?.(providerFixture())
    await flushPromises()
    expect(wrapper.find('.ant-modal').exists()).toBe(false)
  })
})
