
import * as api from '@/api'
import { getRequestErrorMessage } from '@/api/request/error'
import ComPageLayout from '@/components/page-layout'
import ComSender, { AttachmentInfo } from '@/components/sender'
import { ChatRole, ChatType } from '@/configs'
import { checkpointResearchProfile, RESEARCH_PROFILE_LABELS, type ResearchProfileId } from '@/configs/research'
import { deviceActions, deviceState } from '@/store/device'
import { sessionState } from '@/store/session'
import { usePageTransport } from '@/utils'
import { useUnmount } from 'ahooks'
import { uniqueId } from 'lodash-es'
import { message as uiMessage, Button, Space, Tag, Modal, Input, InputNumber, Select, Checkbox, Alert } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { proxy, useSnapshot } from 'valtio'
import ChatMessage from './component/chat-message'
import Drawer from './component/drawer'
import Source from './component/source'
import StepDetailPanel, { StepDetailData } from './component/step-detail-panel'
import ResearchDetail, { ResearchDetailData, ResearchStep } from './component/research-detail'
import styles from './index.module.scss'
import { normalizeReference, readScienceData, mergeScienceData, checkpointDisplayState } from '@/api/research-types'
import { createChatId, createChatIdText, transportToChatEnter, mergeCharts, upsertResearchStep, completeSupplementarySearch, revisionPresentation, reviewPresentation, withQualityReviewNotice, restoredStepStatus, acceptedResumeCheckpoint, checkpointSearchSelection } from './shared'
import { ResearchStreamScope } from '@/utils/research-stream'
import type { Claim } from '@/api/research-types'
import ClaimEvidenceBoundary from '@/components/claim-evidence-boundary'

async function scrollToBottom() {
  await new Promise((resolve) => setTimeout(resolve))

  const threshold = 200
  const distanceToBottom =
    document.documentElement.scrollHeight -
    document.documentElement.scrollTop -
    document.documentElement.clientHeight

  if (distanceToBottom <= threshold) {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: 'smooth',
    })
  }
}

