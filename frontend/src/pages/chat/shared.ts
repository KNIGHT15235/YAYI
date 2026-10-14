
import { PageTransportKey } from '@/utils'
import type { ResearchProfileId } from '@/configs/research'

export type ChatEnterData = {
  message: string
  attachmentIds?: string[]
  profileId: ResearchProfileId
  sessionId: string
}

export function mergeCharts<T extends { id?: string }>(existing: T[] = [], incoming: T[] = []): T[] {
  return Array.from(new Map([...existing, ...incoming].map(chart => [chart.id || JSON.stringify(chart), chart])).values())
}

export function upsertResearchStep<T extends { type: string }>(steps: T[], incoming: T): T[] {
  return steps.some(step => step.type === incoming.type)
    ? steps.map(step => step.type === incoming.type ? { ...step, ...incoming } : step)
    : [...steps, incoming]
}

export function completeSupplementarySearch<T extends { type: string; status: string; subtitle?: string }>(
  steps: T[], nextPhase: unknown,
): T[] {
  // The executor emits the next Analysis phase only after durably saving the
  // completed supplementary search. Scout's searching event alone is earlier.
  if (nextPhase !== 'analyzing' || !steps.some(step => step.type === 're_researching' && step.status === 'running')) return steps
  return steps.map(step => step.type === 're_researching' && step.status === 'running'
    ? { ...step, status: 'completed', subtitle: '' } : step)
}

export function revisionPresentation(changesCount: unknown): string {
  return typeof changesCount === 'number' && Number.isInteger(changesCount) && changesCount >= 0
    ? `📝 修订完成，共 ${changesCount} 处修改`
    : '📝 修订阶段结束，等待复核'
}

type QualityReview = {
  quality_score?: unknown
  quality_review_status?: string
  quality_review_note?: string
  verdict?: string
  review_verdict?: string
  outcome?: string
  research_outcome?: string
  stop_reason?: string
  passed?: boolean
  summary?: string
}

export function reviewPresentation(review: QualityReview) {
  const score = review.quality_score
  const verdict = review.review_verdict || review.verdict
  const outcome = review.outcome || review.research_outcome
  const unconfirmed = review.quality_review_status === 'unconfirmed' || ['unconfirmed', 'not_reviewed'].includes(verdict || '')
    || typeof score !== 'number' || !Number.isFinite(score) || score < 1 || score > 10
  // A numeric score is not an approval. Legacy records without a verdict stay conservative.
  const passed = !unconfirmed && (verdict ? verdict === 'pass'
    : typeof review.passed === 'boolean' ? review.passed : outcome === 'passed')
  return {
    unconfirmed,
    passed,
    text: unconfirmed
      ? `⚠️ 质量审核待确认\n${review.quality_review_note || review.summary || '未取得有效评分，请人工核对来源与结论。'}`
      : `🔍 审核结果: 质量评分 ${score}/10\n${passed ? '✅ 审核通过' : '⚠️ 需要修订'}`,
  }
}

export function withQualityReviewNotice(report: string, review?: QualityReview) {
  if (!review || reviewPresentation(review).passed) return report
  if (!review.quality_review_status && review.quality_score === undefined && !review.review_verdict && !review.outcome && !review.research_outcome) return report
  // The backend embeds this summary in exported reports too; do not duplicate it in the UI.
  if (report.includes('<!-- research-quality-summary -->')) return report
  const label = reviewPresentation(review).unconfirmed ? '质量审核待确认' : '审核未通过 / 存在未解决问题'
  const notice = `> ⚠️ **${label}**：${review.quality_review_note || '执行结束不代表所有结论已通过审核，请核对证据与审核记录。'}${review.stop_reason ? `（结束原因：${review.stop_reason}）` : ''}`
  return report.includes(notice) ? report : `${report}\n\n${notice}`
}

export function restoredStepStatus(step: { type?: string; status?: string }, checkpoint: {
  status?: string; state_json?: { stop_reason?: string }
}): 'pending' | 'running' | 'completed' | 'paused' | 'failed' {
  const reason = checkpoint.state_json?.stop_reason
  if ((reason === 'analysis_unavailable' && step.type === 'analyzing')
    || (reason === 'review_unavailable' && ['reviewing', 'review_retry'].includes(step.type || ''))) return 'failed'
  if (step.status === 'running') {
    if (checkpoint.status === 'paused' || checkpoint.status === 'failed') return checkpoint.status
    if (checkpoint.status === 'completed') return 'completed'
  }
  // Missing historical telemetry is not proof that an unexecuted stage succeeded.
  return ['pending', 'running', 'completed', 'paused', 'failed'].includes(step.status || '')
    ? step.status as 'pending' | 'running' | 'completed' | 'paused' | 'failed' : 'pending'
}

export function acceptedResumeCheckpoint<T extends { session_id: string; status: string; error_message?: string | null }>(
  checkpoint: T | null, sessionId: string,
): T | null {
  if (!checkpoint || checkpoint.session_id !== sessionId) return checkpoint
  // Only the server's research_resumed event calls this; a click/failed HTTP
  // request is not confirmation that the execution has resumed.
  return { ...checkpoint, status: 'running', error_message: null }
}

export function checkpointKnowledgeBase(checkpoint: { session_id: string; state_json?: Record<string, unknown> }, sessionId: string) {
  const state = checkpoint.state_json || {}
  if (checkpoint.session_id !== sessionId || state.search_local !== true
    || typeof state.kb_name !== 'string' || !state.kb_name.trim()
    || typeof state.knowledge_base_id !== 'string' || !state.knowledge_base_id.trim()) return null
  return { name: state.kb_name, id: state.knowledge_base_id }
}

export function checkpointSearchSelection(checkpoint: { session_id: string; state_json?: Record<string, unknown> }, sessionId: string) {
  if (checkpoint.session_id !== sessionId) return null
  const state = checkpoint.state_json || {}
  if (typeof state.search_local !== 'boolean' && typeof state.search_web !== 'boolean') return null
  const modes: Array<'local' | 'web'> = []
  if (state.search_local === true) modes.push('local')
  if (state.search_web === true) modes.push('web')
  return { modes, knowledgeBase: checkpointKnowledgeBase(checkpoint, sessionId) }
}

export const transportToChatEnter = Symbol() as PageTransportKey<{
  data: ChatEnterData
}>

let id = 0

export const createChatId = () => {
  return ++id
}

export function createChatIdText(id: number) {
  return `chat-item-${id}`
}
