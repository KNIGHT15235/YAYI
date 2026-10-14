import { useState, type ReactNode, type MouseEvent } from 'react'
import { Alert, Modal, Tag, message } from 'antd'
import { resolveClaimEvidence, resolveLocalDocumentSource, safeExternalUrl, type ScienceResearchData, type ClaimEvidenceLink, type Paper } from '@/api/research-types'
import DocumentPreview, { LocatorTags } from './document-preview'

/** Scope citation clicks to the immutable evidence snapshot of this report version. */
export default function ClaimEvidenceBoundary({ data, children }: { data?: ScienceResearchData | null; children: ReactNode }) {
  const [selection, setSelection] = useState<ReturnType<typeof resolveClaimEvidence> | { claim?: undefined; link: ClaimEvidenceLink; evidence: Paper }>()
  const onClick = (event: MouseEvent<HTMLDivElement>) => {
    const anchor = event.target instanceof Element ? event.target.closest('a') : null
    const href = anchor?.getAttribute('href') || ''
    const isClaim = href.startsWith('#claim-evidence:')
    const isLocal = href.startsWith('/knowledge-bases/')
    if (!isClaim && !isLocal) return
    event.preventDefault()
    event.stopPropagation()
    const source = isLocal ? resolveLocalDocumentSource(href, data) : undefined
    const result = isClaim ? resolveClaimEvidence(href, data) : source ? {
      evidence: source, link: { evidence_id: source.evidence_id || '', precision: 'source', document_version: source.document_version },
    } : undefined
    if (result) setSelection(result)
    else message.warning('此版本没有可用的精确定位记录，请从证据与审核面板核对原文。')
  }
  const source = selection?.evidence
  const link = selection?.link
  const external = safeExternalUrl(source?.url)
  return <div style={{ display: 'contents' }} onClick={onClick}>
    {children}
    <Modal title="结论与原文证据" open={!!selection} onCancel={() => setSelection(undefined)} footer={null} width={780}>
      <p>{selection?.claim?.claim_text}</p>
      {link?.precision === 'source' && <Alert type="info" showIcon message="这是当前报告保存的来源级回链，不代表某条结论的精确定位或核验通过。" />}
      <Tag>{source?.title}</Tag><Tag>{link?.precision || 'chunk'}</Tag>
      <LocatorTags locators={link?.locator ? [link.locator] : source?.locators} />
      <blockquote style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{link?.quote || source?.content || source?.abstract || '未保存可读原文'}</blockquote>
      {(!link?.precision || ['chunk', 'chunk_level'].includes(link.precision)) && <Alert type="info" showIcon message="这是片段级引用，不代表已核实某个精确单元格或图像中的数值。" />}
      {source?.knowledge_base_id && source.document_id && <DocumentPreview
        key={[source.knowledge_base_id, source.document_id, link?.document_version ?? source.document_version, link?.asset_id, selection?.claim?.claim_id].join(':')}
        kbId={source.knowledge_base_id} documentId={source.document_id} filename={source.title}
        assets={source.assets} locators={link?.locator ? [link.locator] : source.locators}
        selectedAssetId={link?.asset_id} documentVersion={link?.document_version ?? source.document_version} />}
      {external && <p><a href={external} target="_blank" rel="noopener noreferrer">查看文献来源</a></p>}
    </Modal>
  </div>
}
