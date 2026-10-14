
import { request } from './request'
import { authState } from '@/store/auth'

export interface KnowledgeBase {
  id: string
  name: string
  description?: string
  document_count: number
  created_at: string
  updated_at: string
}

export interface KBDocument {
  download_available?: boolean
  id: string
  knowledge_base_id: string
  filename: string
  file_type?: string
  file_size?: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  chunk_count: number
  error_message?: string
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseWithDocuments extends KnowledgeBase {
  documents: KBDocument[]
}

export interface CreateKnowledgeBaseParams {
  name: string
  description?: string
}

export interface UpdateKnowledgeBaseParams {
  name?: string
  description?: string
}

/**
 * 获取知识库列表
 */
export function getKnowledgeBases() {
  return request.get<KnowledgeBase[]>('/knowledge-bases', { loading: false })
}

/**
 * 创建知识库
 */
export function createKnowledgeBase(params: CreateKnowledgeBaseParams) {
  return request.post<KnowledgeBase>('/knowledge-bases', params)
}

/**
 * 获取知识库详情（包含文档列表）
 */
export function getKnowledgeBase(kbId: string) {
  return request.get<KnowledgeBaseWithDocuments>(`/knowledge-bases/${kbId}`, { loading: false })
}

/**
 * 更新知识库
 */
export function updateKnowledgeBase(kbId: string, params: UpdateKnowledgeBaseParams) {
  return request.put<KnowledgeBase>(`/knowledge-bases/${kbId}`, params)
}

/**
 * 删除知识库
 */
export function deleteKnowledgeBase(kbId: string) {
  return request.delete(`/knowledge-bases/${kbId}`)
}

/**
 * 上传文档到知识库
 */
export function uploadDocument(kbId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<{ status: string; id: string; filename: string; process_status: string; message: string }>(
    `/knowledge-bases/${kbId}/documents`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      // 禁用全局 loading，使用 UploadModal 展示进度
      loading: false,
      // 禁用取消重复请求（上传可能耗时较长）
      cancelRepeat: false,
      // 设置较长的超时时间（5分钟）
      timeout: 300000,
    }
  )
}

/**
 * 获取知识库的文档列表
 */
export function getDocuments(kbId: string) {
  return request.get<KBDocument[]>(`/knowledge-bases/${kbId}/documents`, { loading: false })
}

/**
 * 删除文档
 */
export function deleteDocument(kbId: string, docId: string) {
  return request.delete(`/knowledge-bases/${kbId}/documents/${docId}`)
}

/**
 * 切片信息
 */
export interface ChunkInfo {
  index: number
  content: string
  chunk_id?: string
  document_version?: number | string
  locators?: DocumentLocator[]
  assets?: DocumentAsset[]
  evidence_id?: string
  content_hash?: string
}

export interface DocumentLocator {
  page?: number | string | number[]
  page_id?: number | string | number[]
  bbox?: unknown
  table_rows?: unknown
  equation_number?: string | number
  figure_number?: string | number
  block_id?: string
  [key: string]: unknown
}

export interface DocumentAsset {
  asset_id: string
  type: string
  content?: string
  locator?: DocumentLocator
  download_url?: string
  content_hash?: string
  document_version?: number | string
}

/**
 * 文档切片响应
 */
export interface DocumentChunksResponse {
  document_id: string
  filename: string
  chunk_count: number
  chunks: ChunkInfo[]
}

/**
 * 获取文档切片
 */
export function getDocumentChunks(kbId: string, docId: string) {
  return request.get<DocumentChunksResponse>(`/knowledge-bases/${kbId}/documents/${docId}/chunks`, {
    loading: false,
  })
}

export interface KnowledgeSearchResult {
  chunk_id: string
  document_id: string
  document_name: string
  content: string
  score: number | null
  rerank_score?: number | null
  chunk_index: number
  download_available: boolean
  download_url?: string
  document_version?: number
  locators?: DocumentLocator[]
  assets?: DocumentAsset[]
  evidence_id?: string
  content_hash?: string
}

export interface KnowledgeSearchResponse {
  knowledge_base_id: string
  query: string
  reranked: boolean
  warning?: string
  results: KnowledgeSearchResult[]
}

export function searchKnowledgeBase(kbId: string, query: string) {
  return request.post<KnowledgeSearchResponse>(`/knowledge-bases/${encodeURIComponent(kbId)}/search`,
    { query, top_k: 10, rerank: true }, { loading: false, errorToast: false })
}

export async function downloadDocumentFile(kbId: string, docId: string): Promise<Blob> {
  const base = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')
  const response = await fetch(`${base}/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(docId)}/download`, {
    headers: authState.token ? { Authorization: `Bearer ${authState.token}` } : {},
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || (response.status === 404 ? '原文件不可用，请重新上传文档' : '原文件下载失败'))
  }
  return response.blob()
}

export function getDocumentAssets(kbId: string, docId: string, documentVersion?: number | string) {
  return request.get<{ document_id: string; assets: DocumentAsset[] }>(`/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(docId)}/assets`, {
    loading: false, params: documentVersion == null ? undefined : { document_version: documentVersion },
  })
}

export async function downloadDocumentAsset(kbId: string, docId: string, assetId: string): Promise<Blob> {
  const base = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')
  const response = await fetch(`${base}/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(docId)}/assets/${encodeURIComponent(assetId)}/download`, {
    headers: authState.token ? { Authorization: `Bearer ${authState.token}` } : {},
  })
  if (!response.ok) throw new Error('资产不可用或没有访问权限')
  return response.blob()
}
