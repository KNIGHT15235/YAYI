
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

type QualityReview = {
  quality_score?: unknown
  quality_review_status?: string
  quality_review_note?: string
  verdict?: string
  passed?: boolean
  summary?: string
}

export function reviewPresentation(review: QualityReview) {
  const score = review.quality_score
  const unconfirmed = review.quality_review_status === 'unconfirmed' || review.verdict === 'unconfirmed'
    || typeof score !== 'number' || !Number.isFinite(score) || score < 1 || score > 10
  const passed = !unconfirmed && (review.verdict ? review.verdict === 'pass'
    : typeof review.passed === 'boolean' ? review.passed : score >= 7)
  return {
    unconfirmed,
    passed,
    text: unconfirmed
      ? `⚠️ 质量审核待确认\n${review.quality_review_note || review.summary || '未取得有效评分，请人工核对来源与结论。'}`
      : `🔍 审核结果: 质量评分 ${score}/10\n${passed ? '✅ 审核通过' : '⚠️ 需要修订'}`,
  }
}

export function withQualityReviewNotice(report: string, review?: QualityReview) {
  if (!review || (review.quality_review_status !== 'unconfirmed' && review.quality_score !== null)) return report
  const notice = `> ⚠️ **质量审核待确认**：${review.quality_review_note || '未取得有效评分，请人工核对来源与结论。'}`
  return report.includes(notice) ? report : `${report}\n\n${notice}`
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
