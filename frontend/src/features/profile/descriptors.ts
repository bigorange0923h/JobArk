/**
 * 事实面板的界面描述符。
 *
 * 现在只剩**语言能力**还走这条描述符驱动的路径（一份表格 + 弹窗 + 统一的冲突处理）。
 * 技能、工作经历、项目经历与教育经历都已由核心表单接管：字段定义在 `profileFormFields.ts`，
 * 渲染在 `ProfileFactSections.vue`，手填与导入共用同一份。这里不再为它们重复声明字段——
 * 同一份字段表写两遍，迟早出现"这边加了成果、那边还停在旧列"的漂移。
 *
 * 证据也不再有自己的面板：一块写着「证据／可核验程度／已验证」的表格容易被读成"系统已核实这些
 * 能力"，而它其实只是来源记录（见 `docs/requirements/v1.md` 与 `docs/architecture.md`）；
 * 证据由导入与本人填写流程自动创建，只在单条事实的「来源与状态」里查看。
 *
 * 未暴露 `sort_order`：后端已为事实表存了该字段，但档案聚合返回时并不按它排序，界面上会表现为
 * "填了顺序却没有效果"。等后端按它排序（或在聚合里显式排序）之后再暴露，避免给出无效操作。
 */

import { languagesApi, type Evidence, type Language, type LanguageInput } from '@/shared/api/profile'

import type { FactDescriptor, FieldOption } from './types'

/** 偏好字段的枚举选项由偏好组件自行定义，见 `PreferencePanel.vue`。 */
export const REMOTE_PREFERENCE_LABELS = {
  ANY: '不限',
  ONSITE: '坐班',
  HYBRID: '混合',
  REMOTE: '远程',
} as const

/**
 * 可被新事实引用的证据选项。
 *
 * 排除已归档的证据：后端对引用已归档证据的写入返回 422，若在这里仍然列出，用户会选中一个
 * 必然失败的值。历史事实仍引用着已归档证据，因此展示时不能过滤，只有新增引用时才排除。
 */
function usableEvidenceOptions(evidences: Evidence[]): FieldOption[] {
  return evidences
    .filter((item) => item.archived_at === null)
    .map((item) => ({ value: item.id, label: item.title }))
}

/** 把证据 id 显示为证据标题，供表格列使用。 */
function evidenceTitle(item: { source_evidence_id: string | null }, evidences: Evidence[]): string {
  if (item.source_evidence_id === null) {
    return '—'
  }
  const found = evidences.find((candidate) => candidate.id === item.source_evidence_id)
  return found === undefined ? '(证据已不可用)' : found.title
}

/** 语言能力面板。 */
export function languageDescriptor(evidences: Evidence[]): FactDescriptor<Language, LanguageInput> {
  return {
    key: 'languages',
    title: '语言能力',
    description: '语言水平属于本人陈述，可直接记录并使用；如需说明依据，可另建证书类证据并在"来源与状态"中关联。',
    rowLabel: (item) => item.language,
    operations: languagesApi,
    fields: [
      { name: 'language', label: '语言', kind: 'text', required: true, maxLength: 64 },
      { name: 'level', label: '水平', kind: 'text', maxLength: 64, placeholder: 'CET-6 / 雅思 7.0' },
      { name: 'note', label: '说明', kind: 'textarea' },
      {
        name: 'source_evidence_id',
        label: '来源证据',
        kind: 'evidence',
        advanced: true,
        options: usableEvidenceOptions(evidences),
        help: '可选。用于说明这条内容来自哪里（简历、证明、本人填写）；留空不影响保存、匹配与简历生成。',
      },
    ],
    columns: [
      { name: 'language', label: '语言' },
      { name: 'level', label: '水平' },
      { name: 'note', label: '说明' },
      { name: 'source_evidence_id', label: '来源证据', format: (item) => evidenceTitle(item, evidences) },
    ],
  }
}
