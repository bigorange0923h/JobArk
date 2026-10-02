/** @vitest-environment jsdom */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { notification } from 'ant-design-vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { confirmJobImport, previewJobImport, type JobImportCandidate, type JobImportReceipt } from '@/shared/api/jobImport'

import JobImportPanel from './JobImportPanel.vue'

vi.mock('@/shared/api/jobImport', () => ({ previewJobImport: vi.fn(), confirmJobImport: vi.fn() }))

const notice = vi.spyOn(notification, 'error')
const PAGE_URL = 'https://www.linkedin.com/jobs/view/123456789/'

/** 候选来源固定；测试只修改用于不同业务路径的字段。 */
function candidate(patch: Partial<JobImportCandidate> = {}): JobImportCandidate {
  return {
    id: 'candidate-1', version: 3, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    source: 'LINKEDIN', external_id: '123456789', canonical_url: PAGE_URL, status: 'PENDING',
    expires_at: '2099-10-03T00:00:00Z', extractor_version: 'local-1',
    fields: { company_name: '', title: '', location: null, raw_jd: '来自页面的真实职位正文' },
    warnings: ['正文模式需要自行补充公司和职位。'], target_posting_id: null, observed_posting_version: null,
    confirmed_posting_id: null, confirmed_snapshot_id: null, reviewed_fields: null, ...patch,
  }
}

/** 从实际入口开始操作，确保打开面板本身不触发任何业务请求。 */
async function openPanel(): Promise<VueWrapper> {
  const wrapper = mount(JobImportPanel)
  await wrapper.find('[data-testid="open-job-import"]').trigger('click')
  return wrapper
}

/** 只提供预览输入；填写内容不会隐含确认写入。 */
async function preview(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-testid="job-import-url"]').setValue(` ${PAGE_URL} `)
  await wrapper.find('[data-testid="job-import-source-content"]').setValue(' 真实页面正文\n')
  await wrapper.find('[data-testid="preview-job-import"]').trigger('click')
  await flushPromises()
}

/** 补齐必要字段，不代替用户点击正式确认。 */
async function fillFields(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-testid="job-import-company"]').setValue(' 示例科技 ')
  await wrapper.find('[data-testid="job-import-title"]').setValue(' 后端工程师 ')
  await wrapper.find('[data-testid="job-import-location"]').setValue(' 上海 ')
}

beforeEach(() => {
  vi.clearAllMocks()
  notice.mockImplementation(() => undefined)
  vi.mocked(previewJobImport).mockResolvedValue(candidate())
  vi.mocked(confirmJobImport).mockResolvedValue({ opportunity_id: 'job-1', posting_id: 'posting-1', snapshot_id: 'snapshot-1' })
})

enableAutoUnmount(afterEach)

