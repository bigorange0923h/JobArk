/** @vitest-environment jsdom */
/** 核心事实表单的手动保存边界：草稿不误写、合法字段失焦保存。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { skillsApi, type Profile, type Skill } from '@/shared/api/profile'
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

it('已保存技能只显示名称、关联证据标题和删除按钮，名称点击可编辑', async () => {
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
  expect(card.find('.ant-form-item-label').exists()).toBe(false)
  await card.find('[data-testid="fact-skills-0-name"]').trigger('click')
  expect(card.find('[data-testid="fact-skills-0-name-input"]').exists()).toBe(true)
})
