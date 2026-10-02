/**
 * 招聘平台内容导入契约。
 *
 * 网址仅供后端识别来源，预览只保存独立候选；正式职位必须通过用户明确确认后写入。
 * 请求不携带登录凭据，也不会由浏览器访问招聘网站或自动重试确认。
 */

import { requestV1 } from './client'
import type { JobSource } from './job'
import type { EditableResource } from './types'

/** 可导入的四个平台；手工录入保留现有独立入口。 */
export type JobImportSource = Exclude<JobSource, 'MANUAL'>
export type JobImportMode = 'HTML' | 'TEXT'

/** 待核对内容；缺失公司与标题用空字符串展示，不能由前端猜测补齐。 */
export interface JobImportFields {
  company_name: string
  title: string
  location: string | null
  raw_jd: string
}

/** 数据库保存的候选及去重目标；平台、页面 ID 与规范网址始终只读。 */
export interface JobImportCandidate extends EditableResource {
  source: JobImportSource
  external_id: string
  canonical_url: string
  status: 'PENDING' | 'CONFIRMED'
  expires_at: string
  extractor_version: string
  fields: JobImportFields
  warnings: string[]
  target_posting_id: string | null
  observed_posting_version: number | null
  confirmed_posting_id: string | null
  confirmed_snapshot_id: string | null
  reviewed_fields: JobImportFields | null
}

/** 用户提供的单个职位页面内容；预览不会访问网址。 */
export interface JobImportPreviewInput {
  url: string
  mode: JobImportMode
  content: string
}

/** 明确确认已核对的候选；来源字段不在可提交范围内。 */
export interface JobImportConfirmInput {
  version: number
  confirm: true
  fields: JobImportFields
}

/** 不可变确认回执；重复确认仍指向当次写入的快照，不返回机会后续变化的聚合内容。 */
export interface JobImportReceipt {
  opportunity_id: string
  posting_id: string
  snapshot_id: string
}

/** 提取并保存独立候选，正式职位保持不变；失败通过统一错误契约反馈。 */
export function previewJobImport(input: JobImportPreviewInput): Promise<JobImportCandidate> {
  return requestV1('/job-imports/preview', {
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) },
  })
}

/** 读取已保存候选；过期候选仍需重新预览才允许确认。 */
export function fetchJobImport(id: string): Promise<JobImportCandidate> {
  return requestV1(`/job-imports/${id}`)
}

/** 原子确认并返回固定页面与快照回执；版本冲突或过期失败不自动重试。 */
export function confirmJobImport(id: string, input: JobImportConfirmInput): Promise<JobImportReceipt> {
  return requestV1(`/job-imports/${id}/confirm`, {
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) },
  })
}
