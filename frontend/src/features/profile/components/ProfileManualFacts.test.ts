/** @vitest-environment jsdom */
/** 核心事实表单的手动保存边界：草稿不误写、合法字段失焦保存。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { projectsApi, skillsApi, type Profile, type Skill } from '@/shared/api/profile'
import ProfileManualFacts from './ProfileManualFacts.vue'

enableAutoUnmount(afterEach)

function profile(skills: Skill[] = []): Profile {
  return {
    id: 'profile-1', version: 1, singleton_key: 'default',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    full_name: '张伟', headline: null, summary: null, email: null, phone: null, city: null,
    links: [], evidences: [], skills, experiences: [], projects: [], educations: [], languages: [], preference: null,
  }
}

it('新增技能先留在本地，失焦后自动保存且无改动不重复写入', async () => {
  const create = vi.spyOn(skillsApi, 'create').mockResolvedValue({
    id: 'skill-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    name: 'Python', name_normalized: 'python', category: null, proficiency: null,
    years_of_experience: null, source_evidence_id: null, claim_status: 'UNVERIFIED',
  })
  try {
    const wrapper = mount(ProfileManualFacts, { props: { profile: profile() } })
    await wrapper.find('[data-testid="add-item-skills"]').trigger('click')
    await wrapper.find('[data-testid="fact-skills-0-name"]').trigger('click')
    await wrapper.find('[data-testid="fact-skills-0-name-input"]').setValue('Python')
    expect(create).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="fact-skills-0-name-input"]').trigger('blur')
    await flushPromises()
    expect(create).toHaveBeenCalledOnce()
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Python' }))
    await wrapper.find('[data-testid="fact-skills-0-name"]').trigger('click')
    await wrapper.find('[data-testid="fact-skills-0-name-input"]').trigger('blur')
    await flushPromises()
    expect(create).toHaveBeenCalledOnce()
  } finally {
    create.mockRestore()
  }
})

it('建档前可填事实草稿，姓名建档并刷新后才保存', async () => {
  const create = vi.spyOn(skillsApi, 'create').mockResolvedValue({
    id: 'skill-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    name: 'Python', name_normalized: 'python', category: null, proficiency: null,
    years_of_experience: null, source_evidence_id: null, claim_status: 'UNVERIFIED',
  })
  try {
    const wrapper = mount(ProfileManualFacts, { props: { profile: null } })
    await wrapper.find('[data-testid="add-item-skills"]').trigger('click')
    await wrapper.find('[data-testid="fact-skills-0-name"]').trigger('click')
    await wrapper.find('[data-testid="fact-skills-0-name-input"]').setValue('Python')
    await wrapper.find('[data-testid="fact-skills-0-name-input"]').trigger('blur')
    expect(create).not.toHaveBeenCalled()
    await wrapper.setProps({ profile: profile() })
    await flushPromises()
    expect(create).toHaveBeenCalledOnce()
  } finally {
    create.mockRestore()
  }
})

it('工作经历的时间只到月：选择器只选月份，写入值仍是完整日期', async () => {
  const wrapper = mount(ProfileManualFacts, { props: { profile: profile() } })
  await wrapper.find('[data-testid="add-item-experiences"]').trigger('click')

  const pickers = wrapper.findAllComponents({ name: 'ADatePicker' })
  // 只有工作经历的开始/结束时间变成月份选择器；值格式仍是完整日期（日固定为 1），后端契约不变。
  expect(pickers).toHaveLength(2)
  expect(pickers[0]?.props('picker')).toBe('month')
  expect(pickers[1]?.props('picker')).toBe('month')
  expect(pickers[0]?.props('valueFormat')).toBe('YYYY-MM-DD')
})

it('项目可记录成果并关联已有工作经历，时间只到月', async () => {
  const create = vi.spyOn(projectsApi, 'create').mockResolvedValue({
    id: 'project-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    name: '订单系统重构', role: null, description: null, achievements: '把下单耗时降低 30%',
    tech_stack: [], url: null, start_date: '2022-05-01', end_date: null, experience_id: 'experience-1',
    source_evidence_id: null,
  })
  try {
    const data = profile()
    data.experiences = [{
      id: 'experience-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      company: '某公司', title: '后端工程师', location: null, start_date: '2022-03-01', end_date: null,
      responsibilities: null, achievements: null, source_evidence_id: null,
    }]
    const wrapper = mount(ProfileManualFacts, { props: { profile: data } })
    await wrapper.find('[data-testid="add-item-projects"]').trigger('click')

    // 项目时间与工作经历同口径：都只选到月（上面那段经历自己也有两个时间字段）。
    const pickers = wrapper.findAllComponents({ name: 'ADatePicker' })
    expect(pickers).toHaveLength(4)
    expect(pickers.every((picker) => picker.props('picker') === 'month')).toBe(true)

    // 「所属工作经历」的选项来自档案里已有的经历，标签带月份区间便于区分同一公司的多段任职。
    const link = wrapper.findAllComponents({ name: 'ASelect' })[0]
    expect(link?.props('options')).toEqual([{ value: 'experience-1', label: '某公司 · 后端工程师（2022-03 至今）' }])

    await wrapper.find('[data-testid="fact-projects-0-name"]').setValue('订单系统重构')
    await wrapper.find('[data-testid="fact-projects-0-achievements"]').setValue('把下单耗时降低 30%')

    // 选一项要走真实交互：在 AntDV 组件实例上 emit 不会触发父组件监听器。
    const selector = '[data-testid="fact-projects-0-experience_id"] .ant-select-selector'
    await wrapper.find(selector).trigger('mousedown')
    await wrapper.find(selector).trigger('click')
    await nextTick()
    const option = Array.from(document.querySelectorAll('.ant-select-item-option')).find((node) =>
      node.textContent?.includes('某公司'),
    )
    expect(option).toBeDefined()
    option?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(create).toHaveBeenCalledOnce()
    expect(create).toHaveBeenCalledWith(expect.objectContaining({
      name: '订单系统重构',
      achievements: '把下单耗时降低 30%',
      experience_id: 'experience-1',
    }))
  } finally {
    create.mockRestore()
  }
})

it('已保存技能显示名称、可编辑分类、来源和删除按钮', async () => {
  const data = profile([{
    id: 'skill-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    name: 'Python', name_normalized: 'python', category: null, proficiency: null,
    years_of_experience: null, source_evidence_id: 'evidence-1', claim_status: 'UNVERIFIED',
  }])
  data.evidences = [{
    id: 'evidence-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    source_type: 'RESUME_DOCUMENT', title: '导入的简历', content: null, source_url: null,
    source_hash: null, verification_status: 'UNVERIFIED', archived_at: null,
  }]
  const wrapper = mount(ProfileManualFacts, { props: { profile: data } })
  const card = wrapper.find('[data-testid="form-item-skills-0"]')
  expect(card.find('[data-testid="fact-skills-0-name"]').text()).toBe('Python')
  expect(card.find('.skill-source').text()).toContain('来源：导入的简历')
  expect(card.find('[data-testid="remove-item-skills-0"]').exists()).toBe(true)
  expect(card.find('.ant-form-item-label').text()).toContain('技能分类')
  await card.find('[data-testid="fact-skills-0-name"]').trigger('click')
  expect(card.find('[data-testid="fact-skills-0-name-input"]').exists()).toBe(true)
})

it('修改已保存技能分类会自动保存，并保留技能来源证据', async () => {
  const update = vi.spyOn(skillsApi, 'update').mockResolvedValue({
    id: 'skill-1', version: 2, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
    name: 'Python', name_normalized: 'python', category: 'AI 应用', proficiency: null,
    years_of_experience: null, source_evidence_id: 'evidence-1', claim_status: 'UNVERIFIED',
  })
  try {
    const data = profile([{
      id: 'skill-1', version: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      name: 'Python', name_normalized: 'python', category: '编程语言', proficiency: null,
      years_of_experience: null, source_evidence_id: 'evidence-1', claim_status: 'UNVERIFIED',
    }])
    const wrapper = mount(ProfileManualFacts, { props: { profile: data } })
    const selector = '[data-testid="fact-skills-0-category"] .ant-select-selector'
    await wrapper.find(selector).trigger('mousedown')
    await wrapper.find(selector).trigger('click')
    await nextTick()
    const option = Array.from(document.querySelectorAll('.ant-select-item-option')).find((node) =>
      node.textContent?.includes('AI 应用'),
    )
    expect(option).toBeDefined()
    option?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(update).toHaveBeenCalledWith('skill-1', expect.objectContaining({
      category: 'AI 应用', source_evidence_id: 'evidence-1', version: 1,
    }))
  } finally {
    update.mockRestore()
  }
})
