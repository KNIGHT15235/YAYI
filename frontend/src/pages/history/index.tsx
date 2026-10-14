import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, Input, Modal, Pagination, Popconfirm, Select, Skeleton, Tag, message } from 'antd'
import { ArrowRightOutlined, ClockCircleOutlined, DeleteOutlined, EditOutlined, FileSearchOutlined, HistoryOutlined, MessageOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getSessions, type Session } from '@/api/session'
import { sessionActions } from '@/store/session'
import { normalizeApiTimestamp } from '@/utils/api-timestamp'
import styles from './index.module.scss'

const PAGE_SIZE = 12
const formatTime = (value: string) => dayjs(normalizeApiTimestamp(value)).format('YYYY-MM-DD HH:mm')

export default function HistoryPage() {
  const navigate = useNavigate()
  const [messageApi, contextHolder] = message.useMessage()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [loadedCount, setLoadedCount] = useState(0)
  const [error, setError] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [sessionType, setSessionType] = useState('all')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<Session | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const requestId = useRef(0)

  const fetchHistory = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setLoadedCount(0)
    setError(false)
    try {
      const collected = new Map<string, Session>()
      let offset = 0
      // The API returns a list without a total or a title-search parameter.
      // Read every page before deriving totals, filtering titles and paginating.
      while (id === requestId.current) {
        const response = await getSessions({ limit: 100, offset })
        if (id !== requestId.current) return
        const batch = response.data
        batch.forEach(session => collected.set(session.id, session))
        setLoadedCount(collected.size)
        if (batch.length < 100) break
        offset += batch.length
      }
      if (id === requestId.current) setSessions(Array.from(collected.values()))
    } catch {
      if (id === requestId.current) setError(true)
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchHistory()
    return () => { requestId.current += 1 }
  }, [fetchHistory])

  const filteredSessions = useMemo(() => {
    const query = keyword.trim().toLocaleLowerCase()
    return sessions.filter(session => (sessionType === 'all' || session.session_type === sessionType) && (!query || (session.title || '未命名研究').toLocaleLowerCase().includes(query)))
  }, [sessions, keyword, sessionType])
  const totalPages = Math.max(1, Math.ceil(filteredSessions.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const visibleSessions = filteredSessions.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const deepResearchCount = sessions.filter(session => session.session_type === 'deepsearch').length
  const chatCount = sessions.filter(session => session.session_type === 'chat').length

  const rename = async () => {
    const title = editTitle.trim()
    if (!editing || !title || saving) return
    setSaving(true)
    try {
      const updated = await sessionActions.renameSession(editing.id, title)
      setSessions(items => items.map(item => item.id === editing.id ? { ...item, ...updated } : item)
        .sort((a, b) => dayjs(normalizeApiTimestamp(b.updated_at)).valueOf() - dayjs(normalizeApiTimestamp(a.updated_at)).valueOf()))
      setEditing(null)
      messageApi.success('研究名称已更新')
    } catch {
      messageApi.error('重命名失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (session: Session) => {
    setDeleting(session.id)
    try {
      await sessionActions.removeSession(session.id)
      setSessions(items => items.filter(item => item.id !== session.id))
      messageApi.success('研究记录已删除')
    } catch {
      messageApi.error('删除失败，请重试')
    } finally {
      setDeleting(null)
    }
  }

  const resetFilters = () => { setKeyword(''); setSessionType('all'); setPage(1) }
  return (
    <div className={styles.page}>
      {contextHolder}
      <header className={styles.header}>
        <div><span className={styles.eyebrow}>YAYI · 研究档案</span><h1>研究历史</h1><p>回看研究过程与成果，让每一次探索都有迹可循。</p></div>
        <div className={styles.headerActions}><Button icon={<ReloadOutlined />} onClick={fetchHistory} loading={loading} disabled={saving || !!deleting}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/chat')}>深度研究</Button></div>
      </header>
      <div className={styles.stats} aria-label="研究记录统计">
        {[
          { label: '全部记录', value: sessions.length, icon: <HistoryOutlined />, color: 'blue' },
          { label: '深度研究', value: deepResearchCount, icon: <FileSearchOutlined />, color: 'violet' },
          { label: '对话记录', value: chatCount, icon: <MessageOutlined />, color: 'cyan' },
        ].map(item => <div className={styles.stat} key={item.label}><span className={`${styles.statIcon} ${styles[item.color]}`}>{item.icon}</span><div><span>{item.label}</span><strong>{loading || error ? '—' : item.value}</strong></div></div>)}
      </div>
      <section className={styles.archive} aria-label="研究记录列表">
        <div className={styles.toolbar}>
          <Input value={keyword} onChange={event => { setKeyword(event.target.value); setPage(1) }} allowClear prefix={<SearchOutlined />} placeholder="搜索研究标题" aria-label="搜索研究标题" className={styles.search} />
          <Select value={sessionType} onChange={value => { setSessionType(value); setPage(1) }} aria-label="研究类型" className={styles.typeFilter} options={[{ value: 'all', label: '全部类型' }, { value: 'deepsearch', label: '深度研究' }, { value: 'chat', label: '对话记录' }]} />
          <span className={styles.resultCount}>{loading ? `正在读取记录${loadedCount ? ` · 已读取 ${loadedCount} 条` : ''}` : error ? '加载未完成' : `共 ${filteredSessions.length} 条${keyword || sessionType !== 'all' ? '匹配记录' : '记录'}`}</span>
        </div>
        {error ? <div className={styles.error}><Alert type="error" showIcon message="研究历史加载失败" description="请检查连接后重试，已保存的研究记录不会受影响。" action={<Button onClick={fetchHistory} icon={<ReloadOutlined />}>重试</Button>} /></div>
          : loading ? <div className={styles.skeletons}>{[1, 2, 3].map(item => <Skeleton key={item} active avatar paragraph={{ rows: 1 }} />)}</div>
          : visibleSessions.length === 0 ? <div className={styles.empty}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={keyword || sessionType !== 'all' ? '没有找到匹配的研究记录' : '你的研究档案，从第一个问题开始'} />
            {keyword || sessionType !== 'all' ? <Button onClick={resetFilters}>清除筛选</Button> : <Button type="primary" onClick={() => navigate('/chat')}>开始深度研究</Button>}
          </div>
          : <>
            <div className={styles.list}>{visibleSessions.map(session => <article className={styles.record} key={session.id}>
              <div className={`${styles.recordIcon} ${session.session_type === 'deepsearch' ? styles.blue : styles.cyan}`}>{session.session_type === 'deepsearch' ? <FileSearchOutlined /> : <MessageOutlined />}</div>
              <div className={styles.recordContent}>
                <div className={styles.recordTitle}><Link to={`/chat/${session.id}`}>{session.title || '未命名研究'}</Link><Tag color={session.session_type === 'deepsearch' ? 'blue' : 'default'}>{session.session_type === 'deepsearch' ? '深度研究' : session.session_type === 'chat' ? '对话' : '其他记录'}</Tag></div>
                <div className={styles.recordMeta}><span><ClockCircleOutlined /> 更新于 {formatTime(session.updated_at)}</span><span>创建于 {formatTime(session.created_at)}</span><span>{session.message_count} 条消息</span></div>
              </div>
              <div className={styles.recordActions}>
                <Button type="text" icon={<EditOutlined />} aria-label={`重命名 ${session.title || '未命名研究'}`} title="重命名" disabled={!!deleting} onClick={() => { setEditing(session); setEditTitle(session.title || '') }} />
                <Popconfirm title="删除这条研究记录？" description="会话及其中的消息将被删除，此操作无法撤销。" okText="确认删除" cancelText="保留" okButtonProps={{ danger: true }} onConfirm={() => remove(session)}>
                  <Button type="text" danger icon={<DeleteOutlined />} aria-label={`删除 ${session.title || '未命名研究'}`} title="删除记录" loading={deleting === session.id} disabled={!!deleting && deleting !== session.id} />
                </Popconfirm>
                <Button className={styles.openButton} onClick={() => navigate(`/chat/${session.id}`)} icon={<ArrowRightOutlined />} iconPosition="end">打开</Button>
              </div>
            </article>)}</div>
            <div className={styles.pagination}><span>按最近更新时间排序</span><Pagination current={currentPage} pageSize={PAGE_SIZE} total={filteredSessions.length} onChange={setPage} showSizeChanger={false} hideOnSinglePage size="small" /></div>
          </>}
      </section>
      <p className={styles.hint}><HistoryOutlined /> 打开记录后，可查看已有消息；深度研究详情中保留报告、引用、图谱与检查点入口。</p>
      <Modal title="重命名研究" open={!!editing} onCancel={() => { if (!saving) setEditing(null) }} onOk={rename} okText="保存名称" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: !editTitle.trim() }} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} destroyOnClose>
        <label className={styles.renameLabel} htmlFor="history-title">研究名称</label>
        <Input id="history-title" value={editTitle} maxLength={200} showCount onChange={event => setEditTitle(event.target.value)} onPressEnter={rename} disabled={saving} placeholder="输入便于查找的研究名称" />
      </Modal>
    </div>
  )
}
