import { useEffect, useId, useState } from 'react'
import { Alert, Button, Empty, Modal, Space, Tag, message } from 'antd'
import { downloadDocumentAsset, getDocumentAssets, type DocumentAsset, type DocumentLocator } from '@/api/knowledge'
import { hasLocatorDetails, locatorLabels, locatorWindow } from '@/utils/document-locator'

export function LocatorTags({ locators }: { locators?: DocumentLocator[] }) {
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  const { visible, total, hidden } = locatorWindow(locators, expanded)
  if (!total) return null
  return <div style={{ maxWidth: '100%', minWidth: 0 }}>
    <div id={listId} style={{ maxHeight: expanded ? 280 : undefined, overflowY: expanded ? 'auto' : undefined }}>
      {visible.map((locator, i) => <div key={i}>
        <Space size={4} wrap style={{ maxWidth: '100%', alignItems: 'start' }}>
          {locatorLabels(locator).map(label => <Tag key={label}>{label}</Tag>)}
          {hasLocatorDetails(locator) && <details style={{ maxWidth: '100%', fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', color: '#64748b' }}>定位详情</summary>
            <pre style={{ maxWidth: 'min(660px, 75vw)', maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: '8px 0' }}>{JSON.stringify(locator, null, 2)}</pre>
          </details>}
        </Space>
      </div>)}
    </div>
    {(hidden > 0 || expanded) && <Button type="link" size="small" aria-expanded={expanded} aria-controls={listId}
      onClick={() => setExpanded(value => !value)} style={{ paddingInline: 0 }}>
      {expanded ? `收起定位（共 ${total} 处）` : `展开其余 ${hidden} 处定位（共 ${total} 处）`}
    </Button>}
  </div>
}

export default function DocumentPreview({ kbId, documentId, filename, assets: initialAssets, locators, selectedAssetId, documentVersion }: {
  kbId: string; documentId: string; filename: string; assets?: DocumentAsset[]; locators?: DocumentLocator[]
  selectedAssetId?: string; documentVersion?: number | string
}) {
  const [open, setOpen] = useState(false)
  const [assets, setAssets] = useState(initialAssets || [])
  const [loading, setLoading] = useState(false)
  const [imageUrl, setImageUrl] = useState('')
  useEffect(() => () => { if (imageUrl) URL.revokeObjectURL(imageUrl) }, [imageUrl])
  const show = async () => {
    setOpen(true); setLoading(true)
    try {
      const response = await getDocumentAssets(kbId, documentId, documentVersion)
      setAssets((response.data.assets || []).filter(asset => documentVersion == null || String(asset.document_version) === String(documentVersion)))
    }
    catch { setAssets([]); message.error('无法读取文献资产') }
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
      {!assets.length && <Empty description="该版本没有可用结构化资产；不能用其他版本替代当前引用" />}
      {selectedAssetId && assets.length > 0 && !assets.some(asset => asset.asset_id === selectedAssetId) && <Alert type="warning" message="引用资产在当前文档版本不可用，请重新核对；未自动替换为其他资产。" />}
      {assets.filter(asset => !selectedAssetId || asset.asset_id === selectedAssetId).map(asset => <div key={asset.asset_id} style={{ borderBottom: '1px solid #eee', padding: '14px 0' }}>
        <Space wrap><Tag>{asset.type}</Tag><LocatorTags locators={asset.locator ? [asset.locator] : []} />{asset.download_url && <Button size="small" onClick={() => viewAsset(asset)}>查看 / 下载资产</Button>}</Space>
        {asset.content && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', marginTop: 10 }}>{asset.content}</pre>}
      </div>)}
    </Modal></>
}