export default function Index() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: ctx } = usePageTransport(transportToChatEnter)
  const initialProfile = ctx && ctx.data.sessionId === id ? ctx.data.profileId : null
  const [profileId, setProfileId] = useState<ResearchProfileId | null>(initialProfile)
  const researchProfileRef = useRef<ResearchProfileId | null>(initialProfile)
  const profileLoadedRef = useRef(!!initialProfile)

  const [currentChatItem, setCurrentChatItem] = useState<API.ChatItem | null>(
    null,
  )

  // 步骤详情状态 (旧版)
  const [selectedStepDetail, setSelectedStepDetail] = useState<StepDetailData | null>(null)
  const stepDetailsRef = useRef<Map<string, StepDetailData>>(new Map())

  // 研究过程状态 (新版)
  const [researchSteps, setResearchSteps] = useState<ResearchStep[]>([])
  const researchStepsRef = useRef<ResearchStep[]>([])  // 保持最新引用，供事件处理器使用
  const [selectedResearchDetail, setSelectedResearchDetail] = useState<ResearchDetailData | null>(null)
  const researchDetailsRef = useRef<Map<string, ResearchDetailData>>(new Map())
  // 版本计数器 - 用于触发 aggregatedResearchData 重新计算
  const [researchDataVersion, setResearchDataVersion] = useState(0)

  // 同步 researchSteps 到 ref
  useEffect(() => {
    researchStepsRef.current = researchSteps
  }, [researchSteps])

  // 附件状态管理
  const [attachments, setAttachments] = useState<AttachmentInfo[]>([])
  const attachmentPollingRef = useRef<NodeJS.Timeout | null>(null)

  const [chat] = useState(() => {
    return proxy({
      list: [] as API.ChatItem[],
    })
  })
  const { list } = useSnapshot(chat) as {
    list: API.ChatItem[]
  }

  const loading = useMemo(() => {
    return list.some((o) => o.loading)
  }, [list])
  const loadingRef = useRef(loading)
  loadingRef.current = loading
  useEffect(() => {
    deviceActions.setChatting(loading)
  }, [loading])
  useUnmount(() => {
    operationGenerationRef.current += 1
    viewIdentityRef.current.generation += 1
    streamScopeRef.current.close()
    void readerRef.current?.cancel().catch(() => {})
    readerRef.current = null
    deviceActions.setChatting(false)
    // 清理轮询
    if (attachmentPollingRef.current) {
      clearInterval(attachmentPollingRef.current)
    }
  })

  // 用于取消请求的 ref
  const readerRef = useRef<ReadableStreamDefaultReader<any> | null>(null)
  const streamScopeRef = useRef(new ResearchStreamScope())
  const operationGenerationRef = useRef(0)
  const sendPendingRef = useRef<number | null>(null)
  const viewIdentityRef = useRef({ id, generation: 0 })
  if (viewIdentityRef.current.id !== id) {
    viewIdentityRef.current = { id, generation: viewIdentityRef.current.generation + 1 }
  }
  const stoppingRef = useRef(false)
  const [stopping, setStopping] = useState(false)
  const currentSessionIdRef = useRef<string | null>(null)
  const [checkpointInfo, setCheckpointInfo] = useState<api.session.ResearchCheckpoint | null>(null)
  const [resuming, setResuming] = useState(false)
  const [savingMemory, setSavingMemory] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [reviewNotes, setReviewNotes] = useState('')
  const [reviewClaimIds, setReviewClaimIds] = useState<string[]>([])
  const [additionalIterations, setAdditionalIterations] = useState(1)
  const [useRemainingBudget, setUseRemainingBudget] = useState(false)
  const resumeLock = useRef(false)
  const loadCheckpointRef = useRef<() => Promise<void>>(async () => {})
  const activeSessionRef = useRef(id)
  activeSessionRef.current = id
  const restoredCheckpointRef = useRef<api.session.ResearchCheckpoint | null>(null)
  const restoreAssistantFromCheckpoint = useCallback((checkpoint: api.session.ResearchCheckpoint) => {
    const display = checkpointDisplayState(checkpoint)
    let assistant = chat.list.filter(item => item.role === ChatRole.Assistant).pop()
    if (!assistant) {
      chat.list.push({ id: createChatId(), role: ChatRole.Assistant, type: ChatType.Deepsearch, content: '' })
      assistant = chat.list[chat.list.length - 1]
    }
    assistant.type = ChatType.Deepsearch
    assistant.reactMode = true
    assistant.content = withQualityReviewNotice(display.streaming_report || assistant.content || '', checkpoint.state_json || {})
    assistant.charts = display.charts
    assistant.reference = display.references.map(normalizeReference)
    assistant.scienceData = readScienceData(display)
    setCurrentChatItem(assistant)
  }, [chat])

  const refreshCheckpointInfo = useCallback(async () => {
    if (!id) return
    const generation = operationGenerationRef.current
    try {
      const response = await api.session.getFullResearchCheckpoint(id)
      if (activeSessionRef.current === id && operationGenerationRef.current === generation) {
        setCheckpointInfo(response.data.checkpoint || null)
        restoredCheckpointRef.current = response.data.checkpoint || null
      }
    } catch { /* 查询失败不会改变已知检查点 */ }
  }, [id])

  // 停止生成
  const handleStop = useCallback(async () => {
    if (stoppingRef.current) return
    stoppingRef.current = true
    setStopping(true)
    console.log('[handleStop] 用户点击停止按钮')
    const stoppedSession = currentSessionIdRef.current || id
    const stopGeneration = ++operationGenerationRef.current
    const isCurrentStop = () => activeSessionRef.current === stoppedSession && operationGenerationRef.current === stopGeneration
    streamScopeRef.current.close()

    // 取消读取流
    const stoppedReader = readerRef.current
    readerRef.current = null
    if (stoppedReader) {
      try {
        await stoppedReader.cancel()
        console.log('[handleStop] 读取流已取消')
      } catch (e) {
        console.error('[handleStop] 取消读取流失败:', e)
      }
    }

    // 调用后端取消 API
    if (stoppedSession) {
      try {
        await api.session.cancelResearch(stoppedSession)
        console.log('[handleStop] 后端取消请求已发送')
      } catch (e) {
        console.error('[handleStop] 调用取消 API 失败:', e)
      }
    }

    if (!isCurrentStop()) return
    // 停止当前聊天项的加载状态
    const loadingItem = chat.list.find(item => item.loading)
    if (loadingItem) {
      loadingItem.loading = false
      if (!loadingItem.content) {
        loadingItem.content = '⏹️ 已停止生成'
      }
    }

    // 更新研究步骤状态
    setResearchSteps(prev => prev.map(s =>
      s.status === 'running' ? { ...s, status: 'paused' as const, subtitle: '已中断，等待检查点确认' } : s
    ))
    await refreshCheckpointInfo()
    if (isCurrentStop()) {
      stoppingRef.current = false
      resumeLock.current = false
      setStopping(false)
      setResuming(false)
    }
  }, [chat, refreshCheckpointInfo, id])

  // 轮询检查附件处理状态
  useEffect(() => {
    const pendingAttachments = attachments.filter(
      att => att.status === 'pending' || att.status === 'processing'
    )

    if (pendingAttachments.length > 0 && !attachmentPollingRef.current) {
      attachmentPollingRef.current = setInterval(async () => {
        for (const att of pendingAttachments) {
          try {
            const res = await api.session.getAttachment(att.id)
            if (res.data) {
              setAttachments(prev =>
                prev.map(a =>
                  a.id === att.id ? { ...a, status: res.data.status } : a
                )
              )
            }
          } catch (e) {
            console.error('Failed to check attachment status', e)
          }
        }
      }, 2000)
    } else if (pendingAttachments.length === 0 && attachmentPollingRef.current) {
      clearInterval(attachmentPollingRef.current)
      attachmentPollingRef.current = null
    }

    return () => {
      if (attachmentPollingRef.current) {
        clearInterval(attachmentPollingRef.current)
        attachmentPollingRef.current = null
      }
    }
  }, [attachments])

  // 上传附件
  const handleUploadAttachment = useCallback(async (file: File) => {
    if (!id) {
      uiMessage.error('请先创建会话')
      return null
    }

    // 添加临时附件
    const tempId = uniqueId('temp-attachment-')
    setAttachments(prev => [
      ...prev,
      { id: tempId, filename: file.name, status: 'uploading' }
    ])

    try {
      const res = await api.session.uploadAttachment(id, file)
      if (res.data) {
        // 替换临时附件为真实附件
        setAttachments(prev =>
          prev.map(a =>
            a.id === tempId
              ? { id: res.data.id, filename: res.data.filename, status: res.data.status }
              : a
          )
        )
        uiMessage.success(`附件 ${file.name} 上传成功`)
        return res.data
      }
    } catch (e: any) {
      uiMessage.error(`附件上传失败: ${e.message || '未知错误'}`)
      // 移除失败的附件
      setAttachments(prev => prev.filter(a => a.id !== tempId))
    }
    return null
  }, [id])

  // 移除附件
  const handleRemoveAttachment = useCallback(async (attachmentId: string) => {
    try {
      // 只有非临时 ID 才需要调用删除 API
      if (!attachmentId.startsWith('temp-')) {
        await api.session.deleteAttachment(attachmentId)
      }
      setAttachments(prev => prev.filter(a => a.id !== attachmentId))
    } catch (e) {
      console.error('Failed to delete attachment', e)
    }
  }, [])

  const sendChat = useCallback(
    async (target: API.ChatItem, message: string, attachmentIds?: string[], resume = false, resumeOptions: api.session.ResumeResearchOptions = {}) => {
      if (!id || activeSessionRef.current !== id) return
      const ticket = streamScopeRef.current.begin(id)
      const isCurrent = (runId?: unknown) => activeSessionRef.current === id && streamScopeRef.current.accepts(ticket, runId)
      currentSessionIdRef.current = id
      setCurrentChatItem(target)
      target.loading = true
      try {
        let res
        if (resume) {
          res = await api.session.resumeResearch(id!, resumeOptions, { signal: ticket.controller.signal })
        } else if (target.type === ChatType.Deepsearch) {
          // A new task carries its choice; history derives its mode only from
          // the saved checkpoint, never from another task or a build default.
          if (!profileLoadedRef.current) await loadCheckpointRef.current()
          if (!profileLoadedRef.current || !researchProfileRef.current) throw new Error('研究模式加载失败，请刷新后重试')
          if (!isCurrent()) return
          res = await api.session.deepsearch({
            query: message,
            profile_id: researchProfileRef.current,
            session_id: id,  // 传递会话 ID 用于检查点保存
            search_modes: deviceState.searchModes as string[],  // 传递搜索模式
            kb_name: deviceState.knowledgeBaseName || undefined,
          }, { signal: ticket.controller.signal })
        } else if (attachmentIds && attachmentIds.length > 0) {
          // 使用带附件的聊天接口
          res = await api.session.chatWithAttachments({
            session_id: id!,
            question: message,
            attachment_ids: attachmentIds,
          }, { signal: ticket.controller.signal })
        } else {
          res = await api.session.chat({
            session_id: id!,
            question: message,
          }, { signal: ticket.controller.signal })
        }

        const reader = res.data.getReader()
        if (!reader) return
        if (!isCurrent()) { await reader.cancel(); return }

        // 存储 reader 和 session ID 用于取消
        readerRef.current = reader
        currentSessionIdRef.current = id || null

        await read(reader)

        // 清理 reader ref
        if (isCurrent()) readerRef.current = null
      } catch (error) {
        if (isCurrent()) throw error
      } finally {
        target.loading = false
        if (isCurrent()) {
          readerRef.current = null
          currentSessionIdRef.current = null
          if (target.type === ChatType.Deepsearch) await refreshCheckpointInfo()
        }
      }

      async function read(reader: ReadableStreamDefaultReader<any>) {
        let temp = ''
        const decoder = new TextDecoder('utf-8')
        while (true) {
          const { value, done } = await reader.read()
          if (!isCurrent()) { await reader.cancel(); return }
          // 保留跨网络 chunk 的 UTF-8 字节，避免中文和 emoji 被替换为乱码。
          temp += decoder.decode(value, { stream: !done })

          while (true) {
            const index = temp.indexOf('\n')
            if (index === -1) break

            const slice = temp.slice(0, index)
            temp = temp.slice(index + 1)

            if (slice.startsWith('data: ')) {
              parseData(slice)
              scrollToBottom()
            }
          }

          if (done) {
            console.debug('数据接受完毕', temp)
            target.loading = false
            break
          }
        }
      }

      function parseData(slice: string) {
        try {
          const str = slice
            .trim()
            .replace(/^data\: /, '')
            .trim()
          if (str === '[DONE]') {
            return
          }

          const json = JSON.parse(str)
          if (!isCurrent(json.run_id || json.session_id)) return
          if (target.type === ChatType.Deepsearch) {
            // 辅助函数：从 V2 格式中提取实际内容
            const extractContent = (data: any): string => {
              if (typeof data === 'string') return data
              if (typeof data === 'object' && data !== null) {
                // V2 格式: content 是对象 { agent, content: "实际内容" }
                if (typeof data.content === 'string') return data.content
                // 如果 content 也是对象，尝试 JSON 格式化
                return JSON.stringify(data, null, 2)
              }
              return String(data || '')
            }

            // V2 研究开始事件
            if (json.type === 'research_resumed') {
              // This event is accepted only by the current stream ticket above.
              // Recheck inside the state updater as React may apply it later.
              restoredCheckpointRef.current = acceptedResumeCheckpoint(restoredCheckpointRef.current, id!)
              setCheckpointInfo(previous => isCurrent(json.run_id || json.session_id)
                ? acceptedResumeCheckpoint(previous, id!) : previous)
              target.reactMode = true
              target.reactSteps ||= []
              target.reactSteps.push({ step: target.reactSteps.length + 1, type: 'thought', content: `▶️ 从 ${json.phase || '检查点'} 继续研究`, timestamp: Date.now() })
            }
            if (json.type === 'research_start') {
              target.reactMode = true
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              target.reactSteps.push({
                step: 0,
                type: 'plan',
                content: `🔬 开始深度研究: ${json.query || ''}`,
                timestamp: Date.now(),
              })
              // 重置研究步骤
              console.log(`[前端] ⚠️ research_start: 清空 researchDetailsRef`)
              setResearchSteps([])
              researchDetailsRef.current.clear()
              setSelectedResearchDetail(null)
              setResearchDataVersion(0)
            }

            // V2 研究步骤事件 (新增)
            if (json.type === 'research_step') {
              const content = json.content || json
              const stepType = (content.step_type === 'researching' ? 'searching' : content.step_type) as ResearchStep['type']

              // 转换 stats 从 snake_case 到 camelCase
              const rawStats = content.stats || {}
              const stats = {
                resultsCount: rawStats.results_count,
                chartsCount: rawStats.charts_count,
                entitiesCount: rawStats.entities_count,
                sectionsCount: rawStats.sections_count,
                wordCount: rawStats.word_count,
                questionsCount: rawStats.questions_count,
                sourcesCount: rawStats.sources_count,
                referencesCount: rawStats.references_count,
              }

              setResearchSteps(prev => {
                if (!isCurrent(json.run_id || json.session_id)) return prev
                const existing = prev.find(s => s.type === stepType)
                const newSteps = upsertResearchStep<ResearchStep>(prev, {
                  id: stepType,
                  type: stepType,
                  title: content.title || existing?.title || stepType,
                  subtitle: content.subtitle || '',
                  status: content.status || 'running',
                  stats,
                })
                // 同步更新 ref，确保后续事件能立即访问
                researchStepsRef.current = newSteps
                return newSteps
              })

              // 初始化详情数据 - 使用 stepType 作为 key，确保一致性
              if (!researchDetailsRef.current.has(stepType)) {
                const newDetail: ResearchDetailData = {
                  stepId: stepType,  // 使用类型作为 ID
                  stepType,
                  title: content.title || stepType,
                  subtitle: content.subtitle,
                  searchResults: [],
                  charts: [],
                }
                researchDetailsRef.current.set(stepType, newDetail)
                console.log(`[前端] research_step: 创建 detail, key=${stepType}, detailsSize=${researchDetailsRef.current.size}`)
                // 自动选中新的步骤详情（特别是 searching/researching 步骤）
                if (stepType === 'searching' || content.status === 'running') {
                  setSelectedResearchDetail({ ...newDetail })
                }
              } else {
                console.log(`[前端] research_step: detail 已存在, key=${stepType}`)
              }
            }

            // V2 搜索结果事件 (详情面板用)
            if (json.type === 'search_results') {
              const content = json.content || json
              const results = content.results || []
              const isIncremental = content.isIncremental || false
              // 使用 stepType 作为 key 查找 detail
              const searchingType = researchStepsRef.current.find(s => s.type === 'searching') ? 'searching' : 'researching'
              const detail = researchDetailsRef.current.get(searchingType)
              console.log(`[前端] search_results: key=${searchingType}, detail=${detail ? '找到' : '未找到'}, results=${results.length}`)
              if (detail) {
                const newResults = results.map((r: any, i: number) => ({
                  ...r,
                  id: r.id || `sr_${Date.now()}_${i}`,
                  title: r.title,
                  source: r.source,
                  date: r.date,
                  url: r.url,
                  snippet: r.snippet,
                }))
                // 增量模式：累加结果；否则替换
                if (isIncremental && detail.searchResults) {
                  detail.searchResults = [...detail.searchResults, ...newResults]
                } else {
                  detail.searchResults = newResults
                }
                // 更新步骤统计
                setResearchSteps(prev => prev.map(s =>
                  s.type === searchingType
                    ? { ...s, stats: { ...s.stats, resultsCount: detail.searchResults?.length || 0 } }
                    : s
                ))
                // 自动选中并触发聚合数据更新
                setSelectedResearchDetail({ ...detail })
                setResearchDataVersion(v => v + 1)
              }
            }

            // V2 知识图谱事件
            if (json.type === 'knowledge_graph') {
              const content = json.content || json
              const graph = content.graph || content
              // 优先存储到 analyzing，其次 researching/searching - 使用 stepType 作为 key
              const targetType = researchDetailsRef.current.has('analyzing') ? 'analyzing'
                : researchDetailsRef.current.has('researching') ? 'researching' : 'searching'
              const detail = researchDetailsRef.current.get(targetType)
              console.log(`[前端] knowledge_graph: key=${targetType}, detail=${detail ? '找到' : '未找到'}, nodes=${graph.nodes?.length || 0}, edges=${graph.edges?.length || 0}`)
              if (detail) {
                detail.knowledgeGraph = {
                  nodes: graph.nodes || [],
                  edges: graph.edges || [],
                  stats: content.stats || graph.stats,
                }
                setSelectedResearchDetail({ ...detail })
                setResearchDataVersion(v => v + 1)
                console.log(`[前端] knowledge_graph: ✅ 已存储到 detail[${targetType}]`)
              } else {
                console.warn(`[前端] knowledge_graph: ⚠️ 未找到 detail, 可用 keys:`, Array.from(researchDetailsRef.current.keys()))
              }
            }

            // V2 图表事件 (DataAnalyst 发送的 ECharts 图表)
            if (json.type === 'charts') {
              const content = json.content || json
              const charts = content.charts || []
              console.log(`[前端] 收到 charts 事件，图表数量: ${charts.length}`)

              // 使用 stepType 作为 key 查找 detail
              const detail = researchDetailsRef.current.get('analyzing')
              console.log(`[前端] 查找 analyzing detail: ${detail ? '找到' : '未找到'}`)
              if (detail) {
                detail.charts = mergeCharts(detail.charts, charts)
                // 更新步骤统计
                setResearchSteps(prev => prev.map(s =>
                  s.type === 'analyzing'
                    ? { ...s, stats: { ...s.stats, chartsCount: charts.length } }
                    : s
                ))
                setSelectedResearchDetail({ ...detail })
                setResearchDataVersion(v => v + 1)
                console.log(`[前端] ✅ charts 已存储到 detail，触发更新`)
              }
              // 同时保存到 target.charts 供报告使用
              if (!target.charts) {
                target.charts = []
              }
              target.charts = mergeCharts(target.charts, charts)
              console.log(`[前端] target.charts 总数: ${target.charts?.length || 0}`)
            }

            // V2 阶段切换事件
            if (json.type === 'phase') {
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              const phaseLabels: Record<string, string> = {
                planning: '📋 规划阶段',
                researching: '🔍 搜索阶段',
                analyzing: '📊 分析阶段',
                writing: '✍️ 写作阶段',
                reviewing: '🔎 审核阶段',
                re_researching: '🔄 补充搜索',
                rewriting: '📝 重写阶段',
                revising: '📝 修订阶段',
              }
              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'thought',
                content: `${phaseLabels[json.phase] || json.phase}: ${extractContent(json.content)}`,
                timestamp: Date.now(),
              })

              if (json.phase === 'analyzing') {
                setResearchSteps(prev => {
                  if (!isCurrent(json.run_id || json.session_id)) return prev
                  const next = completeSupplementarySearch(prev, json.phase)
                  researchStepsRef.current = next
                  return next
                })
              }

              // 同时更新研究步骤条 - 映射 phase 到 step_type
              const phaseToStepType: Record<string, ResearchStep['type']> = {
                writing: 'writing',
                reviewing: 'reviewing',
                re_researching: 're_researching',
                rewriting: 'revising',
                revising: 'revising',
              }
              const stepType = phaseToStepType[json.phase]
              if (stepType) {
                setResearchSteps(prev => {
                  if (!isCurrent(json.run_id || json.session_id)) return prev
                  // A new accepted phase starts another execution of this step,
                  // including a previously paused/failed/completed revision.
                  const newSteps = upsertResearchStep<ResearchStep>(prev, {
                    id: stepType,
                    type: stepType,
                    title: phaseLabels[json.phase] || json.phase,
                    subtitle: extractContent(json.content) || '',
                    status: 'running',
                  })
                  researchStepsRef.current = newSteps

                  // 同时初始化 researchDetail - 使用 stepType 作为 key
                  if (!researchDetailsRef.current.has(stepType)) {
                    const newDetail: ResearchDetailData = {
                      stepId: stepType,
                      stepType,
                      title: phaseLabels[json.phase] || json.phase,
                      subtitle: extractContent(json.content) || '',
                      searchResults: [],
                      charts: [],
                      streamingReport: '',
                    }
                    researchDetailsRef.current.set(stepType, newDetail)
                    // 对于 writing 步骤，自动选中以便显示过程报告
                    if (stepType === 'writing') {
                      setSelectedResearchDetail({ ...newDetail })
                    }
                  }
                  return newSteps
                })
              }
            }

            // V2 大纲事件
            if (json.type === 'outline') {
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              const outlineContent = json.content || json
              const outline = outlineContent.outline || []
              const questions = outlineContent.research_questions || []

              let content = '**研究大纲**\n\n'
              if (outline.length > 0) {
                content += outline.map((sec: any, i: number) =>
                  `${i + 1}. **${sec.title}**\n   ${sec.description || ''}`
                ).join('\n\n')
              }
              if (questions.length > 0) {
                content += '\n\n**核心问题**\n' + questions.map((q: string) => `• ${q}`).join('\n')
              }

              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'plan',
                content,
                timestamp: Date.now(),
              })
            }

            if (['literature_corpus', 'evidence_assessment', 'hypotheses', 'planning_complete', 'claim_verification', 'report_draft', 'revision_complete'].includes(json.type)) {
              const payload = json.content || json
              const patch = json.type === 'literature_corpus' ? { papers: payload.papers || [], evidenceLedger: payload.evidence_ledger || {} }
                : json.type === 'evidence_assessment' ? { evidenceAssessment: payload }
                : ['hypotheses', 'planning_complete'].includes(json.type) ? { hypotheses: payload.hypotheses || [] }
                : ['report_draft', 'revision_complete'].includes(json.type) ? mergeScienceData(target.scienceData, payload)
                : { claimVerification: payload, claims: payload.claims || [] }
              target.scienceData = { ...target.scienceData, ...patch }
              let detail = researchDetailsRef.current.get('reviewing')
              if (!detail) {
                detail = { stepId: 'reviewing', stepType: 'reviewing', title: '假设与证据审核' }
                researchDetailsRef.current.set('reviewing', detail)
              }
              Object.assign(detail, target.scienceData)
              setResearchDataVersion(version => version + 1)
            }

            if (json.type === 'literature_progress') {
              const progress = json.content || json
              target.reactMode = true
              if (!target.reactSteps) target.reactSteps = []
              target.reactSteps.push({ step: target.reactSteps.length + 1, type: 'observation', content: progress.message || `文献采集：${progress.papers_count || 0} 篇，含摘要 ${progress.abstracts_count || 0} 篇`, success: true, timestamp: Date.now() })
              setResearchSteps(previous => previous.map(step => step.type === 'searching' ? { ...step, subtitle: progress.message || step.subtitle, stats: { ...step.stats, resultsCount: progress.papers_count || 0 } } : step))
            }

            // V2 研究完成事件
            if (json.type === 'research_complete') {
              console.log('研究完成事件:', json)
              target.scienceData = readScienceData(json)
              let scienceDetail = researchDetailsRef.current.get('reviewing')
              if (!scienceDetail) {
                scienceDetail = { stepId: 'reviewing', stepType: 'reviewing', title: '假设与证据审核' }
                researchDetailsRef.current.set('reviewing', scienceDetail)
              }
              Object.assign(scienceDetail, target.scienceData)
              if (json.charts?.length || json.knowledge_graph) {
                let analysis = researchDetailsRef.current.get('analyzing')
                if (!analysis) {
                  analysis = { stepId: 'analyzing', stepType: 'analyzing', title: '数据分析', charts: [] }
                  researchDetailsRef.current.set('analyzing', analysis)
                }
                analysis.charts = mergeCharts(analysis.charts, json.charts || [])
                target.charts = mergeCharts(target.charts, json.charts || [])
                if (json.knowledge_graph) analysis.knowledgeGraph = json.knowledge_graph
              }
              // 设置最终报告为内容
              if (json.final_report) {
                target.content = withQualityReviewNotice(json.final_report, json)
                console.log('设置报告内容，长度:', json.final_report.length)

                // 同时存储到研究详情中供"过程报告"tab显示 - 使用 stepType 作为 key
                const writingType = researchDetailsRef.current.has('writing') ? 'writing' : 'generating'
                const detail = researchDetailsRef.current.get(writingType)
                console.log(`[前端] research_complete: key=${writingType}, detail=${detail ? '找到' : '未找到'}`)
                if (detail) {
                  detail.streamingReport = target.content
                  setSelectedResearchDetail({ ...detail })
                  setResearchDataVersion(v => v + 1)
                  console.log(`[前端] research_complete: ✅ 报告已存储`)
                }
                // 打印所有 detail 的状态
                console.log(`[前端] research_complete: 所有 detail keys:`, Array.from(researchDetailsRef.current.keys()))
                researchDetailsRef.current.forEach((d, k) => {
                  console.log(`[前端] detail[${k}]: searchResults=${d.searchResults?.length || 0}, charts=${d.charts?.length || 0}, hasGraph=${!!d.knowledgeGraph}, hasReport=${!!d.streamingReport}`)
                })
              }
              // 设置引用
              if (json.references && json.references.length > 0) {
                target.reference = json.references.map(normalizeReference)
              }

              // Completion closes the run; it must not erase failed or unexecuted stages.
              setResearchSteps(prev => prev.map(s => ({ ...s, status: restoredStepStatus(s, { status: 'completed', state_json: json }),
                subtitle: s.type === 'reviewing' ? (reviewPresentation(json).passed ? '审核通过' : '执行结束，仍需核对审核问题') : s.subtitle })))
              // 确保触发重新计算
              console.log(`[前端] research_complete: ✅ 研究完成，强制触发 researchDataVersion 更新`)
              setResearchDataVersion(v => v + 1)
            }

            // 检测 ReAct 模式
            if (json.mode === 'react' || json.mode === 'optimized' || json.type === 'react_start') {
              target.reactMode = true
            }

            // 研究计划事件 (V1)
            if (json.type === 'plan' && json.understanding) {
              target.researchPlan = {
                understanding: json.understanding || '',
                strategy: json.strategy || '',
                subQueries: (json.sub_queries || []).map((sq: any) => ({
                  query: sq.query,
                  purpose: sq.purpose,
                  tool: sq.tool,
                })),
                expectedAspects: json.expected_aspects || [],
              }
              // 同时添加到 reactSteps 用于展示
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              target.reactSteps.push({
                step: 0,
                type: 'plan',
                content: `**研究计划**\n\n理解: ${json.understanding}\n\n策略: ${json.strategy}\n\n子查询:\n${(json.sub_queries || []).map((sq: any) => `• ${sq.query} (${sq.purpose})`).join('\n')}`,
                timestamp: Date.now(),
              })
            }

            // ReAct 事件处理 (兼容 V1 和 V2)
            if (json.type === 'thought') {
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              target.reactSteps.push({
                step: json.step || target.reactSteps.length + 1,
                type: 'thought',
                content: extractContent(json.content),
                timestamp: Date.now(),
              })
            } else if (json.type === 'action') {
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              // V2 格式的 action
              const actionContent = json.content || json
              const tool = actionContent.tool || json.tool
              const isParallel = tool === 'parallel_search'
              const queries = actionContent.queries || json.params?.queries || []
              const section = actionContent.section || ''

              let displayContent = ''
              if (isParallel) {
                displayContent = `并行搜索${section ? ` (${section})` : ''} ${queries.length} 个查询:\n${queries.map((q: string) => `• ${q}`).join('\n')}`
              } else {
                displayContent = `调用工具: ${tool}${section ? ` - ${section}` : ''}`
              }

              target.reactSteps.push({
                step: json.step || target.reactSteps.length + 1,
                type: 'action',
                content: displayContent,
                tool: tool,
                params: json.params || actionContent,
                queries: isParallel ? queries : undefined,
                timestamp: Date.now(),
              })
            } else if (json.type === 'observation') {
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              // V2 格式的 observation
              const obsContent = json.content || json
              let displayContent = ''

              if (typeof obsContent === 'object') {
                const parts = []
                if (obsContent.section) parts.push(`📑 ${obsContent.section}`)
                if (obsContent.facts_count) parts.push(`事实: ${obsContent.facts_count} 条`)
                if (obsContent.data_points_count) parts.push(`数据点: ${obsContent.data_points_count} 个`)
                if (obsContent.duplicates_removed) parts.push(`去重: ${obsContent.duplicates_removed} 条`)
                if (obsContent.insights && obsContent.insights.length > 0) {
                  parts.push(`洞察:\n${obsContent.insights.map((i: string) => `  • ${i}`).join('\n')}`)
                }
                if (obsContent.source_quality) parts.push(`来源质量: ${obsContent.source_quality}`)
                displayContent = parts.join('\n') || JSON.stringify(obsContent, null, 2)
              } else {
                displayContent = typeof json.result === 'string' ? json.result : JSON.stringify(json.result || obsContent)
              }

              const stepId = `obs_${Date.now()}_${target.reactSteps.length}`
              target.reactSteps.push({
                step: json.step || target.reactSteps.length + 1,
                type: 'observation',
                content: displayContent,
                tool: json.tool,
                queries: json.queries_executed,
                success: json.success !== false,
                timestamp: Date.now(),
                stepId, // 添加 stepId 用于关联详情
              })

              // 存储步骤详情用于右侧面板展示
              if (typeof obsContent === 'object') {
                const stepDetail: StepDetailData = {
                  stepId,
                  type: obsContent.agent || 'observation',
                  section: obsContent.section,
                  searchResults: obsContent.search_results,
                  extractedFacts: obsContent.extracted_facts,
                  dataPoints: obsContent.data_points,
                  insights: obsContent.insights,
                }
                stepDetailsRef.current.set(stepId, stepDetail)
                // 自动选中最新的步骤详情
                setSelectedStepDetail(stepDetail)
              }
            } else if (json.type === 'section_draft') {
              // V2 章节撰写完成事件
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              const content = json.content || json
              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'observation',
                content: `✍️ 章节「${content.section_title || '未知'}」撰写完成\n字数: ${content.word_count || 0}\n要点: ${(content.key_points || []).join('、')}`,
                timestamp: Date.now(),
              })
            } else if (json.type === 'section_content') {
              // V2 章节内容事件 - 用于"过程报告"tab的流式显示
              const content = json.content || json
              const sectionContent = content.content || ''
              const sectionTitle = content.section_title || ''

              if (sectionContent) {
                console.log(`section_content 收到章节「${sectionTitle}」，长度:`, sectionContent.length)

                // 使用 stepType 作为 key 查找或创建 detail
                const writingType = 'writing'

                // 如果没有找到写作步骤，创建一个（兜底逻辑）
                if (!researchStepsRef.current.find(s => s.type === writingType)) {
                  console.log('section_content: 未找到写作步骤，创建兜底步骤')
                  const newStep: ResearchStep = {
                    id: writingType,  // 使用 type 作为 id
                    type: writingType,
                    title: '✍️ 写作阶段',
                    subtitle: '撰写研究报告',
                    status: 'running',
                  }
                  setResearchSteps(prev => {
                    const updated = [...prev, newStep]
                    researchStepsRef.current = updated
                    return updated
                  })
                }

                // 获取或创建详情 - 使用 stepType 作为 key
                let detail = researchDetailsRef.current.get(writingType)
                if (!detail) {
                  console.log(`section_content: 未找到详情，创建: ${writingType}`)
                  detail = {
                    stepId: writingType,
                    stepType: writingType,
                    title: '写作阶段',
                    streamingReport: '',
                    searchResults: [],
                    charts: [],
                    sections: [],  // 初始化 sections 数组
                  }
                  researchDetailsRef.current.set(writingType, detail)
                }

                // 添加章节到 sections 数组
                const sectionId = content.section_id || `section_${Date.now()}`
                if (!detail.sections) {
                  detail.sections = []
                }
                // 检查是否已存在，避免重复
                const existingIndex = detail.sections.findIndex(s => s.id === sectionId)
                if (existingIndex >= 0) {
                  detail.sections[existingIndex] = {
                    id: sectionId,
                    title: sectionTitle,
                    content: sectionContent,
                    wordCount: sectionContent.length,
                  }
                } else {
                  detail.sections.push({
                    id: sectionId,
                    title: sectionTitle,
                    content: sectionContent,
                    wordCount: sectionContent.length,
                  })
                }
                console.log(`section_content: 已添加章节「${sectionTitle}」到 sections，当前数量: ${detail.sections.length}`)

                // 累加章节内容到 streamingReport（保持向后兼容）
                const existingContent = detail.streamingReport || ''
                const newContent = existingContent
                  ? `${existingContent}\n\n## ${sectionTitle}\n\n${sectionContent}`
                  : `## ${sectionTitle}\n\n${sectionContent}`
                detail.streamingReport = newContent
                setSelectedResearchDetail({ ...detail })
                setResearchDataVersion(v => v + 1)

                // 同时添加到 reactSteps
                if (!target.reactSteps) {
                  target.reactSteps = []
                }
                target.reactSteps.push({
                  step: target.reactSteps.length + 1,
                  type: 'observation',
                  content: `✍️ 章节「${sectionTitle}」已写入过程报告\n字数: ${sectionContent.length}\n要点: ${(content.key_points || []).slice(0, 2).join('、') || '无'}`,
                  timestamp: Date.now(),
                })
              }
            } else if (json.type === 'report_draft') {
              // V2 报告草稿完成事件
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              const eventContent = json.content || json
              const reportContent = typeof eventContent === 'string' ? eventContent : eventContent.content || ''

              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'observation',
                content: `📝 研究报告撰写完成\n字数: ${eventContent.word_count || reportContent.length || 0}\n引用数: ${eventContent.references_count || 0}`,
                timestamp: Date.now(),
              })

              // 存储报告内容到 streamingReport 用于"过程报告"tab显示 - 使用 stepType 作为 key
              if (reportContent) {
                console.log('report_draft 收到报告内容，长度:', reportContent.length)
                const writingType = researchDetailsRef.current.has('writing') ? 'writing' : 'generating'
                const detail = researchDetailsRef.current.get(writingType)
                if (detail) {
                  detail.streamingReport = reportContent
                  setSelectedResearchDetail({ ...detail })
                  setResearchDataVersion(v => v + 1)
                }
                // 同时设置为聊天消息内容
                target.content = reportContent
              }

              // 标记写作步骤完成
              setResearchSteps(prev => prev.map(s =>
                s.type === 'writing' || s.type === 'generating'
                  ? { ...s, status: 'completed' as const }
                  : s
              ))
            } else if (json.type === 'review') {
              // V2 审核反馈事件
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              const content = json.content || json
              const review = reviewPresentation(content)
              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'thought',
                content: review.text,
                timestamp: Date.now(),
              })

              // 更新审核步骤状态
              setResearchSteps(prev => prev.map(s =>
                s.type === 'reviewing'
                  ? { ...s, subtitle: review.unconfirmed ? '质量审核待确认' : s.subtitle,
                    status: review.passed || review.unconfirmed ? 'completed' as const : 'running' as const }
                  : s
              ))
            } else if (json.type === 'revision_complete') {
              // V2 修订完成事件
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              const content = json.content || json
              if (typeof content.content === 'string') target.content = content.content
              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'observation',
                content: revisionPresentation(content.changes_count),
                timestamp: Date.now(),
              })
            } else if (json.type === 'error') {
              // V2 错误事件
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'thought',
                content: `❌ 错误: ${extractContent(json.content)}`,
                timestamp: Date.now(),
              })
              setResearchSteps(previous => previous.map(step => step.status === 'running'
                ? { ...step, status: 'failed' as const, subtitle: '阶段失败，请查看错误与检查点状态' } : step))
            } else if (json.type === 'research_cancelled') {
              // 研究被取消事件
              console.log('[前端] 收到 research_cancelled 事件')
              if (!target.reactSteps) {
                target.reactSteps = []
              }
              target.reactSteps.push({
                step: target.reactSteps.length + 1,
                type: 'thought',
                content: `⏹️ 研究已被用户取消`,
                timestamp: Date.now(),
              })
              target.loading = false
              if (!target.content) {
                target.content = '⏹️ 研究已被用户取消'
              }
              setResearchSteps(prev => prev.map(s => s.status === 'running'
                ? { ...s, status: 'paused' as const, subtitle: json.checkpoint_saved ? '已暂停并保存检查点' : '已暂停，检查点状态待确认' } : s))
            } else if (json.type === 'chart') {
              // 解包 content（后端将数据包在 content 里）
              const content = json.content || json
              console.log(`[前端] 收到 chart 事件 (单个图表)`)
              console.log(`[前端] chart 内容: title=${content.title}, has_echarts=${!!content.echarts_option}, has_image=${!!(content.image || content.image_base64)}`)

              // 构建图表对象
              const chartObj = {
                id: content.id || content.chart_id || uniqueId('chart_'),
                type: content.chart_type || 'generated',
                title: content.title || '数据图表',
                echarts_option: content.echarts_option,
                image_base64: content.image || content.image_base64,
                data: content.data,
              }

              // 存入 target.charts（供报告使用）
              if (!target.charts) {
                target.charts = []
              }
              target.charts = mergeCharts(target.charts, [chartObj])
              console.log(`[前端] 图表已添加到 target.charts，总数: ${target.charts?.length || 0}`)

              // 同时存入 research detail（供可视化面板使用）- 使用 stepType 作为 key
              const detail = researchDetailsRef.current.get('analyzing')
              console.log(`[前端] 查找 analyzing detail: ${detail ? '找到' : '未找到'}`)
              if (detail) {
                if (!detail.charts) {
                  detail.charts = []
                }
                detail.charts = mergeCharts(detail.charts, [chartObj])
                setResearchSteps(prev => prev.map(s =>
                  s.type === 'analyzing'
                    ? { ...s, stats: { ...s.stats, chartsCount: detail.charts?.length || 0 } }
                    : s
                ))
                setSelectedResearchDetail({ ...detail })
                setResearchDataVersion(v => v + 1)
                console.log(`[前端] ✅ chart 已存储到 detail.charts，总数: ${detail.charts.length}`)
              } else {
                console.warn(`[前端] ⚠️ 未找到 analyzing detail，图表可能无法显示在可视化面板`)
              }
            } else if (json.type === 'stock_quote') {
              // 股票实时行情
              const content = json.content || json
              target.stockQuote = {
                code: content.code,
                name: content.name,
                price: content.price,
                change: content.change,
                change_percent: content.change_percent,
                high: content.high,
                low: content.low,
                volume: content.volume,
                turnover: content.turnover,
                open: content.open,
                prev_close: content.prev_close,
              }
            } else if (json.type === 'data_insight') {
              if (!target.insights) {
                target.insights = []
              }
              target.insights.push(...(json.insights || []))
            } else if (['status', 'search_results', 'thinking_step'].includes(json.type)) {
              // 兼容原有状态事件
              if (!target.thinks) {
                target.thinks = []
              }

              const lastThink = target.thinks[target.thinks.length - 1]

              if (lastThink?.type === json.type) {
                lastThink.results!.push({
                  id: uniqueId('think_result'),
                  content: json.subquery || json.content,
                  count: json.count,
                })
              } else {
                target.thinks.push({
                  id: uniqueId('think_result'),
                  type: json.type as 'status' | 'search_results',
                  results: [
                    {
                      id: uniqueId('think_result'),
                      content: json.subquery || json.content,
                      count: json.count,
                    },
                  ],
                })
              }
            } else if (json.type === 'search_result_item') {
              if (!target.search_results) {
                target.search_results = []
              }

              try {
                target.search_results.push({
                  ...json.result,
                  id: uniqueId('search-results'),
                  host: json.result?.url ? new URL(json.result.url).host : '',
                })
              } catch (e) {
                console.debug('Parse URL error', e)
              }
            } else if (json.type === 'thinking') {
              target.think = `${target.think || ''}${json.content || ''}`
            } else if (['answer', 'final_answer'].includes(json.type)) {
              target.content = `${target.content}${json.content || ''}`
            } else if (json.type === 'reference_materials') {
              target.reference = json.content?.map((o: any) => ({
                id: o.reference_id,
                title: o.name,
                link: o.url,
                content: o.summary,
                source: o.source === 'local' ? 'knowledge' : 'web',
              }))
            }
          } else {
            if (json?.content) {
              if (json.thinking) {
                target.think = `${target.think || ''}${json.content || ''}`
              } else {
                target.content = `${target.content || ''}${json.content || ''}`
              }
            }

            if (json?.documents?.length) {
              target.reference = json.documents
            }

            if (json?.image_results) {
              target.image_results = json.image_results
            }
          }
        } catch {
          console.debug('解析失败')
          console.debug(slice)
        }
      }
    },
    [chat, id, refreshCheckpointInfo],
  )

  const send = useCallback(
    async (message: string, attachmentIds?: string[]) => {
      if (loadingRef.current || stoppingRef.current || sendPendingRef.current !== null || resumeLock.current || !id) return
      if (!message && (!attachmentIds || attachmentIds.length === 0)) return
      const sendSession = id
      const sendGeneration = ++operationGenerationRef.current
      sendPendingRef.current = sendGeneration
      const isCurrentSend = () => activeSessionRef.current === sendSession && operationGenerationRef.current === sendGeneration
      try {
        if (!profileLoadedRef.current) await loadCheckpointRef.current()
        if (!isCurrentSend()) return
        if (!profileLoadedRef.current) {
          uiMessage.error('研究模式加载失败，请刷新后重试')
          return
        }
        if ((deviceState.searchModes as string[]).length > 0 && (checkpointInfo || restoredCheckpointRef.current)) {
          Modal.confirm({
            title: '本会话已有研究，不能覆盖原检查点',
            content: '新问题请新建独立研究；要补充或修订当前报告，请使用工具栏的“继续研究”或“追加复核”。原报告、证据与预算将保留。',
            okText: '新建研究', cancelText: '保留当前研究',
            onOk: () => navigate(`/chat?mode=${researchProfileRef.current || 'science'}&prompt=${encodeURIComponent(message)}`),
          })
          return
        }
        if ((restoredCheckpointRef.current || initialProfile) && deviceState.searchModes.length === 0) {
          // Keep research-mode requests on the six-agent path. Removing all
          // sources must not silently turn a study into an ordinary chat.
          uiMessage.warning('请至少选择网络搜索或本地知识库后开始调研')
          return
        }

        chat.list.push({
          id: createChatId(),
          role: ChatRole.User,
          type: ChatType.Normal,
          content: message || '(附件问答)',
        })

        chat.list.push({
          id: createChatId(),
          role: ChatRole.Assistant,
          type: (deviceState.searchModes as string[]).length > 0 ? ChatType.Deepsearch : ChatType.Normal,
          content: '',
        })
        scrollToBottom()
        const target = chat.list[chat.list.length - 1]
        target.loading = true

        // 保存用户消息到数据库
        if (id) {
          try {
            await api.session.addMessage(id, {
              role: 'user',
              content: message || '(附件问答)',
            })
          } catch (e) {
            console.error('Failed to save user message:', e)
          }
        }
        if (!isCurrentSend()) {
          target.loading = false
          return
        }

        await sendChat(target, message || '请分析附件内容', attachmentIds)
        if (!isCurrentSend()) return

        // 保存助手回复到数据库
        if (id && target.content) {
          try {
            await api.session.addMessage(id, {
              role: 'assistant',
              content: target.content,
              thinking: target.think,
              references_data: { references: target.reference || [], science_data: target.scienceData, charts: target.charts },
            })
          } catch (e) {
            console.error('Failed to save assistant message:', e)
          }
        }

        // 发送后清空附件列表
        if (isCurrentSend() && attachmentIds && attachmentIds.length > 0) {
          setAttachments([])
        }
      } finally {
        if (sendPendingRef.current === sendGeneration) sendPendingRef.current = null
      }
    },
    [chat, sendChat, id, checkpointInfo, initialProfile, navigate],
  )
  const hasSentInitialMessage = useRef(false)
  // The transport hook retains its initial value while this route component is
  // reused. Track consumption across ID changes so returning through history
  // cannot replay that query or skip loading the saved conversation.
  const consumedInitialSessions = useRef(new Set<string>())
  const hasLoadedCheckpoint = useRef(false)
  const hasLoadedMessages = useRef(false)
  const previousIdRef = useRef<string | undefined>(undefined)

  // 当 session ID 变化时，重置加载状态
  useEffect(() => {
    if (id !== previousIdRef.current) {
      operationGenerationRef.current += 1
      sendPendingRef.current = null
      stoppingRef.current = false
      setStopping(false)
      streamScopeRef.current.close()
      void readerRef.current?.cancel().catch(() => {})
      readerRef.current = null
      currentSessionIdRef.current = null
      resumeLock.current = false
      setResuming(false)
      setReviewOpen(false)
      setReviewNotes('')
      setReviewClaimIds([])
      console.log('[会话切换] 从', previousIdRef.current, '切换到', id)
      previousIdRef.current = id
      hasLoadedMessages.current = false
      hasLoadedCheckpoint.current = false
      hasSentInitialMessage.current = false
      // 清空消息列表和研究状态
      console.log(`[前端] ⚠️ 会话切换: 清空 researchDetailsRef`)
      chat.list.length = 0
      setResearchSteps([])
      researchStepsRef.current = []
      researchDetailsRef.current.clear()
      setSelectedResearchDetail(null)
      setResearchDataVersion(0)
      setCurrentChatItem(null)
      setCheckpointInfo(null)
      restoredCheckpointRef.current = null
      const nextProfile = ctx && ctx.data.sessionId === id ? ctx.data.profileId : null
      researchProfileRef.current = nextProfile
      profileLoadedRef.current = !!nextProfile
      setProfileId(nextProfile)
    }
  }, [id, chat, restoreAssistantFromCheckpoint])

  // 加载会话历史消息
  useEffect(() => {
    if (!id || hasLoadedMessages.current) return
    const viewGeneration = viewIdentityRef.current.generation
    const operationGeneration = operationGenerationRef.current
    // NewChat created this session for the pending request. A concurrent
    // history response must not replace its in-flight user/assistant items.
    if (ctx && ctx.data.sessionId === id && !consumedInitialSessions.current.has(ctx.data.sessionId)
      && (ctx.data.message || ctx.data.attachmentIds?.length)) {
      hasLoadedMessages.current = true
      return
    }

    // 辅助函数：将消息数组填充到 chat.list
    function populateMessages(messages: any[]) {
      chat.list.length = 0
      for (const msg of messages) {
        const chatItem: API.ChatItem = {
          id: createChatId(),
          role: msg.role === 'user' ? ChatRole.User : ChatRole.Assistant,
          type: msg.role === 'assistant' && msg.content?.length > 1000 ? ChatType.Deepsearch : ChatType.Normal,
          content: msg.content || '',
        }

        // 恢复助手消息的额外数据
        if (msg.role === 'assistant') {
          if (msg.thinking) {
            chatItem.think = msg.thinking
          }
          if (msg.references_data?.science_data) chatItem.scienceData = msg.references_data.science_data as any
          if (msg.references_data?.charts) chatItem.charts = msg.references_data.charts as any
          if (msg.references_data?.references) {
            chatItem.reference = msg.references_data.references as any
          }
        }

        chat.list.push(chatItem)
      }
      if (restoredCheckpointRef.current) restoreAssistantFromCheckpoint(restoredCheckpointRef.current)
      else setCurrentChatItem(chat.list.filter(item => item.role === ChatRole.Assistant).pop() || null)
    }

    // 优先使用 store 中预加载的数据
    const cachedSession = sessionState.currentSession
    if (cachedSession && cachedSession.id === id && cachedSession.messages?.length > 0) {
      console.log('[加载消息] 使用预加载的数据:', cachedSession.messages.length, '条')
      hasLoadedMessages.current = true
      populateMessages(cachedSession.messages)
      return
    }

    // 否则从 API 加载
    async function loadSessionMessages() {
      try {
        console.log('[加载消息] 开始加载会话消息:', id)
        const res = await api.session.getSession(id!)
        const session = (res as any).data || res
        if (activeSessionRef.current !== id || viewIdentityRef.current.generation !== viewGeneration
          || operationGenerationRef.current !== operationGeneration) return

        if (session && session.messages && session.messages.length > 0) {
          hasLoadedMessages.current = true
          console.log('[加载消息] 找到消息:', session.messages.length, '条')
          populateMessages(session.messages)
          console.log('[加载消息] 消息恢复完成')
        }
      } catch (e) {
        console.log('[加载消息] 加载失败或无消息:', e)
      }
    }

    loadSessionMessages()
  }, [id, chat, restoreAssistantFromCheckpoint, ctx])

  // 加载并恢复研究检查点状态
  useEffect(() => {
    if (!id || hasLoadedCheckpoint.current) return
    const viewGeneration = viewIdentityRef.current.generation

    async function loadCheckpoint() {
      const operationGeneration = operationGenerationRef.current
      try {
        console.log('[恢复状态] 开始加载检查点, session_id:', id)
        const res = await api.session.getFullResearchCheckpoint(id!)
        const response = (res as any).data || res
        if (activeSessionRef.current !== id || viewIdentityRef.current.generation !== viewGeneration
          || operationGenerationRef.current !== operationGeneration) return
        console.log('[恢复状态] API响应:', { success: response?.success, hasCheckpoint: !!response?.checkpoint })
        if (response?.success && response?.checkpoint) {
          const checkpoint = response.checkpoint
          const savedProfile = checkpointResearchProfile(checkpoint.state_json)
          researchProfileRef.current = savedProfile
          profileLoadedRef.current = true
          setProfileId(savedProfile)
          restoredCheckpointRef.current = checkpoint
          setCheckpointInfo(checkpoint)
          // The generation checks above prevent late history for A from
          // replacing the selector of B (or a newly created research session).
          const savedSearchSelection = checkpointSearchSelection(checkpoint, id!)
          if (savedSearchSelection) {
            deviceActions.setKnowledgeBaseName(savedSearchSelection.knowledgeBase?.name || '')
            deviceActions.setSearchModes(savedSearchSelection.modes)
          }
          console.log('[恢复状态] 检查点详情:', {
            phase: checkpoint.phase,
            status: checkpoint.status,
            hasStateJson: !!checkpoint.state_json,
            hasUiStateJson: !!checkpoint.ui_state_json,
            hasFinalReport: !!checkpoint.final_report,
          })

          // 保留已暂停/失败研究的现有产物，用户可主动从检查点继续。
          if (['completed', 'running', 'paused', 'failed'].includes(checkpoint.status)) {
            hasLoadedCheckpoint.current = true

            // 恢复 UI 状态
            const uiState = checkpointDisplayState(checkpoint)
            const stateJson = (checkpoint.state_json || {}) as any

            console.log('[恢复状态] UI状态:', {
              steps: uiState?.research_steps?.length || 0,
              searchResults: uiState?.search_results?.length || 0,
              charts: uiState?.charts?.length || 0,
              hasKnowledgeGraph: !!uiState?.knowledge_graph,
              hasReport: !!uiState?.streaming_report,
            })

            // 恢复研究步骤 - 如果没有步骤数据，创建默认步骤
            let steps: ResearchStep[] = []
            if (uiState?.research_steps && uiState.research_steps.length > 0) {
              steps = uiState.research_steps.map((s: any) => ({
                id: s.type === 'researching' ? 'searching' : s.type || `step_${Date.now()}`,
                type: (s.type === 'researching' ? 'searching' : s.type) as ResearchStep['type'],
                title: s.title || s.type || '',
                subtitle: s.subtitle || '',
                status: restoredStepStatus(s, checkpoint),
                stats: s.stats,
              }))
            } else {
              // Legacy checkpoints may lack step telemetry. Do not invent successful stages.
              const phase = checkpoint.phase === 'researching' ? 'searching' : checkpoint.phase
              if (['planning', 'searching', 'analyzing', 'writing', 'reviewing', 're_researching', 'revising'].includes(phase)) {
                steps = [{ id: phase, type: phase as ResearchStep['type'], title: phase,
                  subtitle: '历史检查点未记录完整阶段进度',
                  status: restoredStepStatus({ type: phase, status: checkpoint.status }, checkpoint) }]
              }
            }

            setResearchSteps(steps)
            researchStepsRef.current = steps

            // 初始化详情数据 - 使用 stepType 作为 key
            steps.forEach(step => {
              const detail: ResearchDetailData = {
                stepId: step.type,  // 使用 type 作为 ID
                stepType: step.type,
                title: step.title || step.type,
                searchResults: [],
                charts: [],
              }
              researchDetailsRef.current.set(step.type, detail)  // 使用 type 作为 key
            })
            console.log('[恢复状态] 已创建步骤详情:', researchDetailsRef.current.size, '个')
            for (const step of ['analyzing', 'writing'] as const) {
              if (!researchDetailsRef.current.has(step)) researchDetailsRef.current.set(step, { stepId: step, stepType: step, title: step === 'writing' ? '研究综述' : '数据分析', charts: [] })
            }
            const writingDetail = researchDetailsRef.current.get('writing')!
            writingDetail.sections = Object.entries(stateJson.draft_sections || {}).map(([sectionId, content]) => ({
              id: sectionId,
              title: (stateJson.science_sections || stateJson.outline || []).find((section: any) => section.id === sectionId)?.title || sectionId,
              content: String(content),
            }))


            if (uiState) {

              // 恢复搜索结果 - 使用 stepType 作为 key
              if (uiState.search_results && uiState.search_results.length > 0) {
                const searchingType = researchDetailsRef.current.has('searching') ? 'searching' : 'researching'
                const detail = researchDetailsRef.current.get(searchingType)
                if (detail) {
                  detail.searchResults = uiState.search_results.map((r: any, i: number) => ({
                    ...r,
                    id: r.id || `sr_${i}`,
                    title: r.title || r.source_name || '',
                    source: r.source || 'web',
                    url: r.url || r.source_url || '',
                    snippet: r.snippet || r.content || '',
                    date: r.date || '',
                  }))
                  console.log('[恢复状态] 恢复搜索结果:', detail.searchResults?.length || 0, '条')
                }
              }

              // 恢复知识图谱 - 使用 stepType 作为 key
              if (uiState.knowledge_graph && (uiState.knowledge_graph.nodes?.length > 0 || uiState.knowledge_graph.edges?.length > 0)) {
                const targetType = researchDetailsRef.current.has('analyzing') ? 'analyzing'
                  : researchDetailsRef.current.has('researching') ? 'researching' : 'searching'
                const detail = researchDetailsRef.current.get(targetType)
                if (detail) {
                  detail.knowledgeGraph = uiState.knowledge_graph
                  console.log('[恢复状态] 恢复知识图谱:', uiState.knowledge_graph.nodes?.length || 0, '节点')
                }
              }

              // 恢复图表 - 使用 stepType 作为 key
              if (uiState.charts && uiState.charts.length > 0) {
                const detail = researchDetailsRef.current.get('analyzing')
                if (detail) {
                  detail.charts = uiState.charts
                  console.log('[恢复状态] 恢复图表:', uiState.charts.length, '个')
                }
              }

              // 恢复报告 - 使用 stepType 作为 key
              if (uiState.streaming_report || checkpoint.final_report) {
                const detail = researchDetailsRef.current.get('writing')
                if (detail) {
                  detail.streamingReport = withQualityReviewNotice(uiState.streaming_report || checkpoint.final_report || '', stateJson)
                  console.log('[恢复状态] 恢复报告长度:', detail.streamingReport?.length || 0)
                }
              }

            }

            const scienceData = readScienceData({ ...stateJson, ...uiState })
            let scienceDetail = researchDetailsRef.current.get('reviewing')
            if (!scienceDetail) {
              scienceDetail = { stepId: 'reviewing', stepType: 'reviewing', title: '假设与证据审核' }
              researchDetailsRef.current.set('reviewing', scienceDetail)
            }
            Object.assign(scienceDetail, scienceData)

            // 触发数据更新
            setResearchDataVersion(v => v + 1)

            // Messages and checkpoints may arrive in either order; restore the same final assistant.
            if (!chat.list.some(item => item.role === ChatRole.User)) {
              chat.list.push({ id: createChatId(), role: ChatRole.User, type: ChatType.Normal, content: checkpoint.query || '' })
            }
            restoreAssistantFromCheckpoint(checkpoint)

            // 最终状态汇总
            const finalSummary: Record<string, any> = {
              stepsCount: researchStepsRef.current.length,
              detailsCount: researchDetailsRef.current.size,
              chatListLength: chat.list.length,
            }
            researchDetailsRef.current.forEach((detail, stepId) => {
              finalSummary[`detail_${stepId}`] = {
                searchResults: detail.searchResults?.length || 0,
                charts: detail.charts?.length || 0,
                hasKnowledgeGraph: !!detail.knowledgeGraph,
                hasReport: !!detail.streamingReport,
              }
            })
            console.log('[恢复状态] ✅ 恢复完成，最终状态:', finalSummary)
          }
        } else {
          console.log('[恢复状态] 未找到有效检查点')
          // New empty sessions have no checkpoint yet. Preserve a transported
          // selection if present; ordinary legacy chat sessions default science.
          if (response?.success === true || response?.message === 'No checkpoint found') {
            const nextProfile = researchProfileRef.current || 'science'
            researchProfileRef.current = nextProfile
            profileLoadedRef.current = true
            setProfileId(nextProfile)
          }
        }
      } catch (e) {
        console.log('[恢复状态] 加载失败:', e)
      }
    }

    loadCheckpointRef.current = loadCheckpoint
    loadCheckpoint()
  }, [id, chat, restoreAssistantFromCheckpoint])

  const handleResume = async (options: api.session.ResumeResearchOptions = {}) => {
    if (!id || loadingRef.current || stoppingRef.current || sendPendingRef.current !== null || resumeLock.current) return
    const resumeSession = id
    const resumeGeneration = ++operationGenerationRef.current
    const isCurrentResume = () => activeSessionRef.current === resumeSession && operationGenerationRef.current === resumeGeneration
    resumeLock.current = true
    setResuming(true)
    try {
      await loadCheckpointRef.current()
      if (!isCurrentResume()) return
      const resumeCheckpoint = restoredCheckpointRef.current
      const target: API.ChatItem = { id: createChatId(), role: ChatRole.Assistant, type: ChatType.Deepsearch, content: '',
        scienceData: resumeCheckpoint?.session_id === resumeSession
          ? readScienceData(checkpointDisplayState(resumeCheckpoint)) : undefined }
      chat.list.push(target)
      const liveTarget = chat.list[chat.list.length - 1]
      setReviewOpen(false)
      await sendChat(liveTarget, checkpointInfo?.query || '', undefined, true, options)
      if (!isCurrentResume()) return
      if (liveTarget.content) await api.session.addMessage(id, { role: 'assistant', content: liveTarget.content,
        thinking: liveTarget.think, references_data: { references: liveTarget.reference || [], science_data: liveTarget.scienceData, charts: liveTarget.charts } })
    } catch (error: any) {
      if (isCurrentResume()) uiMessage.error(await getRequestErrorMessage(error, '恢复研究失败，请重试'))
    } finally {
      if (isCurrentResume()) {
        resumeLock.current = false
        setResuming(false)
        await refreshCheckpointInfo()
      }
    }
  }

  const handleSaveMemory = async () => {
    if (!id || loadingRef.current || savingMemory) return
    setSavingMemory(true)
    try {
      const response = await api.memory.createMemory(id)
      if (response.data.warning) uiMessage.warning(`已保存。${response.data.warning}`)
      else uiMessage.success('已保存为记忆，可在记忆库查看')
    } catch (error: any) {
      uiMessage.error(error?.response?.data?.detail || error?.message || '保存记忆失败')
    } finally { setSavingMemory(false) }
  }

  useEffect(() => {
    if (ctx && ctx.data.sessionId === id && !consumedInitialSessions.current.has(ctx.data.sessionId)
      && (ctx.data.message || ctx.data.attachmentIds?.length) && !hasSentInitialMessage.current) {
      hasSentInitialMessage.current = true
      consumedInitialSessions.current.add(ctx.data.sessionId)
      send(ctx.data.message, ctx.data.attachmentIds)
    }
  }, [ctx, send, id])

  useEffect(() => {
    const handleScroll = () => {
      const anchors: {
        id: string
        top: number
        item: API.ChatItem
      }[] = []

      chat.list
        .filter((o) => o.type === ChatType.Deepsearch)
        .forEach((item, index) => {
          const id = createChatIdText(item.id)
          const dom = document.getElementById(id)
          if (!dom) return

          const top = dom.offsetTop
          if (index === 0 || top < window.scrollY) {
            anchors.push({ id, top, item })
          }
        })

      if (anchors.length) {
        const current = anchors.reduce((prev, curr) =>
          curr.top > prev.top ? curr : prev,
        )

        setCurrentChatItem(current.item)
      }
    }

    window.addEventListener('scroll', handleScroll)

    return () => {
      window.removeEventListener('scroll', handleScroll)
    }
  }, [])

  // 处理步骤点击，切换显示详情 (旧版)
  const handleStepClick = useCallback((stepId: string) => {
    const detail = stepDetailsRef.current.get(stepId)
    if (detail) {
      setSelectedStepDetail(detail)
    }
  }, [])

  // 处理研究步骤点击 (新版)
  const handleResearchStepClick = useCallback((stepId: string) => {
    const detail = researchDetailsRef.current.get(stepId)
    if (detail) {
      setSelectedResearchDetail(detail)
    }
  }, [])

  // 判断是否在深度研究模式（只要是 Deepsearch 类型就启用宽布局）
  const isDeepResearchMode = currentChatItem?.type === ChatType.Deepsearch

  // 调试日志：跟踪 currentChatItem 变化
  useEffect(() => {
    console.log('[前端] currentChatItem 变化:', {
      hasItem: !!currentChatItem,
      type: currentChatItem?.type,
      isDeepsearch: currentChatItem?.type === ChatType.Deepsearch,
      ChatTypeDeepsearch: ChatType.Deepsearch,
    })
  }, [currentChatItem])

  // 聚合所有研究步骤的数据，用于在tab中显示完整信息
  const aggregatedResearchData = useMemo(() => {
    console.log(`[前端] ========== 计算 aggregatedResearchData ==========`)
    console.log(`[前端] isDeepResearchMode=${isDeepResearchMode}, detailsSize=${researchDetailsRef.current.size}, version=${researchDataVersion}`)
    console.log(`[前端] currentChatItem?.type=${currentChatItem?.type}, ChatType.Deepsearch=${ChatType.Deepsearch}`)
    console.log(`[前端] researchSteps=`, researchSteps.map(s => s.type))
    console.log(`[前端] detail keys=`, Array.from(researchDetailsRef.current.keys()))

    if (!isDeepResearchMode || researchDetailsRef.current.size === 0) {
      console.log(`[前端] ⚠️ 跳过聚合: isDeepResearchMode=${isDeepResearchMode}, size=${researchDetailsRef.current.size}`)
      return null
    }

    // 从所有步骤中收集数据
    let allSearchResults: ResearchDetailData['searchResults'] = []
    let knowledgeGraph: ResearchDetailData['knowledgeGraph'] = undefined
    let allCharts: ResearchDetailData['charts'] = []
    let streamingReport = ''
    let allSections: ResearchDetailData['sections'] = []
    let scienceData = {} as import('@/api/research-types').ScienceResearchData

    researchDetailsRef.current.forEach((detail, stepId) => {
      console.log(`[前端] 聚合步骤 ${stepId}: searchResults=${detail.searchResults?.length || 0}, charts=${detail.charts?.length || 0}, hasGraph=${!!detail.knowledgeGraph}, hasReport=${!!detail.streamingReport}, sections=${detail.sections?.length || 0}`)

      for (const field of ['papers', 'evidenceLedger', 'claims', 'claimVerification', 'evidenceAssessment', 'hypotheses', 'outcome', 'reviewVerdict', 'stopReason'] as const) {
        if (detail[field] !== undefined) scienceData = { ...scienceData, [field]: detail[field] }
      }
      // 收集搜索结果
      if (detail.searchResults && detail.searchResults.length > 0) {
        allSearchResults = [...allSearchResults!, ...detail.searchResults]
      }
      // 取最新的知识图谱
      if (detail.knowledgeGraph) {
        knowledgeGraph = detail.knowledgeGraph
      }
      // 收集图表
      if (detail.charts && detail.charts.length > 0) {
        allCharts = [...allCharts!, ...detail.charts]
      }
      // 取最新的流式报告
      if (detail.streamingReport) {
        streamingReport = detail.streamingReport
      }
      // 收集章节草稿
      if (detail.sections && detail.sections.length > 0) {
        allSections = [...allSections!, ...detail.sections]
      }
    })

    console.log(`[前端] 聚合结果: searchResults=${allSearchResults.length}, charts=${allCharts.length}, hasGraph=${!!knowledgeGraph}, hasReport=${!!streamingReport}, sections=${allSections.length}`)

    // 创建聚合的数据对象
    const aggregated: ResearchDetailData = {
      stepId: selectedResearchDetail?.stepId || 'aggregated',
      stepType: selectedResearchDetail?.stepType || 'aggregated',
      title: selectedResearchDetail?.title || '研究详情',
      subtitle: selectedResearchDetail?.subtitle,
      ...scienceData,
      searchResults: [...new Map(allSearchResults.map(result => [result.source_id || result.evidence_id || result.url || result.id, result])).values()],
      knowledgeGraph,
      charts: mergeCharts([], allCharts),
      streamingReport,
      sections: allSections,
    }

    return aggregated
  }, [isDeepResearchMode, selectedResearchDetail, researchSteps, researchDataVersion])  // researchSteps/version 变化时重新计算

  // 确定右侧面板显示内容
  const rightPanelContent = useMemo(() => {
    // 新版: 深度研究模式，显示研究详情面板
    if (isDeepResearchMode) {
      return (
        <ClaimEvidenceBoundary data={aggregatedResearchData}><ResearchDetail
          data={aggregatedResearchData}
          steps={researchSteps}
          onStepClick={handleResearchStepClick}
          onClose={() => setSelectedResearchDetail(null)}
        /></ClaimEvidenceBoundary>
      )
    }
    // 旧版: 如果当前在深度搜索模式且有步骤详情，显示旧的步骤详情面板
    if (currentChatItem?.type === ChatType.Deepsearch && (selectedStepDetail || currentChatItem?.reactSteps?.length)) {
      return <StepDetailPanel detail={selectedStepDetail} />
    }
    // 否则显示搜索来源
    if (currentChatItem?.search_results?.length) {
      return (
        <Drawer title="搜索来源">
          <Source list={currentChatItem.search_results} />
        </Drawer>
      )
    }
    return null
  }, [currentChatItem, selectedStepDetail, isDeepResearchMode, aggregatedResearchData, researchSteps, handleResearchStepClick])

  const checkpointState = checkpointInfo?.state_json || {}
  const reviewClaims = (Array.isArray(checkpointState.claims) ? checkpointState.claims : aggregatedResearchData?.claims || []) as Claim[]
  const extraAvailable = Math.max(0, 2 - Number(checkpointState.review_extension_rounds || 0))
  const remainingReviewBudget = Math.max(0, Number(checkpointState.max_iterations || 0) - Number(checkpointState.iteration || 0))
  const mayUseRemaining = Number(checkpointState.review_extension_rounds || 0) > 0 && remainingReviewBudget > 0
  const openReview = () => {
    setAdditionalIterations(Math.max(1, Math.min(extraAvailable, 1)))
    setUseRemainingBudget(extraAvailable === 0 && mayUseRemaining)
    setReviewOpen(true)
  }

  return (
    <ComPageLayout
      sender={
        <>
          <ComSender
            loading={loading || stopping}
            requireSearch={!!checkpointInfo || !!initialProfile}
            placeholder={profileId === 'industry' ? '继续提问行业、企业或风险问题；Enter 开始，Shift + Enter 换行' : '继续描述研究问题；Enter 开始，Shift + Enter 换行'}
            attachments={attachments}
            onSend={send}
            onStop={handleStop}
            onUploadAttachment={handleUploadAttachment}
            onRemoveAttachment={handleRemoveAttachment}
          />
        </>
      }
      right={rightPanelContent}
      wideRight={isDeepResearchMode}
    >
      <div className={styles['chat-page']}>
        <Space wrap className={styles['chat-toolbar']}>
          {profileId && (checkpointInfo || initialProfile) && <Tag color={profileId === 'industry' ? 'cyan' : 'blue'}>{RESEARCH_PROFILE_LABELS[profileId]}</Tag>}
          {checkpointInfo && <Tag>执行：{({ running: '运行中', paused: '已暂停', failed: '失败（检查点可用时恢复）', completed: '已结束' })[checkpointInfo.status]}</Tag>}
          {checkpointInfo?.status === 'completed' && <Tag color={reviewPresentation(checkpointState).passed ? 'green' : 'orange'}>{reviewPresentation(checkpointState).passed ? '质量审核通过' : '请核对审核结论与资料限制'}</Tag>}
          {checkpointInfo && checkpointInfo.status !== 'completed' && <Button loading={resuming} disabled={loading || stopping} onClick={() => handleResume()}>继续研究</Button>}
          {checkpointInfo?.status === 'completed' && profileId !== 'industry' && <Button loading={resuming} disabled={loading || stopping} onClick={openReview}>追加复核</Button>}
          {checkpointInfo && <Button disabled={loading || stopping} onClick={() => navigate(`/chat?mode=${profileId || 'science'}`)}>新建研究</Button>}
          <Button loading={savingMemory} disabled={loading || list.length === 0} onClick={handleSaveMemory}>保存为记忆</Button>
        </Space>
        <Modal title="追加有限复核（保留原报告版本）" open={reviewOpen} onCancel={() => setReviewOpen(false)}
          confirmLoading={resuming} okText="确认预算并开始" okButtonProps={{ disabled: !useRemainingBudget && extraAvailable === 0 }}
          onOk={() => {
            if ((useRemainingBudget || reviewClaimIds.length > 0) && !reviewNotes.trim()) {
              uiMessage.warning('使用剩余预算或指定声明时，请填写具体复核意见'); return
            }
            void handleResume({
              ...(useRemainingBudget ? { use_remaining_budget: true } : { additional_iterations: Math.min(extraAvailable, additionalIterations) }),
              ...(reviewNotes.trim() ? { review_notes: reviewNotes.trim() } : {}),
              ...(reviewClaimIds.length ? { review_claim_ids: reviewClaimIds } : {}),
            })
          }}>
          <Alert type="info" showIcon message="追加轮次不会重置总检索预算，也不保证资料一定可得。"
            description={`累计最多追加 2 轮；本任务还可新增 ${extraAvailable} 轮。已授权剩余修订轮次 ${remainingReviewBudget}。`} />
          <p>复核意见（指出需要核实的证据、矛盾或结论，不将意见直接作为文献证据）</p>
          <Input.TextArea value={reviewNotes} onChange={event => setReviewNotes(event.target.value)} rows={4} maxLength={4000} showCount />
          <p>指定声明（可选，最多 20 条；不选则由审核定位问题）</p>
          <Select mode="multiple" style={{ width: '100%' }} value={reviewClaimIds} onChange={values => setReviewClaimIds(values.slice(0, 20))}
            options={reviewClaims.map(claim => ({ value: claim.claim_id, label: claim.claim_text.slice(0, 110) }))} />
          <p><Checkbox checked={useRemainingBudget} disabled={!mayUseRemaining} onChange={event => setUseRemainingBudget(event.target.checked)}>使用尚未用完的已授权追加预算</Checkbox></p>
          {!useRemainingBudget && <Space>本次新增修订轮次<InputNumber min={1} max={Math.max(1, extraAvailable)} value={additionalIterations} disabled={extraAvailable === 0} onChange={value => setAdditionalIterations(value || 1)} /></Space>}
        </Modal>
        <ChatMessage list={list} researchSession={!!checkpointInfo} onSend={send} onStepClick={handleStepClick} />
      </div>
    </ComPageLayout>
  )
}
