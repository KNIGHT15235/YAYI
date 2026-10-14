import type { DocumentAsset, DocumentLocator } from './knowledge'

export interface Paper {
  id?: string | number
  source_id?: string
  evidence_id?: string
  title: string
  url?: string
  doi?: string
  year?: number | string
  authors?: (string | { name?: string })[]
  abstract?: string
  content?: string
  provider?: string
  verified?: boolean
  verification?: string | Record<string, unknown>
  evidence_level?: string
  locator?: DocumentLocator
  locators?: DocumentLocator[]
  assets?: DocumentAsset[]
  document_id?: string
  knowledge_base_id?: string
  document_version?: number | string
  chunk_id?: string
  asset_ids?: string[]
}

export interface ClaimEvidenceLink {
  evidence_id: string
  asset_id?: string
  locator?: DocumentLocator
  quote?: string
  text_span?: [number, number] | { start: number; end: number }
  precision?: string
  document_version?: number | string
}

export interface Claim {
  claim_id: string
  section_id?: string
  claim_text: string
  evidence_ids: string[]
  verification_status?: string
  reason?: string
  evidence_links?: ClaimEvidenceLink[]
}

export interface ClaimVerification {
  checked?: number
  total?: number
  skipped?: number
  supported?: number
  contradicted?: number
  insufficient?: number
  unverified?: number
  coverage?: number
  results?: { claim_id: string; status: string; reason?: string }[]
}

export interface ScienceResearchData {
  outcome?: string
  reviewVerdict?: string
  stopReason?: string
  papers?: Paper[]
  evidenceLedger?: Record<string, Paper>
  claims?: Claim[]
  claimVerification?: ClaimVerification
  evidenceAssessment?: { sufficient?: boolean; missing_questions?: string[]; required_evidence?: unknown; [key: string]: unknown }
  hypotheses?: { id?: string; hypothesis?: string; statement?: string; status?: string; reason?: string; [key: string]: unknown }[]
}

/** Metadata is optional, so saved research from earlier versions remains readable. */
export function readScienceData(data: Record<string, any> = {}): ScienceResearchData {
  return {
    outcome: data.outcome || data.research_outcome,
    reviewVerdict: data.review_verdict,
    stopReason: data.stop_reason,
    papers: data.papers,
    evidenceLedger: data.evidence_ledger,
    claims: data.claims,
    claimVerification: data.claim_verification,
    evidenceAssessment: data.evidence_assessment,
    hypotheses: data.hypotheses,
  }
}

/** Stream payloads are partial; replace supplied arrays, never erase an absent ledger. */
export function mergeScienceData(previous: ScienceResearchData | undefined, payload: Record<string, any>): ScienceResearchData {
  const patch = Object.fromEntries(Object.entries(readScienceData(payload)).filter(([, value]) => value !== undefined))
  return { ...previous, ...patch }
}

/** Legacy source links lack a claim locator: allow only exact, unambiguous saved identities. */
export function resolveLocalDocumentSource(href: string, data?: ScienceResearchData | null) {
  const match = /^\/knowledge-bases\/([0-9a-f-]{36})\/documents\/([0-9a-f-]{36})\/download$/i.exec(href)
  if (!match) return undefined
  const sources = Object.values(data?.evidenceLedger || {}).filter(source =>
    source.knowledge_base_id === match[1] && source.document_id === match[2]
    && source.document_version != null && String(source.document_version).length > 0)
  if (!sources.length || new Set(sources.map(source => String(source.document_version))).size !== 1) return undefined
  return sources[0]
}

/** Resolve only links belonging to the displayed report version, never another run. */
export function resolveClaimEvidence(href: string, data?: ScienceResearchData | null) {
  if (!href.startsWith('#claim-evidence:')) return undefined
  const parts = href.slice('#claim-evidence:'.length).split(':')
  if (parts.length !== 2 || !/^\d+$/.test(parts[1])) return undefined
  try {
    const claim = data?.claims?.find(row => row.claim_id === decodeURIComponent(parts[0]))
    const link = claim?.evidence_links?.[Number(parts[1])]
    const evidence = link && data?.evidenceLedger?.[link.evidence_id]
    if (!claim || !link || !evidence || !claim.evidence_ids.includes(link.evidence_id)) return undefined
    return { claim, link, evidence }
  } catch { return undefined }
}

/** Prefer raw state evidence over older UI snapshots that flattened bibliographic fields. */
export function checkpointDisplayState(checkpoint: Record<string, any>): Record<string, any> {
  const state = checkpoint.state_json || {}
  const ui = checkpoint.ui_state_json || {}
  const graph = ui.knowledge_graph
  return {
    ...state,
    ...ui,
    charts: ui.charts?.length ? ui.charts : state.charts || [],
    knowledge_graph: graph?.nodes?.length || graph?.edges?.length ? graph : state.knowledge_graph,
    references: state.references?.length ? state.references : ui.references || [],
    streaming_report: checkpoint.final_report || state.final_report || ui.streaming_report || '',
  }
}

export function normalizeReference(ref: Record<string, any>, index: number): API.Reference {
  return {
    ...ref,
    id: Number.isInteger(Number(ref.id)) && Number(ref.id) > 0 ? Number(ref.id) : index + 1,
    title: ref.title || ref.source_name || '来源',
    link: ref.link || ref.url || ref.source_url || '',
    content: ref.content || ref.abstract || ref.summary || '',
    source: ['local', 'knowledge'].includes(ref.source_type || ref.source) ? 'knowledge' : 'web',
  }
}

export function safeExternalUrl(url?: string): string | undefined {
  if (!url) return undefined
  try { const value = new URL(url); return ['https:', 'http:'].includes(value.protocol) ? value.href : undefined } catch { return undefined }
}

/** Relative citations belong to the local knowledge base, not a public website. */
export function findSourceHost<T extends { url: string }>(url: string | undefined, hosts: readonly T[]): T | undefined {
  const externalUrl = safeExternalUrl(url)
  if (!externalUrl) return undefined
  const hostname = new URL(externalUrl).hostname
  return hosts.find(host => hostname === host.url
    || hostname.replace(/^www\./, '') === host.url.replace(/^www\./, '')
    || (hostname.split('.').length >= 2 && hostname.replace(/^.+?\.(.+)$/, '$1') === host.url.replace(/^www\./, '')))
}
