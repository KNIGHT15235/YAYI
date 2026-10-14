import { useEffect, useState } from 'react'
import { Button, Empty, Modal, Space, Tag, message } from 'antd'
import { downloadDocumentAsset, getDocumentAssets, type DocumentAsset, type DocumentLocator } from '@/api/knowledge'
import { hasLocatorDetails, locatorLabels } from '@/utils/document-locator'

export function LocatorTags({ locators }: { locators?: DocumentLocator[] }) {
  return <>{locators?.map((locator, i) => <Space key={i} size={4} wrap style={{ maxWidth: '100%', alignItems: 'start' }}>
    {locatorLabels(locator).map(label => <Tag key={label}>{label}</Tag>)}
    {hasLocatorDetails(locator) && <details style={{ maxWidth: '100%', fontSize: 12 }}>
      <summary style={{ cursor: 'pointer', color: '#64748b' }}>定位详情</summary>
      <pre style={{ maxWidth: 'min(660px, 75vw)', maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: '8px 0' }}>{JSON.stringify(locator, null, 2)}</pre>
    </details>}
  </Space>)}</>
}

export default function DocumentPreview({ kbId, documentId, filename, assets: initialAssets, locators }: {
  kbId: string; documentId: string; filename: string; assets?: DocumentAsset[]; locators?: DocumentLocator[]
}) {
  const [open, setOpen] = useState(false)
  const [assets, setAssets] = useState(initialAssets || [])
  const [loading, setLoading] = useState(false)
  const [imageUrl, setImageUrl] = useState('')
  useEffect(() => () => { if (imageUrl) URL.revokeObjectURL(imageUrl) }, [imageUrl])
  const show = async () => {
    setOpen(true); setLoading(true)
    try { const response = await getDocumentAssets(kbId, documentId); setAssets(response.data.assets || []) }
    catch { message.error('无法读取文献资产') }
    finally { setLoading(false) }
  }
  const viewAsset = async (asset: DocumentAsset) => {
    try {
      const blob = await downloadDocumentAsset(kbId, documentId, asset.asset_id)
      if (blob.type.startsWith('image/')) { setImageUrl(URL.createObjectURL(blob)); return }
      const url = URL.createObjectURL(blob); const link = document.createElement('a')
      link.href = url; link.download = `${filename}-${asset.asset_id}${blob.type.includes('json') ? '.json' : ''}`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { message.error(error instanceof Error ? error.message : '资产读取失败') }
  }
  return <><Button size="small" onClick={show}>原文定位与资产</Button>
    <Modal title={filename} open={open} onCancel={() => { setOpen(false); setImageUrl('') }} footer={null} width={820} loading={loading}>
      <LocatorTags locators={locators} />
      {imageUrl && <img src={imageUrl} alt="文献资产" style={{ maxWidth: '100%', margin: '16px 0' }} />}
      {!assets.length && <Empty description="该文档没有结构化资产；可下载原文件查看" />}
      {assets.map(asset => <div key={asset.asset_id} style={{ borderBottom: '1px solid #eee', padding: '14px 0' }}>
        <Space wrap><Tag>{asset.type}</Tag><LocatorTags locators={asset.locator ? [asset.locator] : []} />{asset.download_url && <Button size="small" onClick={() => viewAsset(asset)}>查看 / 下载资产</Button>}</Space>
        {asset.content && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', marginTop: 10 }}>{asset.content}</pre>}
      </div>)}
    </Modal></>
}
