import { useRef, useState } from 'react'
import { Alert, Button, Card, Empty, Input, List, Space, Tag, Tooltip, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { downloadDocumentFile, searchKnowledgeBase, type KnowledgeSearchResponse } from '@/api/knowledge'
import DocumentPreview, { LocatorTags } from '@/components/document-preview'

export function HighlightedText({ text, query }: { text: string; query: string }) {
  const terms = query.trim().split(/\s+/).filter(Boolean).map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!terms.length) return <>{text}</>
  const pieces = text.split(new RegExp(`(${terms.join('|')})`, 'gi'))
  return <>{pieces.map((piece, index) => index % 2 ? <mark key={index}>{piece}</mark> : piece)}</>
}

export function DownloadDocumentButton({ kbId, documentId, filename, available }: {
  kbId: string; documentId: string; filename: string; available?: boolean
}) {
  const [loading, setLoading] = useState(false)
  const download = async () => {
    setLoading(true)
    try {
      const blob = await downloadDocumentFile(kbId, documentId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '下载失败')
    } finally { setLoading(false) }
  }
  return <Tooltip title={available === false ? '原文件不可用，请重新上传文档' : '下载原文件'}>
    <Button size="small" icon={<DownloadOutlined />} loading={loading} disabled={available === false} onClick={download}>原文件</Button>
  </Tooltip>
}

export default function KnowledgeSearch({ kbId }: { kbId: string }) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<KnowledgeSearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(0)
  const search = async (value: string) => {
    if (!value.trim()) return
    const current = ++requestId.current
    setLoading(true); setError(''); setResult(null)
    try {
      const response = await searchKnowledgeBase(kbId, value.trim())
      if (current === requestId.current) setResult(response.data)
    } catch (cause: any) {
      if (current === requestId.current) setError(cause?.response?.data?.detail || cause?.message || '知识库检索失败')
    } finally { if (current === requestId.current) setLoading(false) }
  }
  return <Card title="在此知识库中检索" style={{ marginBottom: 20 }}>
    <Input.Search aria-label="知识库检索问题" placeholder="输入问题，查看相关段落与来源" value={query} onChange={event => setQuery(event.target.value)} onSearch={search} loading={loading} enterButton="检索" />
    {error && <Alert style={{ marginTop: 12 }} type="error" message={error} showIcon />}
    {result?.warning && <Alert style={{ marginTop: 12 }} type="warning" message={result.warning} showIcon />}
    {result && <>
      <Tag style={{ marginTop: 12 }}>{result.reranked ? '已重排' : '向量检索'}</Tag>
      <List dataSource={result.results} locale={{ emptyText: <Empty description="没有匹配段落" /> }} renderItem={item => <List.Item key={item.chunk_id}>
        <div style={{ width: '100%' }}>
          <Space wrap style={{ marginBottom: 8 }}>
            <strong>{item.document_name}</strong><Tag>切片 {item.chunk_index + 1}</Tag>
            <Tag>余弦相似度 {typeof item.score === 'number' && Number.isFinite(item.score) ? item.score.toFixed(3) : '不可用'}</Tag>
            {typeof item.rerank_score === 'number' && Number.isFinite(item.rerank_score) && <Tag>重排分数 {item.rerank_score.toFixed(3)}</Tag>}
            <DownloadDocumentButton kbId={kbId} documentId={item.document_id} filename={item.document_name} available={item.download_available} />
            <DocumentPreview kbId={kbId} documentId={item.document_id} filename={item.document_name} assets={item.assets} locators={item.locators} />
            <LocatorTags locators={item.locators} />
          </Space>
          <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, margin: 0 }}><HighlightedText text={item.content} query={result.query} /></p>
        </div>
      </List.Item>} />
    </>}
  </Card>
}
