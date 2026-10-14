
import * as api from '@/api'
import type { NewsItem, BiddingItem } from '@/api/news'
import IconNews from '@/assets/layout/news.svg'
import ComSender, { AttachmentInfo } from '@/components/sender'
import { useQuery } from '@/router/hook'
import { industryState, setCurrentIndustry } from '@/store/industry'
import { setPageTransport } from '@/utils'
import { useMemo, useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { message, Spin, Tag, Select } from 'antd'
import { ClockCircleOutlined, EnvironmentOutlined } from '@ant-design/icons'
import { uniqueId } from 'lodash-es'
import dayjs from 'dayjs'
import styles from './new.module.scss'
import { transportToChatEnter } from './shared'
import { RESEARCH_QUESTIONS, researchProfileId } from '@/configs/research'
import { deviceState } from '@/store/device'

export default function NewChat() {
  const query = useQuery()
  const navigate = useNavigate()
  const industry = useSnapshot(industryState)
  const profileId = researchProfileId(query.get('mode')) || 'science'
  const isScience = profileId !== 'industry'
  const prompt = query.get('prompt') || ''
  const [draft, setDraft] = useState(prompt)
  useEffect(() => { setDraft(prompt) }, [prompt])

  const changeMode = (mode: 'science' | 'industry') => {
    const params = new URLSearchParams(query)
    params.set('mode', mode)
    navigate(`/chat?${params.toString()}`, { replace: true })
  }

  // 获取当前行业名称
  const currentIndustryName = useMemo(() => {
    const current = industry.industries.find(i => i.id === industry.currentIndustryId)
    return current?.name || '行业助手'
  }, [industry.currentIndustryId, industry.industries])

  // 推荐问题 - 根据行业生成，只要3个
  const recommendQuestions = useMemo(() => {
    if (isScience) return RESEARCH_QUESTIONS
    const industryName = currentIndustryName
    return [
      `调研${industryName}的市场规模、增长驱动与竞争格局，给出有来源的行业研究报告。`,
      `分析${industryName}主要企业的经营状况、产业链位置与潜在风险。`,
      `梳理${industryName}相关政策及其影响，区分增长机会、风险因素与待验证假设。`,
    ]
  }, [currentIndustryName, isScience])

  // 附件状态管理
  const [attachments, setAttachments] = useState<AttachmentInfo[]>([])
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null)
  const attachmentPollingRef = useRef<NodeJS.Timeout | null>(null)

  // 热门资讯 - 从行业资讯和招投标获取，只取当月的
  type HotItem = {
    id: string
    title: string
    content?: string
    type: 'news' | 'bidding'
    date: string
    source?: string
    category?: string
    province?: string
    city?: string
    department?: string
  }
  const [hotList, setHotList] = useState<HotItem[]>([])
  const [newsLoading, setNewsLoading] = useState(true)

  // 获取最近的行业资讯和招投标（最近30天或最新数据）
  useEffect(() => {
    if (isScience) { setNewsLoading(false); return }
    let active = true
    async function fetchHotItems() {
      try {
        setNewsLoading(true)

        // 并行获取资讯和招投标
        const [newsRes, biddingRes] = await Promise.all([
          api.news.getNewsList({
            industry_id: industry.currentIndustryId,
            limit: 20,
            offset: 0,
          }),
          api.news.getBiddingList({
            industry_id: industry.currentIndustryId,
            limit: 20,
            offset: 0,
          }),
        ])

        const items: HotItem[] = []

        // 获取资讯（API已按时间倒序，直接取最新的）
        if (newsRes.success && newsRes.data) {
          newsRes.data.forEach((n: NewsItem) => {
            items.push({
              id: n.id,
              title: n.title,
              content: n.content,
              type: 'news',
              date: n.publish_time || n.collected_at,
              source: n.source,
              category: n.category,
              department: n.department,
            })
          })
        }

        // 获取招投标（API已按时间倒序，直接取最新的）
        if (biddingRes.success && biddingRes.data) {
          biddingRes.data.forEach((b: BiddingItem) => {
            items.push({
              id: b.id,
              title: b.title,
              content: b.content,
              type: 'bidding',
              date: b.publish_time || b.collected_at,
              source: b.source,
              category: b.notice_type,
              province: b.province,
              city: b.city,
            })
          })
        }

        // 按时间排序，取最新10条
        items.sort((a, b) => dayjs(b.date).valueOf() - dayjs(a.date).valueOf())
        if (active) setHotList(items.slice(0, 10))
      } catch (error) {
        console.error('获取热门资讯失败:', error)
        if (active) setHotList([])
      } finally {
        if (active) setNewsLoading(false)
      }
    }

    fetchHotItems()
    return () => { active = false }
  }, [industry.currentIndustryId, isScience])

  // 轮询检查附件处理状态
  useEffect(() => {
    // 只轮询非临时附件（已上传到服务器的）且状态为 pending/processing 的附件
    const pendingAttachments = attachments.filter(
      att => !att.id.startsWith('temp-') && (att.status === 'pending' || att.status === 'processing')
    )

    if (pendingAttachments.length > 0 && !attachmentPollingRef.current) {
      attachmentPollingRef.current = setInterval(async () => {
        for (const att of pendingAttachments) {
          try {
            const res = await api.session.getAttachment(att.id)
            const data = res.data || res
            if (data && data.status) {
              setAttachments(prev =>
                prev.map(a =>
                  a.id === att.id ? { ...a, status: data.status } : a
                )
              )
            }
          } catch (e) {
            console.error('Failed to check attachment status', e)
            // 如果获取失败，标记为完成以停止轮询
            setAttachments(prev =>
              prev.map(a =>
                a.id === att.id ? { ...a, status: 'completed' } : a
              )
            )
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
    // 如果还没有创建会话，先创建一个
    let sessionId = pendingSessionId
    if (!sessionId) {
      try {
        // 使用新的 session API，这样会话会出现在对话历史中
        const { data } = await api.session.createSession({ title: '新对话' })
        sessionId = data.id
        setPendingSessionId(sessionId)
      } catch (e) {
        message.error('创建会话失败')
        return null
      }
    }

    // 添加临时附件
    const tempId = uniqueId('temp-attachment-')
    setAttachments(prev => [
      ...prev,
      { id: tempId, filename: file.name, status: 'uploading' }
    ])

    try {
      const res = await api.session.uploadAttachment(sessionId, file)
      // 响应可能是 res.data 或直接是 res（取决于 axios 拦截器配置）
      const attachmentData = res.data || res
      if (attachmentData && attachmentData.id) {
        // 上传成功后，将状态设为 completed（后端处理完成后会变成 completed）
        // 如果后端返回 pending/processing，则启动轮询
        const newStatus = attachmentData.status === 'completed' ? 'completed' : attachmentData.status
        setAttachments(prev =>
          prev.map(a =>
            a.id === tempId
              ? { id: attachmentData.id, filename: attachmentData.filename, status: newStatus }
              : a
          )
        )
        message.success(`附件 ${file.name} 上传成功`)
        return attachmentData
      } else {
        // 如果没有有效响应，也标记为完成（避免一直loading）
        setAttachments(prev =>
          prev.map(a =>
            a.id === tempId
              ? { ...a, status: 'completed' }
              : a
          )
        )
      }
    } catch (e: any) {
      message.error(`附件上传失败: ${e.message || '未知错误'}`)
      setAttachments(prev => prev.filter(a => a.id !== tempId))
    }
    return null
  }, [pendingSessionId])

  // 移除附件
  const handleRemoveAttachment = useCallback(async (attachmentId: string) => {
    try {
      if (!attachmentId.startsWith('temp-')) {
        await api.session.deleteAttachment(attachmentId)
      }
      setAttachments(prev => prev.filter(a => a.id !== attachmentId))
    } catch (e) {
      console.error('Failed to delete attachment', e)
    }
  }, [])

  async function send(msg: string, attachmentIds?: string[]) {
    if (deviceState.searchModes.length === 0) { message.warning('请至少选择网络搜索或本地知识库后开始调研'); return }
    if (deviceState.searchModes.includes('local') && !deviceState.knowledgeBaseName) { message.warning('请先选择要检索的知识库'); return }
    // 如果已经有预创建的会话（因为上传了附件），直接使用它
    let sessionId = pendingSessionId
    if (!sessionId) {
      // 使用新的 session API，这样会话会出现在对话历史中
      // 用问题的前20个字符作为标题
      const title = msg.length > 20 ? msg.slice(0, 20) + '...' : msg
      const { data } = await api.session.createSession({ title })
      sessionId = data.id
    } else {
      // 如果已有会话，更新标题
      try {
        const title = msg.length > 20 ? msg.slice(0, 20) + '...' : msg
        await api.session.updateSession(sessionId, { title })
      } catch (e) {
        console.error('更新会话标题失败', e)
      }
    }

    setPageTransport(transportToChatEnter, {
      data: {
        message: msg,
        attachmentIds,
        profileId,
        sessionId,
      },
    })
    navigate(`/chat/${sessionId}`)
  }

  return (
    <div className={styles['newchat-page']}>
      <header className={styles['newchat-page__header']}>
        <span className={styles.eyebrow}>YAYI · 研究工作台</span>
        <h1>深度研究</h1>
        <p>{isScience ? '描述你的研究问题，让文献、数据与证据共同支撑结论。' : '从市场、企业与政策出发，梳理行业背景、发展机会与风险。'}</p>
      </header>

      <section className={styles['mode-panel']} aria-label="研究模式">
        <div className={styles['mode-options']} role="group" aria-label="选择研究模式">
          <button type="button" aria-pressed={isScience} onClick={() => changeMode('science')}><strong>科研背景调研</strong><span>文献综述 · 方法比较 · 假设验证</span></button>
          <button type="button" aria-pressed={!isScience} onClick={() => changeMode('industry')}><strong>行业调研</strong><span>市场与企业 · 政策解读 · 风险分析</span></button>
        </div>
        <p>为本次新研究选择模式，已有研究按原模式继续。</p>
        {!isScience && <div className={styles['industry-topic']}><span>行业主题</span><Select aria-label="选择行业主题" value={industry.currentIndustryId} options={industry.industries.map(item => ({ value: item.id, label: item.name }))} onChange={setCurrentIndustry} /><small>也可直接输入其他行业的问题</small></div>}
      </section>

      <div className={styles['input-heading']}><strong>{isScience ? '开始一个研究课题' : '开始一次行业调研'}</strong><span>选择搜索范围，也可上传资料或关联知识库</span></div>

      <ComSender
        className={styles['newchat-page__sender']}
        initialValue={draft}
        requireSearch
        placeholder={isScience ? '描述研究主题、时间范围和关注的方法；Enter 开始，Shift + Enter 换行' : '描述要调研的行业、企业或风险问题；Enter 开始，Shift + Enter 换行'}
        attachments={attachments}
        onSend={send}
        onUploadAttachment={handleUploadAttachment}
        onRemoveAttachment={handleRemoveAttachment}
      />

      {/* 推荐问题 - 和标签在同一行 */}
      <div className={styles['newchat-page__questions-row']}>
        <span className={styles['questions-label']}>试试这些研究问题<span>点击填入，可继续编辑</span></span>
        <div className={styles['questions-list']}>
          {recommendQuestions.map((question, index) => (
            <button
              type="button"
              className={styles['question-tag']}
              key={index}
              onClick={() => setDraft(question)}
            >
              {question}
            </button>
          ))}
        </div>
      </div>

      {/* 热门资讯在行业模式下保留 */}
      {!isScience && <div className={styles['newchat-page__section']}>
        <div className={styles['section-header']}>
          <div className={styles['section-icon']}>
            <img src={IconNews} />
          </div>
          <span className={styles['section-title']}>热门资讯</span>
        </div>
        <div className={styles['newchat-page__news-list']}>
          {newsLoading ? (
            <div style={{ padding: '20px', textAlign: 'center' }}>
              <Spin size="small" />
            </div>
          ) : hotList.length > 0 ? (
            hotList.map((item) => (
              <div
                className={styles['newchat-page__news-card']}
                key={item.id}
                onClick={() => setDraft(`请帮我分析：${item.title}`)}
              >
                <div className={styles['news-card__title']}>{item.title}</div>
                <div className={styles['news-card__info']}>
                  <Tag color="blue">
                    {item.type === 'news'
                      ? (item.category || '资讯')
                      : `招标 | ${item.category || '招标公告'}`}
                  </Tag>
                  {item.type === 'bidding' && (item.province || item.city) && (
                    <span className={styles['info-location']}>
                      <EnvironmentOutlined />
                      {[item.province, item.city].filter(Boolean).join(' ')}
                    </span>
                  )}
                  {item.type === 'news' && item.department && (
                    <span className={styles['info-location']}>
                      <EnvironmentOutlined />
                      {item.department}
                    </span>
                  )}
                </div>
                <div className={styles['news-card__meta']}>
                  <span className={styles['meta-item']}>
                    <ClockCircleOutlined />
                    发布于 {dayjs(item.date).format('YYYY/MM/DD')}
                  </span>
                  <span className={styles['meta-item']}>
                    ID: {item.id.slice(0, 8)}...
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div style={{ padding: '20px', textAlign: 'center', color: '#bfbfbf', fontSize: 13 }}>
              暂无相关资讯，可前往资讯页面查看或采集
            </div>
          )}
        </div>
      </div>}
      <section className={styles.workflow} aria-label="研究工作流"><div><strong>从问题到有据可循的结论</strong><span>六个研究角色协作，保留过程与来源</span></div><ol>{(isScience ? ['研究规划', '文献检索', '假设与证据', '图谱与图表', '综述撰写', '引用审核'] : ['研究规划', '资料检索', '数据与假设', '图谱与图表', '报告撰写', '质量审核']).map((step, index) => <li key={step}><b>{String(index + 1).padStart(2, '0')}</b>{step}</li>)}</ol><p>研究详情中可核对来源、引用和图表；结果保存在研究历史，支持读取检查点继续研究。</p></section>
    </div>
  )
}
