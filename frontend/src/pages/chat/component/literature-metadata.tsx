import { Space, Tag } from 'antd'
import { LocatorTags } from '@/components/document-preview'
import DocumentPreview from '@/components/document-preview'
import { safeExternalUrl } from '@/api/research-types'
import type { Paper } from '@/api/research-types'

export default function LiteratureMetadata({ paper, excerpt = false }: { paper: Partial<Paper>; excerpt?: boolean }) {
  const doiUrl = paper.doi ? safeExternalUrl(`https://doi.org/${paper.doi.replace(/^https?:\/\/(?:dx\.)?doi.org\//, '')}`) : undefined
  return <div onClick={event => event.stopPropagation()} style={{ marginTop: 8, fontSize: 12 }}>
    <Space size={4} wrap>
      {paper.year && <Tag>{paper.year}</Tag>}
      {paper.evidence_id && <Tag>{paper.evidence_id}</Tag>}
      {paper.verified === true ? <Tag color="green">来源已核对</Tag> : paper.verified === false ? <Tag color="orange">来源待核验</Tag> : null}
      {paper.evidence_level && <Tag>{({ abstract: '摘要证据', fulltext: '全文证据', metadata: '元数据证据' } as Record<string, string>)[paper.evidence_level] || paper.evidence_level}</Tag>}
      <LocatorTags locators={paper.locators || (paper.locator ? [paper.locator] : [])} />
      {doiUrl && <a href={doiUrl} target="_blank" rel="noopener noreferrer">DOI: {paper.doi}</a>}
      {paper.knowledge_base_id && paper.document_id && <DocumentPreview kbId={paper.knowledge_base_id} documentId={paper.document_id} documentVersion={paper.document_version} filename={paper.title || '文献'} assets={paper.assets} locators={paper.locators} />}
    </Space>
    {excerpt && (paper.abstract || paper.content) && <details style={{ marginTop: 8 }}><summary style={{ cursor: 'pointer', color: '#1677ff' }}>查看证据摘录</summary><p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, color: '#475569' }}>{paper.abstract || paper.content}</p></details>}
  </div>
}
