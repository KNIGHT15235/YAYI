import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, Skeleton } from 'antd'
import { ArrowRightOutlined, BookOutlined, BulbOutlined, ClockCircleOutlined, DatabaseOutlined, ExperimentOutlined, FileSearchOutlined, ReadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getSessions, type Session } from '@/api/session'
import { normalizeApiTimestamp } from '@/utils/api-timestamp'
import styles from './index.module.scss'

const exampleQuery = '围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。'
const resources = [
  { path: '/knowledge', title: '知识库管理', subtitle: '让研究资料成为可追溯的证据', description: '上传论文与资料，查看解析状态，检索段落并回查原文。', icon: <BookOutlined />, color: 'blue' },
  { path: '/database', title: '数据库探索', subtitle: '用自然语言理解结构化数据', description: '探索已接入的数据，查看查询结果，辅助分析与可视化。', icon: <DatabaseOutlined />, color: 'violet' },
  { path: '/news', title: '科研资讯', subtitle: '从外部动态发现研究线索', description: '检索主题相关资讯，查看原始来源，延伸下一次研究。', icon: <ReadOutlined />, color: 'cyan' },
  { path: '/memory', title: '记忆库', subtitle: '让每一次研究都留下积累', description: '回看研究主题、阶段摘要和偏好，为后续对话提供上下文。', icon: <BulbOutlined />, color: 'amber' },
]
const steps = [
  ['研究规划', '明确问题与研究假设'], ['资料检索', '收集文献与相关证据'], ['数据分析', '比较方法与关键数据'],
  ['知识整合', '组织关联与图表'], ['综述撰写', '形成结构化研究报告'], ['证据审核', '核对引用与结论'],
]

export default function Index() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const requestId = useRef(0)
  const loadRecent = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setError(false)
    try {
      const response = await getSessions({ limit: 4 })
      if (id === requestId.current) setSessions(response.data)
    } catch {
      if (id === requestId.current) setError(true)
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [])
  useEffect(() => {
    void loadRecent()
    return () => { requestId.current += 1 }
  }, [loadRecent])
  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div><span className={styles.eyebrow}>YAYI · 科研工作台</span><h1>从一个问题，开启新的探索</h1></div>
        <span className={styles.headerNote}><ExperimentOutlined /> 让研究有据可循</span>
      </header>
      <section className={styles.hero} aria-labelledby="home-research-title">
        <div className={styles.heroContent}>
          <span className={styles.heroLabel}><span /> 深度研究 · 多智能体协作</span>
          <h2 id="home-research-title">连接知识与证据<br />让洞见逐步清晰</h2>
          <p>从研究假设到文献综述，YAYI 协助你规划研究、追溯证据，<br className={styles.desktopBreak} />把分散的资料组织为可核对的结论。</p>
          <Button type="primary" size="large" icon={<ArrowRightOutlined />} iconPosition="end" onClick={() => navigate('/chat')}>进入深度研究</Button>
        </div>
        <div className={styles.researchOrbit} aria-hidden="true">
          <div className={styles.orbitOuter} /><div className={styles.orbitInner} />
          <div className={styles.orbitCore}><img src="/yayi-logo.png" alt="" /><span>YAYI</span><small>探索 · 连接 · 发现</small></div>
          <span className={`${styles.orbitLabel} ${styles.labelOne}`}><FileSearchOutlined /> 文献与证据</span>
          <span className={`${styles.orbitLabel} ${styles.labelTwo}`}><BulbOutlined /> 假设与洞见</span>
          <span className={`${styles.orbitLabel} ${styles.labelThree}`}><DatabaseOutlined /> 数据与知识</span>
        </div>
      </section>
      <div className={styles.example}>
        <span className={styles.exampleLabel}>试试这个研究问题</span>
        <button onClick={() => navigate(`/chat?prompt=${encodeURIComponent(exampleQuery)}`)}>{exampleQuery}<ArrowRightOutlined /></button>
      </div>
      <section className={styles.section} aria-labelledby="recent-title">
        <div className={styles.sectionHeading}>
          <div><h2 id="recent-title">继续你的研究</h2><p>从最近的记录继续探索，或回看已有成果。</p></div>
          <Link to="/history">全部历史 <ArrowRightOutlined /></Link>
        </div>
        {error ? <Alert type="warning" showIcon message="最近研究暂时无法加载" action={<Button size="small" icon={<ReloadOutlined />} onClick={loadRecent}>重试</Button>} />
          : loading ? <div className={styles.recentGrid}>{[1, 2, 3, 4].map(key => <div className={styles.recentSkeleton} key={key}><Skeleton active paragraph={{ rows: 2 }} /></div>)}</div>
          : sessions.length === 0 ? <div className={styles.empty}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有研究记录，从你关心的问题开始吧。" /><Button type="primary" onClick={() => navigate('/chat')}>开始首次研究</Button></div>
          : <div className={styles.recentGrid}>{sessions.map(session => <Link to={`/chat/${session.id}`} className={styles.recentCard} key={session.id}>
              <div className={styles.recentTop}><span className={styles.recentIcon}><FileSearchOutlined /></span><span>{session.session_type === 'deepsearch' ? '深度研究' : '对话记录'}</span><ArrowRightOutlined className={styles.recentArrow} /></div>
              <h3>{session.title || '未命名研究'}</h3>
              <div className={styles.recentMeta}><ClockCircleOutlined /> {dayjs(normalizeApiTimestamp(session.updated_at)).format('MM-DD HH:mm')}<span>{session.message_count} 条消息</span></div>
            </Link>)}</div>}
      </section>
      <section className={styles.section} aria-labelledby="resources-title">
        <div className={styles.sectionHeading}><div><h2 id="resources-title">你的研究资源</h2><p>资料、数据、动态与记忆，汇聚在同一个工作空间。</p></div></div>
        <div className={styles.resourceGrid}>{resources.map(item => <Link to={item.path} key={item.path} className={styles.resourceCard}>
          <div className={styles.resourceTop}><span className={`${styles.resourceIcon} ${styles[item.color]}`}>{item.icon}</span><ArrowRightOutlined /></div>
          <h3>{item.title}</h3><strong>{item.subtitle}</strong><p>{item.description}</p>
        </Link>)}</div>
      </section>
      <section className={styles.workflow} aria-labelledby="workflow-title">
        <div className={styles.sectionHeading}><div><h2 id="workflow-title">六个角色，共同推进一个研究问题</h2><p>研究过程可查看，文献与引用可追溯，结论经证据审核。</p></div><span className={styles.workflowBadge}>6 Agent 协作</span></div>
        <ol className={styles.steps}>{steps.map(([title, description], index) => <li key={title}><span className={styles.stepNumber}>{String(index + 1).padStart(2, '0')}</span><h3>{title}</h3><p>{description}</p></li>)}</ol>
      </section>
      <footer className={styles.footer}>YAYI 雅意 · 连接知识，启发研究</footer>
    </div>
  )
}
