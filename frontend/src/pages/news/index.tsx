
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Modal, Pagination, Select, Skeleton, Spin, Tag } from 'antd'
import { ArrowRightOutlined, BankOutlined, ClockCircleOutlined, FileTextOutlined, LinkOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import { useSnapshot } from 'valtio'
import { useNavigate } from 'react-router-dom'
import { authState } from '@/store/auth'
import * as api from '@/api'
import type { NewsItem, NewsStats } from '@/api/news'
import CollectionModal from '@/components/collection-modal'
import type { CollectionResult } from '@/components/collection-modal'
import styles from './index.module.scss'

const PAGE_SIZE = 20
const CATEGORIES = [{ label: '全部类型', value: '' }, { label: '新闻', value: '新闻' }, { label: '研报', value: '研报' }, { label: '政策', value: '政策' }, { label: '纪要', value: '纪要' }]
type Topic = { id: string; name: string; description: string }

export function sourceLink(value: string) {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined
  } catch { return undefined }
}

export function formatTime(value: string | null | undefined) {
  if (!value?.trim()) return '日期未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '日期未知' : date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

export default function NewsPage() {
  const navigate = useNavigate()
  const { isLoggedIn } = useSnapshot(authState)
  const [topic, setTopic] = useState('remote_sensing')
  const [topics, setTopics] = useState<Topic[]>([])
  const [topicsLoading, setTopicsLoading] = useState(false)
  const [topicsError, setTopicsError] = useState(false)
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [news, setNews] = useState<NewsItem[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<NewsStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [collecting, setCollecting] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [collectionResult, setCollectionResult] = useState<CollectionResult | null>(null)
  const newsRequest = useRef(0)
  const topicsRequest = useRef(0)
  const currentTopicName = topics.find(item => item.id === topic)?.name || (topic ? '所选主题' : '全部主题')
  const scienceTopic = topic === 'remote_sensing'

  const fetchTopics = useCallback(async () => {
    const request = ++topicsRequest.current
    setTopicsLoading(true)
    setTopicsError(false)
    try {
      const result = await api.news.getIndustries()
      if (request !== topicsRequest.current) return
      if (!result.success) throw new Error('Failed to load topics')
      setTopics(result.industries)
    } catch {
      if (request === topicsRequest.current) setTopicsError(true)
    } finally {
      if (request === topicsRequest.current) setTopicsLoading(false)
    }
  }, [])

  const fetchNews = useCallback(async () => {
    const request = ++newsRequest.current
    setLoading(true)
    setError('')
    try {
      const result = await api.news.getNewsList({
        category: category || undefined,
        ...(topic ? { industry_id: topic } : {}),
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      })
      if (request !== newsRequest.current) return
      if (!result.success) throw new Error('Failed to load news')
      setNews(result.data)
      setTotal(result.total)
      setStats(result.stats)
    } catch {
      if (request === newsRequest.current) setError('资讯加载失败，请检查连接后重试。')
    } finally {
      if (request === newsRequest.current) setLoading(false)
    }
  }, [category, page, topic])

  useEffect(() => {
    if (isLoggedIn) void fetchTopics()
    return () => { topicsRequest.current += 1 }
  }, [isLoggedIn, fetchTopics])
  useEffect(() => {
    if (isLoggedIn) void fetchNews()
    return () => { newsRequest.current += 1 }
  }, [isLoggedIn, fetchNews])

  const handleCollect = async () => {
    if (collecting || !topic) return
    setModalOpen(true)
    setCollectionResult(null)
    setCollecting(true)
    try {
      const result = await api.news.triggerCollection({
        max_news: 50, max_bidding: 50,
        ...(topic ? { industry_id: topic } : {}),
      })
      setCollectionResult(result)
      if (result.success) await fetchNews()
    } catch {
      setCollectionResult({ success: false, message: '采集请求失败，请稍后重试', news_collected: 0, bidding_collected: 0, errors: ['无法完成采集请求，请检查网络或服务状态。'] })
    } finally { setCollecting(false) }
  }

  const researchFromNews = (item: NewsItem) => {
    const url = sourceLink(item.source_url)
    const prompt = [
      scienceTopic || !topic
        ? '请以这条资讯为研究线索，梳理相关研究问题，检索并核查原始资料，区分资讯报道与文献证据，形成有引用的研究综述。'
        : '请以这条资讯为线索开展行业调研，核查原始资料，分析相关市场、政策与风险，形成有来源的研究报告。',
      '资讯标题：' + item.title,
      item.source ? '资讯来源：' + item.source : '',
      item.publish_time ? '发布日期：' + formatTime(item.publish_time) : '',
      url ? '原文链接：' + url : '',
    ].filter(Boolean).join('\n')
    navigate('/chat?mode=' + (scienceTopic || !topic ? 'science' : 'industry') + '&prompt=' + encodeURIComponent(prompt))
  }

  if (!isLoggedIn) return <div className={styles.page}><div className={styles.empty}>
    <Empty description="登录后浏览资讯和研究线索" />
    <Button type="primary" onClick={() => navigate('/login')}>前往登录</Button>
  </div></div>

  const statCards = [
    { label: '已收录资讯', value: stats?.total },
    { label: '近 24 小时收录', value: stats?.recent_24h },
    { label: scienceTopic ? '新闻与动态' : '政策', value: stats?.by_category?.[scienceTopic ? '新闻' : '政策'] },
    { label: '研报', value: stats?.by_category?.['研报'] },
  ]

  return <div className={styles.page}><div className={styles.container}>
    <header className={styles.header}>
      <div><div className={styles.eyebrow}><FileTextOutlined /> NEWS & INSIGHTS</div>
        <h1>资讯与研究线索</h1>
        <p>{scienceTopic ? '关注遥感与地球观测的官方动态、数据产品与研究进展，从原始来源发现新问题。' : '浏览主题相关的政策、研报与新闻，从真实来源发现值得深入研究的问题。'}</p>
      </div>
      <Button type="primary" icon={<SyncOutlined spin={collecting} />} loading={collecting} disabled={!topic} title={!topic ? '请先选择一个具体主题' : undefined} onClick={() => void handleCollect()}>采集资讯</Button>
    </header>

    <div className={styles.stats} aria-label="当前主题资讯统计">
      {statCards.map(item => <div className={styles.statCard} key={item.label}>
        <span>{item.label}</span><strong>{loading || error || !stats ? '—' : (item.value ?? 0).toLocaleString()}</strong>
      </div>)}
    </div>

    <section className={styles.content} aria-label="资讯列表">
      <div className={styles.filters}>
        <div className={styles.topicSelect}><label htmlFor="news-topic">主题</label><Select id="news-topic" value={topic} loading={topicsLoading} disabled={collecting}
          onChange={value => { setTopic(value); setPage(1) }} aria-label="筛选资讯主题" showSearch optionFilterProp="label"
          options={[{ value: '', label: '全部主题' }, ...topics.map(item => ({ value: item.id, label: item.name }))]} /></div>
        <div className={styles.categories} aria-label="筛选资讯类型">{CATEGORIES.map(item =>
          <button type="button" key={item.value} aria-pressed={category === item.value} disabled={collecting}
            className={category === item.value ? styles.active : ''} onClick={() => { setCategory(item.value); setPage(1) }}>{item.label}</button>)}</div>
        <Button icon={<ReloadOutlined />} loading={loading} disabled={collecting} onClick={() => void fetchNews()}>刷新</Button>
      </div>
      {topicsError && <Alert type="warning" showIcon message="主题列表暂时不可用，仍可浏览当前资讯。"
        action={<Button size="small" onClick={() => void fetchTopics()}>重试</Button>} />}
      <div className={styles.listHeading}><span>{currentTopicName} · {category || '全部类型'}</span><span>{loading ? '正在获取资讯' : error ? '加载未完成' : '共 ' + total.toLocaleString() + ' 条'}</span></div>
      <p className={styles.note}>{scienceTopic ? '当前主题使用 NASA、ESA、USGS 等官方来源，采集科研资讯，不采集招投标。内容为来源摘要，结论请回查原文。' : '上方统计按所选主题汇总，来源与发布时间以原始页面为准。'} 点击“作为研究线索”仅预填问题，可继续编辑后再发起研究。{!topic && ' 采集资讯前，请先选择一个具体主题。'}</p>

      {loading ? <div className={styles.list} aria-label="正在加载资讯">{Array.from({ length: 4 }, (_, index) =>
        <div className={styles.newsCard} key={index}><Skeleton active title paragraph={{ rows: 2 }} /></div>)}</div>
        : error ? <div className={styles.error}><Alert type="error" showIcon message={error}
          action={<Button onClick={() => void fetchNews()}>重新加载</Button>} /></div>
          : !news.length ? <div className={styles.empty}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={topic || category ? '当前筛选下暂无资讯' : '还没有收录资讯'} />
            <p>可以切换主题或类型，也可以采集相关资讯。</p>
            <div className={styles.emptyActions}>{(topic || category) && <Button onClick={() => { setTopic(''); setCategory(''); setPage(1) }}>查看全部资讯</Button>}
              <Button type="primary" loading={collecting} disabled={!topic} onClick={() => void handleCollect()}>采集资讯</Button></div>
          </div>
            : <div className={styles.list}>{news.map(item => {
              const url = sourceLink(item.source_url)
              return <article className={styles.newsCard} key={item.id}>
                <div className={styles.articleHeading}><Tag color="blue">{item.category || '资讯'}</Tag>
                  <span><ClockCircleOutlined /> {formatTime(item.publish_time)}</span></div>
                <h2>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{item.title || '未命名资讯'}</a> : item.title || '未命名资讯'}</h2>
                {item.content && <p className={styles.summary}>{item.content}</p>}
                <div className={styles.articleFooter}>
                  <div className={styles.meta}>{item.source && <span><LinkOutlined /> {item.source}</span>}
                    {item.department && <span><BankOutlined /> {item.department}</span>}</div>
                  <div className={styles.actions}>
                    {url ? <a href={url} target="_blank" rel="noopener noreferrer">查看原文 <LinkOutlined /></a> : <span className={styles.noLink}>原文链接暂缺</span>}
                    <Button size="small" icon={<ArrowRightOutlined />} onClick={() => researchFromNews(item)}>作为研究线索</Button>
                  </div>
                </div>
              </article>
            })}</div>}

      {!loading && !error && total > PAGE_SIZE && <div className={styles.pagination}>
        <Pagination current={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} showSizeChanger={false} responsive />
      </div>}
    </section>

    {scienceTopic ? <Modal title={`科研资讯采集 · ${currentTopicName}`} open={modalOpen} footer={null} closable={!collecting}
      maskClosable={false} keyboard={!collecting} onCancel={() => { if (!collecting) { setModalOpen(false); setCollectionResult(null) } }}>
      {collecting ? <p className={styles.note}><Spin size="small" /> 正在检索官方来源并检查重复资讯，可能需要几分钟。</p>
        : collectionResult && <>
          <Alert showIcon type={collectionResult.success ? 'success' : 'warning'} message={collectionResult.message}
            description={`新增科研资讯 ${collectionResult.news_collected} 条；科研主题不采集招投标。`} />
          {collectionResult.errors.length > 0 && <ul className={styles.note}>{collectionResult.errors.slice(0, 3).map((text, index) => <li key={index}>{text}</li>)}</ul>}
          <Button style={{ marginTop: 16 }} onClick={() => { setModalOpen(false); setCollectionResult(null) }}>关闭</Button>
        </>}
    </Modal> : <CollectionModal open={modalOpen} collecting={collecting} result={collectionResult} industryName={currentTopicName}
      onClose={() => { if (!collecting) { setModalOpen(false); setCollectionResult(null) } }} />}
  </div></div>
}