describe('JobImportPanel', () => {
  it('说明内容导入范围，初始打开不发请求，网址与内容齐全才能预览', async () => {
    const wrapper = await openPanel()
    expect(wrapper.text()).toContain('不会自动访问网站')
    expect(wrapper.text()).toContain('内容不会发送给 AI')
    expect(previewJobImport).not.toHaveBeenCalled()
    expect(confirmJobImport).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="preview-job-import"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="job-import-url"]').setValue(PAGE_URL)
    expect(wrapper.find('[data-testid="preview-job-import"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="job-import-source-content"]').setValue('正文')
    expect(wrapper.find('[data-testid="preview-job-import"]').attributes('disabled')).toBeUndefined()
  })

  it('预览只调用候选接口，缺失公司或职位时禁止正式确认', async () => {
    const wrapper = await openPanel()
    await preview(wrapper)
    expect(previewJobImport).toHaveBeenCalledWith({ url: PAGE_URL, mode: 'TEXT', content: ' 真实页面正文\n' })
    expect(confirmJobImport).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('领英')
    expect(wrapper.text()).toContain('新建职位')
    expect(wrapper.text()).toContain(PAGE_URL)
    expect(wrapper.find('[data-testid="job-import-warnings"]').text()).toContain('自行补充公司和职位')
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="job-import-company"]').setValue('公司')
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="job-import-title"]').setValue('职位')
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeUndefined()
    await wrapper.find('[data-testid="job-import-jd"]').setValue(' ')
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeDefined()
  })

  it('人工修正后只在明确点击确认时提交版本与字段，成功后发出保存事件', async () => {
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    await wrapper.find('[data-testid="job-import-jd"]').setValue(' 修正后的真实 JD\n')
    expect(confirmJobImport).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    await flushPromises()
    expect(confirmJobImport).toHaveBeenCalledWith('candidate-1', {
      version: 3, confirm: true,
      fields: { company_name: '示例科技', title: '后端工程师', location: '上海', raw_jd: ' 修正后的真实 JD\n' },
    })
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(wrapper.find('[data-testid="job-import-result"]').text()).toContain('已确认导入')
    await wrapper.find('[data-testid="open-job-import"]').trigger('click')
    expect((wrapper.find('[data-testid="job-import-url"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.find('[data-testid="job-import-review"]').exists()).toBe(false)
  })

  it('取消保留原输入和已编辑候选，重新打开可继续核对', async () => {
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    await wrapper.find('[data-testid="cancel-job-import"]').trigger('click')
    expect(wrapper.find('[data-testid="job-import-content"]').exists()).toBe(false)
    expect(confirmJobImport).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="open-job-import"]').trigger('click')
    expect((wrapper.find('[data-testid="job-import-source-content"]').element as HTMLTextAreaElement).value).toBe(' 真实页面正文\n')
    expect((wrapper.find('[data-testid="job-import-company"]').element as HTMLInputElement).value).toBe(' 示例科技 ')
  })

  it('预览失败保留输入并就地显示可修改的原因', async () => {
    vi.mocked(previewJobImport).mockRejectedValueOnce(new ApiError({ status: 422, code: 'VALIDATION_ERROR', message: '不支持该详情链接。', details: [{ field: 'url', reason: '请使用单个职位详情页。' }] }))
    const wrapper = await openPanel()
    await preview(wrapper)
    expect(wrapper.find('[data-testid="job-import-error"]').text()).toContain('不支持该详情链接')
    expect(wrapper.text()).toContain('请使用单个职位详情页')
    expect((wrapper.find('[data-testid="job-import-url"]').element as HTMLInputElement).value).toBe(` ${PAGE_URL} `)
    expect((wrapper.find('[data-testid="job-import-source-content"]').element as HTMLTextAreaElement).value).toBe(' 真实页面正文\n')
    expect(notice).not.toHaveBeenCalled()
  })

  it('确认字段错误保留人工修订，字段原因内联展示', async () => {
    vi.mocked(confirmJobImport).mockRejectedValueOnce(new ApiError({ status: 422, code: 'VALIDATION_ERROR', message: '请核对 JD。', details: [{ field: 'fields.raw_jd', reason: 'JD 正文无效。' }] }))
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    await wrapper.find('[data-testid="job-import-jd"]').setValue('人工核对正文')
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="job-import-error"]').text()).toContain('请核对 JD')
    expect(wrapper.text()).toContain('JD 正文无效')
    expect((wrapper.find('[data-testid="job-import-jd"]').element as HTMLTextAreaElement).value).toBe('人工核对正文')
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(notice).not.toHaveBeenCalled()
  })

  it.each(['IMPORT_EXPIRED', 'VERSION_CONFLICT'])('409 %s 保留输入和核对草稿，要求重新预览', async (code) => {
    vi.mocked(confirmJobImport).mockRejectedValueOnce(new ApiError({ status: 409, code, message: '候选已过期或页面已变化。', requestId: 'req-conflict' }))
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="job-import-error"]').text()).toContain('req-conflict')
    expect(wrapper.find('[data-testid="job-import-repreview"]').text()).toContain('重新预览')
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeDefined()
    expect((wrapper.find('[data-testid="job-import-company"]').element as HTMLInputElement).value).toBe(' 示例科技 ')
    expect((wrapper.find('[data-testid="job-import-source-content"]').element as HTMLTextAreaElement).value).toBe(' 真实页面正文\n')
    expect(notice).not.toHaveBeenCalled()
  })

  it('网络确认失败走轻通知，草稿可保留并显式重试', async () => {
    vi.mocked(confirmJobImport).mockRejectedValueOnce(new ApiError({ code: 'NETWORK_ERROR', message: '无法连接职位导入服务。' }))
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    await flushPromises()
    expect(notice).toHaveBeenCalledTimes(1)
    expect(notice).toHaveBeenCalledWith(expect.objectContaining({ message: '确认导入职位失败' }))
    expect(wrapper.find('[data-testid="job-import-error"]').exists()).toBe(false)
    expect((wrapper.find('[data-testid="job-import-company"]').element as HTMLInputElement).value).toBe(' 示例科技 ')
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeUndefined()
  })

  it.each(['job-import-url', 'job-import-source-content'])('编辑原输入 %s 后旧候选不能确认', async (testId) => {
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    await wrapper.find(`[data-testid="${testId}"]`).setValue(testId === 'job-import-url' ? 'https://www.linkedin.com/jobs/view/222222/' : '新的页面正文')
    expect(wrapper.find('[data-testid="job-import-repreview"]').text()).toContain('旧输入')
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    expect(confirmJobImport).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeDefined()
  })

  it('修改格式会使旧候选失效，HTML 仅作为请求输入而不执行', async () => {
    const wrapper = await openPanel()
    await preview(wrapper)
    await fillFields(wrapper)
    wrapper.findComponent({ name: 'ARadioGroup' }).vm.$emit('update:value', 'HTML')
    await wrapper.find('[data-testid="job-import-source-content"]').setValue('<script>alert(1)</script><div>JD 内容</div>')
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('[data-testid="confirm-job-import"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="preview-job-import"]').trigger('click')
    await flushPromises()
    expect(previewJobImport).toHaveBeenLastCalledWith({ url: PAGE_URL, mode: 'HTML', content: '<script>alert(1)</script><div>JD 内容</div>' })
  })

  it('已有页面禁止改公司、标题和地点，确认只提交现有元数据与修订 JD', async () => {
    vi.mocked(previewJobImport).mockResolvedValueOnce(candidate({ target_posting_id: 'posting-1', observed_posting_version: 4, fields: { company_name: '原公司', title: '人工维护职位', location: '深圳', raw_jd: '旧 JD' } }))
    const wrapper = await openPanel()
    await preview(wrapper)
    expect(wrapper.find('[data-testid="job-import-existing-notice"]').text()).toContain('只更新 JD')
    for (const id of ['company', 'title', 'location']) {
      expect(wrapper.find(`[data-testid="job-import-${id}"]`).attributes('disabled')).toBeDefined()
    }
    // 即使组件的更新事件被意外触发，确认仍从原始候选取元数据。
    const company = wrapper.findAllComponents({ name: 'AInput' }).find((component) => component.attributes('data-testid') === 'job-import-company')
    expect(company).toBeDefined()
    company?.vm.$emit('update:value', '误改公司')
    await wrapper.find('[data-testid="job-import-jd"]').setValue('新的 JD')
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    await flushPromises()
    expect(confirmJobImport).toHaveBeenCalledWith('candidate-1', { version: 3, confirm: true, fields: { company_name: '原公司', title: '人工维护职位', location: '深圳', raw_jd: '新的 JD' } })
    expect(wrapper.find('[data-testid="job-import-result"]').text()).toContain('已确认更新 JD')
  })

  it('预览与确认各自保持忙碌并防止重复点击', async () => {
    let finishPreview: ((value: JobImportCandidate) => void) | undefined
    vi.mocked(previewJobImport).mockImplementationOnce(() => new Promise((resolve) => { finishPreview = resolve }))
    const wrapper = await openPanel()
    await preview(wrapper)
    await wrapper.find('[data-testid="preview-job-import"]').trigger('click')
    expect(previewJobImport).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="preview-job-import"]').attributes('disabled')).toBeDefined()
    finishPreview?.(candidate())
    await flushPromises()
    await fillFields(wrapper)
    let finishConfirm: ((value: JobImportReceipt) => void) | undefined
    vi.mocked(confirmJobImport).mockImplementationOnce(() => new Promise((resolve) => { finishConfirm = resolve }))
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    await wrapper.find('[data-testid="confirm-job-import"]').trigger('click')
    expect(confirmJobImport).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="cancel-job-import"]').attributes('disabled')).toBeDefined()
    finishConfirm?.({ opportunity_id: 'job-1', posting_id: 'posting-1', snapshot_id: 'snapshot-1' })
    await flushPromises()
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('读取本地 HTML 后切换格式与正文，不自动发请求', async () => {
    const wrapper = await openPanel()
    const node = wrapper.find('[data-testid="job-import-file"]')
    Object.defineProperty(node.element, 'files', { value: [new File(['<div>本地 JD</div>'], 'job.html', { type: 'text/html' })], configurable: true })
    await node.trigger('change')
    await vi.waitFor(() => expect((wrapper.find('[data-testid="job-import-source-content"]').element as HTMLTextAreaElement).value).toBe('<div>本地 JD</div>'))
    expect(wrapper.findComponent({ name: 'ARadioGroup' }).props('value')).toBe('HTML')
    expect(previewJobImport).not.toHaveBeenCalled()
    expect(confirmJobImport).not.toHaveBeenCalled()
  })

  it('超过 1 MB 或非 HTML 的文件不替换原输入', async () => {
    const wrapper = await openPanel()
    await wrapper.find('[data-testid="job-import-source-content"]').setValue('原输入')
    const node = wrapper.find('[data-testid="job-import-file"]')
    for (const file of [new File(['非 HTML'], 'job.txt'), new File(['x'.repeat(1024 * 1024 + 1)], 'job.html')]) {
      Object.defineProperty(node.element, 'files', { value: [file], configurable: true })
      await node.trigger('change')
      expect(wrapper.find('[data-testid="job-import-error"]').text()).toContain('不超过 1 MB')
      expect((wrapper.find('[data-testid="job-import-source-content"]').element as HTMLTextAreaElement).value).toBe('原输入')
    }
    expect(previewJobImport).not.toHaveBeenCalled()
  })
})
