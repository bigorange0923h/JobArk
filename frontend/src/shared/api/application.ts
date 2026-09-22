/** 人工申请记录接口；记录状态不会向外部平台提交。 */
import { requestV1 } from './client'
import type { EditableResource } from './types'

export const statusLabels: Record<string, string> = { SAVED: '已保存', PREPARING: '准备中', READY_TO_APPLY: '待投递', APPLIED: '已投递', CONTACTED: '已联系', INTERVIEWING: '面试中', OFFERED: '收到录用', REJECTED: '被拒绝', WITHDRAWN: '已撤回', CLOSED: '已结束' }
export interface Application extends EditableResource { job_opportunity_id: string; job_snapshot_id: string; resume_version_id: string; attempt_no: number; current_status: string }
export interface ApplicationDetail extends Application { events: { id: string; sequence_no: number; from_status: string | null; to_status: string; occurred_at: string; notes: string | null }[]; allowed_statuses: string[] }
/** 创建新的申请尝试，重复尝试必须显式确认。 */
export function createApplication(payload: { job_opportunity_id: string; job_snapshot_id: string; resume_version_id: string; confirm_repeat: boolean }): Promise<ApplicationDetail> { return requestV1('/applications', { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } }) }
/** 读取申请列表。 */
export function listApplications(): Promise<Application[]> { return requestV1('/applications') }
/** 读取完整时间线。 */
export function fetchApplication(id: string): Promise<ApplicationDetail> { return requestV1(`/applications/${id}`) }
/** 记录人工确认的阶段变化。 */
export function transitionApplication(id: string, payload: { version: number; status: string; confirm_applied: boolean; notes: string | null }): Promise<ApplicationDetail> { return requestV1(`/applications/${id}/events`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } }) }
