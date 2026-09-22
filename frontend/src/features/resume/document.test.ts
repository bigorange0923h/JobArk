/**
 * 简历文档与模块设置的纯逻辑测试。
 *
 * 覆盖的是一旦失效就会造成"用户看到的与库里的不一致"的规则：
 *
 * - `section_order` 始终是六个模块的完整排列：顺序算法不能丢项或产生重复；
 * - 空模块不参与渲染，但**不**因此被写进 `hidden_sections`：暂时的空与用户的显式隐藏必须可区分，
 *   否则"我明明没关掉这个模块"会变成无法解释的状态；
 * - 从档案生成文档时逐条带上 `source_fact_id`：溯源在生成时就建立，而不是事后补。
 */

import { describe, expect, it } from 'vitest'

import type { Profile } from '@/shared/api/profile'
import type { ResumeDocument, ResumeSection } from '@/shared/api/resume'

import {
  SECTION_ORDER_DEFAULT,
  createBlankDocument,
  createDocumentFromProfile,
  isSectionEmpty,
  moveSection,
  renderedSections,
  setSectionHidden,
} from './document'

/** 构造一份档案，只覆盖用例关心的部分。 */
function stubProfile(overrides: Partial<Profile> = {}): Profile {
  return {
    id: 'profile-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    singleton_key: 'default',
    full_name: '张伟',
    headline: '后端工程师',
    summary: '5 年后端开发经验。',
    email: 'zhang@example.com',
    phone: '13800000000',
    city: '上海',
    links: [{ label: 'GitHub', url: 'https://github.com/example' }],
    evidences: [],
    skills: [
      {
        id: 'skill-1',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        version: 1,
        name: 'Python',
        name_normalized: 'python',
        category: '编程语言',
        proficiency: 'ADVANCED',
        years_of_experience: '5',
        source_evidence_id: null,
        claim_status: 'UNVERIFIED',
      },
    ],
    experiences: [
      {
        id: 'exp-1',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        version: 1,
        company: '某公司',
        title: '后端工程师',
        location: '上海',
        start_date: '2022-03-01',
        end_date: null,
        responsibilities: '负责订单系统',
        achievements: '把下单耗时降低 30%',
        source_evidence_id: null,
      },
    ],
    projects: [],
    educations: [],
    languages: [],
    preference: null,
    ...overrides,
  }
}

/** 构造一份用于渲染用例的文档：只有简介与技能有内容。 */
function documentWithSections(): ResumeDocument {
  return {
    ...createBlankDocument(),
    summary: { text: '有内容', source_fact_id: null },
    skills: [{ source_fact_id: null, name: 'Python', category: null, proficiency: null }],
  }
}

describe('createBlankDocument', () => {
  it('给出六项完整排列且没有隐藏模块', () => {
    const document = createBlankDocument()

    expect(document.section_order).toEqual([...SECTION_ORDER_DEFAULT])
    expect([...document.section_order].sort()).toEqual([...SECTION_ORDER_DEFAULT].sort())
    expect(document.hidden_sections).toEqual([])
    expect(document.summary).toBeNull()
    expect(document.experiences).toEqual([])
  })
})

describe('isSectionEmpty', () => {
  it('简介为空、空白或缺失时都算空', () => {
    const document = createBlankDocument()

    expect(isSectionEmpty({ ...document, summary: null }, 'SUMMARY')).toBe(true)
    expect(isSectionEmpty({ ...document, summary: { text: '   ', source_fact_id: null } }, 'SUMMARY')).toBe(true)
    expect(isSectionEmpty({ ...document, summary: { text: '有内容', source_fact_id: null } }, 'SUMMARY')).toBe(false)
  })

  it('列表模块没有条目时算空，有任意条目就不算空', () => {
    const document = createBlankDocument()

    expect(isSectionEmpty(document, 'EXPERIENCES')).toBe(true)
    expect(
      isSectionEmpty(
        {
          ...document,
          experiences: [
            {
              source_fact_id: null,
              company: '某公司',
              title: '后端工程师',
              location: null,
              start_date: null,
              end_date: null,
              highlights: [],
            },
          ],
        },
        'EXPERIENCES',
      ),
    ).toBe(false)
  })
})

