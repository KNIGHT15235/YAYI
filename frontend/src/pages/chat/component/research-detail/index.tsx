
import { FileTextOutlined, ShareAltOutlined, BarChartOutlined, CheckOutlined, LoadingOutlined, FileMarkdownOutlined } from '@ant-design/icons'
import { useState } from 'react'
import classNames from 'classnames'
import SearchResults from './search-results'
import KnowledgeGraph from './knowledge-graph'
import Visualization from './visualization'
import ProcessReport, { SectionDraft } from './process-report'
import styles from './index.module.scss'
import type { ScienceResearchData, Paper } from '@/api/research-types'
import EvidenceReview from './evidence-review'

export interface SearchResult extends Paper {
  id: string
  title: string
  source: string
  date?: string
  url?: string
  snippet?: string
}

export interface GraphNode {
  id: string
  name: string
  type: string
  url?: string
  year?: number | string
  size?: number
  importance?: number
}

export interface GraphEdge {
  source: string
  target: string
  relation: string
}

export interface KnowledgeGraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats?: {
    entitiesCount: number
    relationsCount: number
  }
}

export interface ChartConfig {
  id: string
  title: string
  subtitle?: string
  type: 'line' | 'bar' | 'pie' | 'horizontal_bar' | 'radar' | 'sankey' | 'wordcloud' | 'graph'
  echarts_option?: Record<string, unknown>
  image_base64?: string  // matplotlib 生成的 base64 图片
}

export interface ResearchDetailData extends ScienceResearchData {
  stepId: string
  stepType: string
  title: string
  subtitle?: string
  searchResults?: SearchResult[]
  knowledgeGraph?: KnowledgeGraphData
  charts?: ChartConfig[]
  streamingReport?: string  // 最终报告
  sections?: SectionDraft[]  // 章节草稿
}

export interface ResearchStep {
  id: string
  type: 'planning' | 'searching' | 'analyzing' | 'generating' | 'writing' | 'reviewing' | 're_researching' | 'revising'
  title: string
  subtitle: string
  status: 'pending' | 'running' | 'completed'
  stats?: Record<string, number>
}

interface ResearchDetailProps {
  data: ResearchDetailData | null
  steps?: ResearchStep[]
  onStepClick?: (stepId: string) => void
  onClose?: () => void
}

type TabKey = 'results' | 'papers' | 'graph' | 'charts' | 'report' | 'evidence'

const stepLabels: Record<ResearchStep['type'], string> = {
  planning: '研究计划',
  searching: '信息检索',
  analyzing: '数据分析',
  generating: '内容生成',
  writing: '撰写报告',
  reviewing: '质量审核',
  re_researching: '补充搜索',
  revising: '内容修订',
}

export default function ResearchDetail({ data, steps = [], onStepClick }: ResearchDetailProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('results')

  console.log(`[ResearchDetail] 渲染，data=${data ? 'exists' : 'null'}, steps=${steps.length}`)
  if (data) {
    console.log(`[ResearchDetail] data 详情: searchResults=${data.searchResults?.length || 0}, charts=${data.charts?.length || 0}, hasGraph=${!!data.knowledgeGraph}, hasReport=${!!data.streamingReport}`)
  }

  // 空状态
  if (!data && steps.length === 0) {
    console.log(`[ResearchDetail] 显示空状态`)
    return (
      <div className={styles.panel}>
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>
            <FileTextOutlined />
          </div>
          <div className={styles.emptyText}>开始深度研究后在此查看详情</div>
        </div>
      </div>
    )
  }

  // 计算过程报告数量：章节数 + 最终报告(如果有)
  const reportCount = (data?.sections?.length || 0) + (data?.streamingReport ? 1 : 0)

  const tabs: { key: TabKey; label: string; icon: React.ReactNode; count?: number }[] = [
    {
      key: 'results',
      label: '搜索结果',
      icon: <FileTextOutlined />,
      count: data?.searchResults?.length,
    },
    { key: 'papers', label: '文献库', icon: <FileTextOutlined />, count: data?.papers?.length },
    { key: 'evidence', label: '假设与审核', icon: <CheckOutlined />, count: data?.claims?.length },
    {
      key: 'graph',
      label: '知识图谱',
      icon: <ShareAltOutlined />,
      count: data?.knowledgeGraph?.nodes?.length,
    },
    {
      key: 'charts',
      label: '可视化图表',
      icon: <BarChartOutlined />,
      count: data?.charts?.length,
    },
    {
      key: 'report',
      label: '过程报告',
      icon: <FileMarkdownOutlined />,
      count: reportCount > 0 ? reportCount : undefined,
    },
  ]

  return (
    <div className={styles.panel}>
      {/* 研究进度步骤条 */}
      {steps.length > 0 && (
        <div className={styles.stepper}>
          {steps.map((step, index) => (
            <div
              key={step.id}
              className={classNames(styles.stepItem, {
                [styles.active]: data?.stepId === step.id,
                [styles.completed]: step.status === 'completed',
                [styles.running]: step.status === 'running',
                [styles.clickable]: step.status === 'completed',
              })}
              onClick={() => step.status === 'completed' && onStepClick?.(step.id)}
            >
              <div className={styles.stepIcon}>
                {step.status === 'completed' ? (
                  <CheckOutlined />
                ) : step.status === 'running' ? (
                  <LoadingOutlined spin />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              <div className={styles.stepLabel}>{stepLabels[step.type] || step.title}</div>
              {index < steps.length - 1 && <div className={styles.stepLine} />}
            </div>
          ))}
        </div>
      )}

      {/* Tab 切换 */}
      <div className={styles.tabs}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={classNames(styles.tab, { [styles.active]: activeTab === tab.key })}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.icon}
            <span>{tab.label}</span>
            {tab.count !== undefined && tab.count > 0 && (
              <span className={styles.count}>{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className={styles.content}>
        {activeTab === 'results' && <SearchResults data={data?.searchResults} />}
        {activeTab === 'papers' && <SearchResults data={data?.papers?.map((paper, index) => ({ ...paper, id: String(paper.source_id || paper.id || index), source: paper.provider || '学术文献', snippet: paper.abstract || paper.content }))} />}
        {activeTab === 'evidence' && <EvidenceReview data={data} />}
        {activeTab === 'graph' && <KnowledgeGraph data={data?.knowledgeGraph} />}
        {activeTab === 'charts' && <Visualization charts={data?.charts} />}
        {activeTab === 'report' && <ProcessReport content={data?.streamingReport} sections={data?.sections} charts={data?.charts} knowledgeGraph={data?.knowledgeGraph} />}
      </div>
    </div>
  )
}
