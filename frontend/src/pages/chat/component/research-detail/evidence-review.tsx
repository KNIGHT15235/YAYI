import { Alert, Collapse, Empty, Space, Tag } from 'antd'
import type { ScienceResearchData } from '@/api/research-types'
import LiteratureMetadata from '../literature-metadata'

const labels: Record<string, string> = { supported: '支持', contradicted: '矛盾', insufficient: '证据不足', unverified: '未核验', pending: '待核验', partially_supported: '部分支持', refuted: '反驳', mixed: '混合证据' }
const evidenceList = (value: unknown): string[] => Array.isArray(value) ? value.map(item => typeof item === 'string' ? item : JSON.stringify(item)) : []
const colors: Record<string, string> = { supported: 'green', contradicted: 'red', insufficient: 'orange', partially_supported: 'gold', mixed: 'purple' }

export default function EvidenceReview({ data }: { data?: ScienceResearchData | null }) {
  if (!data?.claims?.length && !data?.hypotheses?.length && !data?.evidenceAssessment) return <Empty description="审核结果将在证据分析与引用核验后显示" />
  const verification = data?.claimVerification
  const ledger = data?.evidenceLedger || {}
  return <div style={{ padding: 20 }}>
    <Space wrap style={{ marginBottom: 16 }}>
      <Tag>声明 {verification?.total ?? data?.claims?.length ?? 0}</Tag>
      <Tag>已核验 {verification?.checked ?? 0}</Tag>
      <Tag color="green">支持 {verification?.supported ?? 0}</Tag>
      <Tag color="orange">证据不足 {verification?.insufficient ?? 0}</Tag>
      <Tag color="red">矛盾 {verification?.contradicted ?? 0}</Tag>
      <Tag>未核验 {verification?.unverified ?? 0}</Tag>
      <Tag>跳过 {verification?.skipped ?? 0}</Tag>
      {typeof verification?.coverage === 'number' && <Tag>审核覆盖率 {(verification.coverage * 100).toFixed(1)}%</Tag>}
    </Space>
    {data?.evidenceAssessment?.sufficient === false && <Alert type="warning" showIcon message="仍存在证据缺口" description={data.evidenceAssessment.missing_questions?.join('；') || '请结合审核原因理解结论适用范围。'} style={{ marginBottom: 16 }} />}
    {!!data?.hypotheses?.length && <><h3>研究假设</h3><Collapse style={{ marginBottom: 20 }} items={data.hypotheses.map((hypothesis, i) => ({ key: hypothesis.id || i, label: <Space wrap><Tag color={colors[hypothesis.status || '']}>{labels[hypothesis.status || ''] || hypothesis.status || '待验证'}</Tag>{String(hypothesis.content || hypothesis.hypothesis || hypothesis.statement || hypothesis.description || `假设 ${i + 1}`)}</Space>, children: <div style={{ whiteSpace: 'pre-wrap' }}><p>{String(hypothesis.reason || hypothesis.assessment || hypothesis.rationale || '结合下方证据查看假设验证结果。')}</p>{evidenceList(hypothesis.evidence_ids || hypothesis.evidence).map((id, index) => <p key={`${id}-${index}`}><Tag>{id}</Tag>{ledger[id]?.title || id}</p>)}{!!evidenceList(hypothesis.evidence_for).length && <p><strong>支持证据：</strong>{evidenceList(hypothesis.evidence_for).join('；')}</p>}{!!evidenceList(hypothesis.evidence_against).length && <p><strong>反驳证据：</strong>{evidenceList(hypothesis.evidence_against).join('；')}</p>}</div> }))} /></>}
    <h3>逐条声明与证据</h3>
    <Collapse items={(data?.claims || []).map(claim => {
      const result = verification?.results?.find(item => item.claim_id === claim.claim_id)
      const status = result?.status || claim.verification_status || 'unverified'
      return { key: claim.claim_id, label: <span><Tag color={colors[status]}>{labels[status] || status}</Tag>{claim.claim_text}</span>, children: <div>
        <p>{result?.reason || claim.reason || '尚未给出语义核验结论。'}</p>
        {(claim.evidence_links || []).map((link, index) => <p key={`${link.evidence_id}-${index}`}><a href={`#claim-evidence:${encodeURIComponent(claim.claim_id)}:${index}`}>查看引用位置 {index + 1}</a> <Tag>{link.precision || 'chunk'}</Tag></p>)}
        {(claim.evidence_ids || []).map(id => <div key={id} style={{ padding: '10px 0', borderTop: '1px solid #f0f0f0' }}><strong>{id} · {ledger[id]?.title || '未找到关联证据'}</strong>{ledger[id] && <LiteratureMetadata paper={ledger[id]} />}<p style={{ whiteSpace: 'pre-wrap' }}>{ledger[id]?.content || ledger[id]?.abstract || '没有保存可供展示的原文摘录。'}</p></div>)}
      </div> }
    })} />
  </div>
}
