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
  postings: JobPosting[]
  latest_snapshot: JobSnapshot | null
}

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
