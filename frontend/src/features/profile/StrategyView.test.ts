/** @vitest-environment jsdom */
/** 求职策略独立页的建档引导、既有数据回填、保存和加载失败反馈。 */
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { fetchProfile, savePreference, type Profile } from '@/shared/api/profile'

import StrategyView from './StrategyView.vue'
import { CITY_OPTIONS } from './cityOptions'

function mountView(attach = false) {
  return mount(StrategyView, {
    ...(attach ? { attachTo: document.body } : {}),
    global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="`/${to.name}`"><slot /></a>' } } },
  })
}

vi.mock('@/shared/api/profile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/profile')>()
  return { ...actual, fetchProfile: vi.fn(), savePreference: vi.fn() }
})

function fixture(): Profile {
  return {
    id: 'profile-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    version: 1, singleton_key: 'default', full_name: '张伟', headline: null, summary: null,
    email: null, phone: null, city: '上海', links: [], evidences: [], skills: [],
    experiences: [], projects: [], educations: [], languages: [],
    preference: {
      id: 'preference-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      version: 3, target_locations: ['上海'], job_types: ['全职'], salary_min: null,
      salary_max: null, salary_currency: null, remote_preference: 'HYBRID', exclusions: [],
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchProfile).mockResolvedValue(fixture())
  vi.mocked(savePreference).mockResolvedValue(fixture().preference!)
})
enableAutoUnmount(afterEach)

it('独立页面回填既有偏好，保存沿用版本号并重新读取', async () => {
  const wrapper = mountView()
  await flushPromises()

  expect(wrapper.find('[data-testid="panel-preference"]').exists()).toBe(true)
  expect(wrapper.find('[data-testid="strategy-scope-notice"]').text()).toContain('结构化排除规则用于当前职位筛选')
  await wrapper.find('[data-testid="save-preference"]').trigger('click')
  await flushPromises()

  expect(savePreference).toHaveBeenCalledWith(expect.objectContaining({
    version: 3, target_locations: ['上海'], job_types: ['全职'], remote_preference: 'HYBRID',
  }))
  expect(fetchProfile).toHaveBeenCalledTimes(2)
})

it('从省市树选择新目标城市后保存，同时保留原有地点写法', async () => {
  const wrapper = mountView()
  await flushPromises()
  const tree = wrapper.findComponent({ name: 'ACascader' })
  expect(tree.props('multiple')).toBe(true)
  tree.vm.$emit('update:value', [['上海市', '上海市'], ['江苏省', '南京市']])
  await wrapper.find('[data-testid="save-preference"]').trigger('click')
  await flushPromises()

  expect(savePreference).toHaveBeenCalledWith(expect.objectContaining({
    target_locations: ['上海', '江苏省南京市'], version: 3,
  }))
})

it.each(['北京市', '上海市', '天津市', '重庆市', '南京市'])('实际点击 %s 后保留选中状态，并提交城市与原有地点', async (city) => {
  const profile = fixture()
  profile.preference!.target_locations = ['杭州', '新加坡']
  vi.mocked(fetchProfile).mockResolvedValue(profile)
  const wrapper = mountView(true)
  await flushPromises()
  await wrapper.get('.ant-cascader .ant-select-selector').trigger('mousedown')
  await flushPromises()
  const page = new DOMWrapper(document.body)
  const province = city === '南京市' ? '江苏省' : city
  await page.get(`.ant-cascader-menu:first-child [title="${province}"]`).trigger('click')
  await flushPromises()
  await page.get(`.ant-cascader-menu:nth-child(2) [title="${city}"]`).trigger('click')
  await flushPromises()

  expect(page.get(`.ant-cascader-menu:nth-child(2) [title="${city}"]`).attributes('aria-checked')).toBe('true')
  expect(wrapper.findComponent({ name: 'ACascader' }).props('value')).toContainEqual([province, city])
  await wrapper.get('[data-testid="save-preference"]').trigger('click')
  await flushPromises()
  expect(savePreference).toHaveBeenCalledWith(expect.objectContaining({
    target_locations: ['杭州', '新加坡', `${province}${city}`], version: 3,
  }))
})

it('实际勾选整个省份后保留每个城市，再取消单个城市仅移除该项', async () => {
  const profile = fixture()
  profile.preference!.target_locations = ['上海', '新加坡']
  vi.mocked(fetchProfile).mockResolvedValue(profile)
  const wrapper = mountView(true)
  await flushPromises()
  await wrapper.get('.ant-cascader .ant-select-selector').trigger('mousedown')
  await flushPromises()
  const page = new DOMWrapper(document.body)
  await page.get('.ant-cascader-menu:first-child [title="江苏省"] .ant-cascader-checkbox').trigger('click')
  await flushPromises()
  const cities = CITY_OPTIONS.find((option) => option.value === '江苏省')!.children
  const tree = wrapper.findComponent({ name: 'ACascader' })
  expect(tree.props('value')).toEqual([
    ['上海市', '上海市'], ...cities.map((city) => ['江苏省', city.value]),
  ])
  await page.get('.ant-cascader-menu:first-child [title="江苏省"]').trigger('click')
  await flushPromises()
  await page.get('.ant-cascader-menu:nth-child(2) [title="南京市"]').trigger('click')
  await flushPromises()
  expect(tree.props('value')).not.toContainEqual(['江苏省', '南京市'])
  await wrapper.get('[data-testid="save-preference"]').trigger('click')
  await flushPromises()
  expect(savePreference).toHaveBeenCalledWith(expect.objectContaining({
    target_locations: ['上海', '新加坡', ...cities.filter((city) => city.value !== '南京市').map((city) => `江苏省${city.value}`)],
  }))
})

it('尚未建档时引导去个人资料，不显示偏好表单', async () => {
  vi.mocked(fetchProfile).mockRejectedValueOnce(new ApiError({
    code: 'RESOURCE_NOT_FOUND', message: '个人档案尚未创建。', status: 404,
  }))
  const wrapper = mountView()
  await flushPromises()

  expect(wrapper.find('[data-testid="strategy-needs-profile"]').text()).toContain('请先创建个人档案')
  expect(wrapper.find('[data-testid="strategy-needs-profile"] a').attributes('href')).toBe('/profile')
  expect(wrapper.find('[data-testid="panel-preference"]').exists()).toBe(false)
})

it('加载失败保留请求编号与重试入口', async () => {
  vi.mocked(fetchProfile).mockRejectedValueOnce(new ApiError({
    code: 'NETWORK_ERROR', message: '连接失败。', requestId: 'req-strategy',
  }))
  const wrapper = mountView()
  await flushPromises()

  expect(wrapper.find('[data-testid="strategy-load-error"]').text()).toContain('req-strategy')
  expect(wrapper.find('[data-testid="panel-preference"]').exists()).toBe(false)
  await wrapper.find('[data-testid="strategy-load-error"] button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[data-testid="panel-preference"]').exists()).toBe(true)
})

it('版本冲突时显示提示并重新读取最新档案', async () => {
  vi.mocked(savePreference).mockRejectedValueOnce(new ApiError({
    code: 'CONFLICT', message: '记录已被更新。', status: 409,
    details: [{ field: 'version', reason: '版本已过期。' }],
  }))
  const wrapper = mountView()
  await flushPromises()

  await wrapper.find('[data-testid="save-preference"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('[data-testid="strategy-conflict"]').text()).toContain('记录已被更新')
  expect(fetchProfile).toHaveBeenCalledTimes(2)
})