describe('renderedSections', () => {
  it('只返回有内容且未被隐藏的模块，顺序遵循 section_order', () => {
    const document = documentWithSections()

    expect(renderedSections(document)).toEqual(['SUMMARY', 'SKILLS'])
  })

  it('被显式隐藏的模块即使有内容也不渲染', () => {
    const document: ResumeDocument = {
      ...documentWithSections(),
      hidden_sections: ['SKILLS'],
    }

    expect(renderedSections(document)).toEqual(['SUMMARY'])
  })

  it('空模块不渲染，但不因此被写进 hidden_sections', () => {
    const document = documentWithSections()
    const hiddenBefore = [...document.hidden_sections]

    const rendered = renderedSections(document)

    expect(rendered).not.toContain('PROJECTS')
    expect(document.hidden_sections).toEqual(hiddenBefore)
    expect(document.hidden_sections).not.toContain('PROJECTS')
  })

  it('顺序调整后渲染顺序随之改变', () => {
    // 每次只与前一项交换，因此把技能移到简介前面需要连续上移三次（经过项目、经历两格）。
    let order: ResumeSection[] = [...SECTION_ORDER_DEFAULT]
    for (let step = 0; step < 3; step += 1) {
      order = moveSection(order, 'SKILLS', 'up')
    }

    expect(renderedSections({ ...documentWithSections(), section_order: order })).toEqual(['SKILLS', 'SUMMARY'])
  })
})

describe('moveSection', () => {
  it('上移与相邻的前一项交换位置', () => {
    const moved = moveSection(SECTION_ORDER_DEFAULT, 'EXPERIENCES', 'up')

    expect(moved.slice(0, 2)).toEqual(['EXPERIENCES', 'SUMMARY'])
    expect(moved).toHaveLength(SECTION_ORDER_DEFAULT.length)
  })

  it('下移与相邻的后一项交换位置', () => {
    const moved = moveSection(SECTION_ORDER_DEFAULT, 'SUMMARY', 'down')

    expect(moved.slice(0, 2)).toEqual(['EXPERIENCES', 'SUMMARY'])
  })

  it('首项上移与末项下移都保持原排列不变', () => {
    expect(moveSection(SECTION_ORDER_DEFAULT, 'SUMMARY', 'up')).toEqual([...SECTION_ORDER_DEFAULT])
    expect(moveSection(SECTION_ORDER_DEFAULT, 'LANGUAGES', 'down')).toEqual([...SECTION_ORDER_DEFAULT])
  })

  it('任何一步移动的结果仍是六项完整排列，且不修改入参', () => {
    const original = [...SECTION_ORDER_DEFAULT]

    for (const section of SECTION_ORDER_DEFAULT) {
      for (const direction of ['up', 'down'] as const) {
        const moved = moveSection(original, section, direction)
        expect([...moved].sort()).toEqual([...SECTION_ORDER_DEFAULT].sort())
      }
    }
    expect(original).toEqual([...SECTION_ORDER_DEFAULT])
  })
})

describe('setSectionHidden', () => {
  it('关闭显示时加入隐藏列表，重新打开时移除', () => {
    const hidden = setSectionHidden([], 'SKILLS', true)

    expect(hidden).toEqual(['SKILLS'])
    expect(setSectionHidden(hidden, 'SKILLS', false)).toEqual([])
  })

  it('重复关闭不产生重复项', () => {
    const hidden = setSectionHidden(setSectionHidden([], 'SKILLS', true), 'SKILLS', true)

    expect(hidden).toEqual(['SKILLS'])
  })

  it('打开一个本就未隐藏的模块不会改动列表', () => {
    expect(setSectionHidden(['SKILLS'], 'PROJECTS', false)).toEqual(['SKILLS'])
  })
})

