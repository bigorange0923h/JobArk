/**
 * Job 领域 API 类型与请求封装。
 *
 * 手工职位录入只提交用户实际看到的公司信息与原始 JD；解析状态由后端保存，前端不会自行把
 * 文本拆成看似可靠的结构化条件。
 */

import { requestV1 } from './client'
import type { EditableResource } from './types'

export type OpportunityStatus = 'ACTIVE' | 'ARCHIVED'
export type JobSource = 'MANUAL'
export type PostingStatus = 'ACTIVE' | 'UNAVAILABLE'
export type SnapshotParseStatus = 'NOT_REQUESTED' | 'PARSED' | 'FAILED'

export interface JobCompany extends EditableResource {
  name: string
  name_normalized: string
  website_url: string | null
  industry: string | null
  nature_code: string | null
  industry_code: string | null
  location: string | null
}

export interface JobPosting extends EditableResource {
  opportunity_id: string
  source: JobSource
  external_id: string | null
  canonical_url: string | null
  first_seen_at: string
  last_seen_at: string
  page_status: PostingStatus
}

export interface JobSnapshot {
  id: string
  posting_id: string
  content_hash: string
  captured_at: string
  raw_jd: string
  parsed_json: Record<string, unknown> | null
  parse_status: SnapshotParseStatus
  parser_version: string | null
  failure_code: string | null
  created_at: string
}

export interface JobListItem extends EditableResource {
  company_name: string
  title: string
  location: string | null
  employment_type: string | null
  status: OpportunityStatus
  latest_snapshot_id: string | null
  latest_captured_at: string | null
}

export interface JobOpportunity extends EditableResource {
  company: JobCompany
  title: string
  location: string | null
  employment_type: string | null
  status: OpportunityStatus
  notes: string | null
  outsourcing_arrangement: string | null
  postings: JobPosting[]
  latest_snapshot: JobSnapshot | null
}

export type ExclusionKind = 'COMPANY_NATURE' | 'COMPANY_INDUSTRY' | 'COMPANY_NAME' | 'JD_KEYWORD'
export interface ExclusionRule { id: string; kind: ExclusionKind; value: string; enabled: boolean }
export interface ExclusionPolicy { version: number; rules: ExclusionRule[] }
export interface ExclusionEvaluation {
  opportunity_id: string; snapshot_id: string; policy_version: number; company_version: number; opportunity_version: number
  decision: { verdict: 'EXCLUDED' | 'REVIEW' | 'ELIGIBLE'; reasons: { kind: string; rule_id: string | null; text: string; snippet: string | null }[] }
  exception_active: boolean; preparation_allowed: boolean
}
/** 读取与整体保存结构化规则；旧标签不在这里自动转换。 */
export function getExclusionPolicy(): Promise<ExclusionPolicy> { return requestV1('/exclusion-policy') }
export function saveExclusionPolicy(payload: ExclusionPolicy): Promise<ExclusionPolicy> { return requestV1('/exclusion-policy', { init: { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } }) }
/** 预览与登记评估；投递准备必须调用登记接口以重新评估。 */
export function previewExclusion(id: string): Promise<ExclusionEvaluation> { return requestV1(`/jobs/${id}/exclusion`) }
export function recordExclusion(id: string): Promise<ExclusionEvaluation> { return requestV1(`/jobs/${id}/exclusion/evaluations`, { init: { method: 'POST' } }) }
/** 显式确认公司性质、行业或单个岗位安排。 */
export function confirmExclusionFacts(id: string, payload: { company_version: number; opportunity_version: number; nature_code?: string | null; industry_code?: string | null; outsourcing_arrangement?: string | null; confirm: boolean }): Promise<ExclusionEvaluation> { return requestV1(`/jobs/${id}/exclusion-facts`, { init: { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } }) }
/** 记录当前输入限定的单职位例外，原因和确认必填。 */
export function grantExclusionException(id: string, evaluation: ExclusionEvaluation, reason: string): Promise<ExclusionEvaluation> { return requestV1(`/jobs/${id}/exclusion/exception`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ snapshot_id: evaluation.snapshot_id, policy_version: evaluation.policy_version, company_version: evaluation.company_version, opportunity_version: evaluation.opportunity_version, reason, confirm: true }) } }) }

export interface ManualJobCreate {
  company: { name: string; website_url: string | null; industry: string | null; location: string | null }
  title: string
  location: string | null
  employment_type: string | null
  notes: string | null
  canonical_url: string | null
  raw_jd: string
}

/** 读取职位摘要列表。 */
export function listJobs(): Promise<JobListItem[]> {
  return requestV1<JobListItem[]>('/jobs')
}

/** 读取职位详情。 */
export function fetchJob(id: string): Promise<JobOpportunity> { return requestV1(`/jobs/${id}`) }
/** 读取不可变 JD 历史。 */
export function listSnapshots(id: string): Promise<JobSnapshot[]> { return requestV1(`/jobs/${id}/snapshots`) }
/** 按当前版本保存可编辑字段。 */
export function updateJob(id: string, payload: { version: number; title: string; location: string | null; notes: string | null; status: OpportunityStatus }): Promise<JobOpportunity> { return requestV1(`/jobs/${id}`, { init: { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } }) }
/** 为页面保存新快照，原快照始终保留。 */
export function saveSnapshot(id: string, postingId: string, raw_jd: string): Promise<JobSnapshot> { return requestV1(`/jobs/${id}/postings/${postingId}/snapshots`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ raw_jd }) } }) }

/** 原子保存手工职位、页面和首份 JD 快照。 */
export function createManualJob(payload: ManualJobCreate): Promise<JobOpportunity> {
  return requestV1<JobOpportunity>('/jobs', {
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  })
}