describe('createDocumentFromProfile', () => {
  it('头部与联系方式取自档案', () => {
    const document = createDocumentFromProfile(stubProfile())

    expect(document.basics.full_name).toBe('张伟')
    expect(document.basics.headline).toBe('后端工程师')
    expect(document.basics.city).toBe('上海')
    expect(document.basics.links).toEqual([{ label: 'GitHub', url: 'https://github.com/example' }])
    expect(document.contact).toEqual({ email: 'zhang@example.com', phone: '13800000000' })
    expect(document.summary?.text).toBe('5 年后端开发经验。')
  })

  it('逐条带上来源事实主键，使内容可追溯到档案', () => {
    const document = createDocumentFromProfile(stubProfile())

    expect(document.skills).toHaveLength(1)
    expect(document.skills[0]?.source_fact_id).toBe('skill-1')
    expect(document.skills[0]?.name).toBe('Python')
    expect(document.experiences[0]?.source_fact_id).toBe('exp-1')
    expect(document.experiences[0]?.company).toBe('某公司')
  })

  it('档案里没有的模块生成空列表，而不是省略字段', () => {
    const document = createDocumentFromProfile(stubProfile())

    expect(document.projects).toEqual([])
    expect(document.educations).toEqual([])
    expect(document.languages).toEqual([])
    expect(document.section_order).toEqual([...SECTION_ORDER_DEFAULT])
    expect(document.hidden_sections).toEqual([])
  })

  it('档案没有简介时简介留空，不写入空文本块', () => {
    const document = createDocumentFromProfile(stubProfile({ summary: null }))

    expect(document.summary).toBeNull()
  })

  it('把档案里分段的职责与成果拆成要点，丢弃空行', () => {
    const profile = stubProfile()
    const experience = profile.experiences[0]
    if (experience === undefined) {
      throw new Error('测试夹具缺少工作经历。')
    }

    const document = createDocumentFromProfile(
      stubProfile({
        experiences: [{ ...experience, responsibilities: '第一行\n\n第二行  ', achievements: '成果一' }],
      }),
    )

    expect(document.experiences[0]?.highlights).toEqual(['第一行', '第二行', '成果一'])
  })

  it('教育、语言与项目的关键字段逐项映射', () => {
    const profile = stubProfile({
      educations: [
        {
          id: 'edu-1',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          version: 1,
          school: '某大学',
          major: '计算机',
          degree: '本科',
          start_date: '2016-09-01',
          end_date: '2020-06-30',
          source_evidence_id: null,
        },
      ],
      languages: [
        {
          id: 'lang-1',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          version: 1,
          language: '英语',
          level: 'CET-6',
          note: null,
          source_evidence_id: null,
        },
      ],
      projects: [
        {
          id: 'proj-1',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          version: 1,
          name: 'JobArk',
          role: '独立开发',
          description: '求职工作台',
          tech_stack: ['Vue', 'FastAPI'],
          url: null,
          start_date: null,
          end_date: null,
          source_evidence_id: null,
        },
      ],
    })

    const document = createDocumentFromProfile(profile)

    expect(document.educations[0]).toEqual({
      source_fact_id: 'edu-1',
      school: '某大学',
      major: '计算机',
      degree: '本科',
      start_date: '2016-09-01',
      end_date: '2020-06-30',
    })
    expect(document.languages[0]).toEqual({ source_fact_id: 'lang-1', language: '英语', level: 'CET-6' })
    expect(document.projects[0]).toEqual({
      source_fact_id: 'proj-1',
      name: 'JobArk',
      role: '独立开发',
      description: '求职工作台',
      tech_stack: ['Vue', 'FastAPI'],
      url: null,
    })
  })
})
