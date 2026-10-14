
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Pagination, Spin, Table, Tag, Tooltip } from 'antd'
import { DatabaseOutlined, ReloadOutlined, SearchOutlined, TableOutlined } from '@ant-design/icons'
import { useSnapshot } from 'valtio'
import { useNavigate } from 'react-router-dom'
import { authState } from '@/store/auth'
import * as api from '@/api'
import type { DatabaseCatalog, TableDataResponse, TableInfo, Text2SQLResponse } from '@/api/database'
import QueryVisualization from './query-visualization'
import styles from './index.module.scss'

const PAGE_SIZE = 20
const COLUMN_NAMES: Record<string, string> = {
  id: 'ID', industry_name: '行业名称', metric_name: '指标名称', metric_value: '指标值',
  unit: '单位', year: '年份', quarter: '季度', month: '月份', region: '地区',
  source: '来源', created_at: '创建时间', company_name: '企业名称', stock_code: '股票代码',
  industry: '所属行业', sub_industry: '细分行业', revenue: '营收（亿元）',
  net_profit: '净利润（亿元）', gross_margin: '毛利率（%）', market_cap: '市值（亿元）',
  employees: '员工数量', market_share: '市场份额（%）', policy_name: '政策名称',
  policy_number: '文号', department: '发布部门', level: '政策级别', publish_date: '发布日期',
  effective_date: '生效日期', category: '分类', summary: '摘要', impact_level: '影响程度',
  paper_id: '文献 ID', title: '文献标题', publication_year: '发表年份', authors: '作者', venue: '期刊 / 会议',
  doi: 'DOI', source_url: '原始来源', metadata_source: '元数据来源', evidence_level: '证据层级',
  source_verified: '来源核验', corpus_id: '语料集 ID', imported_at: '导入时间', abstract: '摘要',
  method_name: '方法标签', matched_keywords: '匹配关键词', tagging_rule: '标签规则',
  paper_count: '文献数量', count: '数量', method_count: '方法标签数量',
}
type DataRow = Record<string, unknown>
type CatalogTable = DatabaseCatalog['tables'][number] & Partial<TableInfo>

export function originalSourceLink(column: string, value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined
  const input = value.trim()
  if (column === 'doi') {
    const doi = input.replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, '')
    return /^10\.\d{4,9}\/\S+$/i.test(doi) ? `https://doi.org/${encodeURI(doi).replace(/#/g, '%23').replace(/\?/g, '%3F')}` : undefined
  }
  if (column !== 'source_url') return undefined
  try { const url = new URL(input); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined } catch { return undefined }
}

export function DataTable({ columns, rows, columnNames = {} }: { columns: string[]; rows: DataRow[]; columnNames?: Record<string, string> }) {
  return <Table<DataRow>
    className={styles.dataTable}
    size="middle"
    columns={columns.map(column => ({
      title: <span>{columnNames[column] || COLUMN_NAMES[column] || column}<small>{column}</small></span>,
      dataIndex: column, key: column, width: 180, ellipsis: { showTitle: false },
      render: (value: unknown) => {
        const link = originalSourceLink(column, value)
        if (link) return <Tooltip title={String(value)}><a href={link} target="_blank" rel="noopener noreferrer">{column === 'doi' ? String(value) : '查看原文 ↗'}</a></Tooltip>
        if (column === 'source_verified') return <Tag color={value === true ? 'green' : 'default'}>{value === true ? '已核验' : value === false ? '未核验' : '未知'}</Tag>
        if (column === 'evidence_level' && typeof value === 'string') return <span>{({ metadata: '元数据', abstract: '摘要', full_text: '全文', fulltext: '全文' } as Record<string, string>)[value] || value}</span>
        const label = value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)
        return <Tooltip title={label}><span>{label}</span></Tooltip>
      },
    }))}
    dataSource={rows} rowKey={(_row, index) => String(index)} pagination={false}
    scroll={{ x: Math.max(columns.length * 180, 600) }}
    locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无匹配数据" /> }}
  />
}

export default function DatabasePage() {
  const { isLoggedIn } = useSnapshot(authState)
  const navigate = useNavigate()
  const [tables, setTables] = useState<CatalogTable[]>([])
  const [catalog, setCatalog] = useState<DatabaseCatalog | null>(null)
  const [tablesLoading, setTablesLoading] = useState(false)
  const [tablesError, setTablesError] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [page, setPage] = useState(1)
  const [tableData, setTableData] = useState<DataRow[]>([])
  const [tableColumns, setTableColumns] = useState<string[]>([])
  const [tableTotal, setTableTotal] = useState(0)
  const [dataLoading, setDataLoading] = useState(false)
  const [dataError, setDataError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchResult, setSearchResult] = useState<Text2SQLResponse | null>(null)
  const [searchError, setSearchError] = useState('')
  const tablesRequest = useRef(0)
  const dataRequest = useRef(0)
  const searchRequest = useRef(0)

  const fetchTables = useCallback(async () => {
    const request = ++tablesRequest.current
    setTablesLoading(true)
    setTablesError('')
    try {
      const [response, catalogResponse] = await Promise.all([api.database.getTables(), api.database.getCatalog()])
      const data = response.data as TableInfo[]
      const descriptions = catalogResponse.data as DatabaseCatalog
      if (request !== tablesRequest.current) return
      const available = descriptions.tables.map(table => ({ ...data.find(item => item.name === table.name), ...table }))
      setCatalog(descriptions)
      setTables(available)
      setSelectedTable(current => available.some(table => table.name === current) ? current
        : available.find(table => table.name === descriptions.default_table)?.name || available[0]?.name || '')
      setPage(1)
    } catch {
      if (request === tablesRequest.current) setTablesError('数据表列表加载失败，请检查连接后重试。')
    } finally {
      if (request === tablesRequest.current) setTablesLoading(false)
    }
  }, [])

  const fetchTableData = useCallback(async () => {
    if (!selectedTable) return
    const request = ++dataRequest.current
    setDataLoading(true)
    setDataError('')
    try {
      const response = await api.database.getTableData(selectedTable, { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
      const data = response.data as TableDataResponse
      if (request !== dataRequest.current) return
      setTableData(data.rows)
      setTableColumns(data.columns)
      setTableTotal(data.total)
    } catch {
      if (request === dataRequest.current) setDataError('表格数据加载失败，可以重试当前页。')
    } finally {
      if (request === dataRequest.current) setDataLoading(false)
    }
  }, [selectedTable, page])

  useEffect(() => {
    if (isLoggedIn) void fetchTables()
    return () => { tablesRequest.current += 1 }
  }, [isLoggedIn, fetchTables])
  useEffect(() => {
    if (isLoggedIn) void fetchTableData()
    return () => { dataRequest.current += 1 }
  }, [isLoggedIn, fetchTableData])
  useEffect(() => () => { searchRequest.current += 1 }, [])

  const handleSearch = async (question = searchQuery) => {
    if (!question.trim() || searchLoading) return
    const request = ++searchRequest.current
    setSubmittedQuery(question.trim())
    setSearchLoading(true)
    setSearchResult(null)
    setSearchError('')
    try {
      const response = await api.database.text2sql(question.trim())
      const data = response.data as Text2SQLResponse
      if (request !== searchRequest.current) return
      setSearchResult(data)
      if (!data.success) setSearchError(data.error || '暂时无法完成这次查询，请尝试明确数据表、指标或时间范围。')
    } catch {
      if (request === searchRequest.current) setSearchError('查询请求失败，请重试，或调整问题后重新查询。')
    } finally {
      if (request === searchRequest.current) setSearchLoading(false)
    }
  }

  if (!isLoggedIn) return <div className={styles.page}><div className={styles.empty}>
    <Empty description="登录后探索数据表和自然语言查询" />
    <Button type="primary" onClick={() => navigate('/login')}>前往登录</Button>
  </div></div>

  return <div className={styles.page}>
    <div className={styles.container}>
      <header className={styles.header}>
        <div><div className={styles.eyebrow}><DatabaseOutlined /> DATA EXPLORER</div>
          <h1>数据库探索</h1>
          <p>探索已纳入的真实文献与行业资料，用自然语言查询、统计并回查来源。</p>
        </div>
        <Tag color="blue">结构化数据</Tag>
      </header>
      <section className={styles.queryCard} aria-labelledby="query-heading">
        <div className={styles.cardHeading}><h2 id="query-heading">用问题探索数据</h2><Tag>Text2SQL</Tag></div>
        <p className={styles.description}>{catalog?.corpus?.label || '通过已接入的数据表开展文献统计与资料查询'}。查询、图表和表格均来自实际记录。</p>
        {catalog?.notice && <p className={styles.corpusNote}>{catalog.notice}</p>}
        <form className={styles.searchForm} onSubmit={event => { event.preventDefault(); void handleSearch() }}>
          <Input size="large" prefix={<SearchOutlined />} value={searchQuery} allowClear
            onChange={event => setSearchQuery(event.target.value)} maxLength={1500}
            aria-label="自然语言查询问题" placeholder="例如：按年份统计文献数量" />
          <Button type="primary" size="large" htmlType="submit" loading={searchLoading} disabled={!searchQuery.trim()}>查询数据</Button>
        </form>
        <div className={styles.examples}><span>试试这样问</span>{(catalog?.examples || []).map(question =>
          <button key={question} type="button" disabled={searchLoading} onClick={() => setSearchQuery(question)}>{question}</button>)}</div>
      </section>
      {(searchLoading || searchResult || searchError) && <section className={styles.resultCard} aria-live="polite">
        <div className={styles.cardHeading}><div><h2>查询结果</h2><p className={styles.description}>{submittedQuery}</p></div>
          {!searchLoading && <Button type="text" onClick={() => { setSearchResult(null); setSearchError('') }}>收起结果</Button>}</div>
        {searchLoading ? <div className={styles.loading}><Spin /><span>正在理解问题并查询数据…</span></div> : <>
          {searchError && <Alert type="error" showIcon message="本次查询未完成" description={searchError}
            action={<Button size="small" onClick={() => void handleSearch(submittedQuery)}>重试</Button>} />}
          {searchResult?.explanation && <p className={styles.explanation}>{searchResult.explanation}</p>}
          {searchResult?.sql && <details className={styles.sql}><summary>查看生成的 SQL</summary><pre>{searchResult.sql}</pre></details>}
          {searchResult?.success && <>
            <QueryVisualization result={searchResult} />
            <DataTable columns={searchResult.columns?.length ? searchResult.columns : Object.keys(searchResult.data?.[0] || {})} rows={searchResult.data || []} />
            <p className={styles.resultCount}>返回 {searchResult.row_count ?? searchResult.data?.length ?? 0} 条结果 · 图表仅反映本次查询返回的数据</p>
          </>}
        </>}
      </section>}
      <div className={styles.workspace}>
        <aside className={styles.sidebar} aria-label="数据表选择">
          <div className={styles.cardHeading}><h2>数据表</h2><Button type="text" size="small" aria-label="刷新数据表列表" title="刷新数据表列表"
            icon={<ReloadOutlined />} loading={tablesLoading} onClick={() => void fetchTables()} /></div>
          {tablesError ? <Alert type="error" showIcon message={tablesError} action={<Button size="small" onClick={() => void fetchTables()}>重试</Button>} />
            : tablesLoading ? <div className={styles.loading}><Spin /></div>
              : tables.length ? <div className={styles.tableList}>{tables.map(table => <button type="button" key={table.name}
                className={`${styles.tableItem} ${table.name === selectedTable ? styles.active : ''}`}
                aria-pressed={table.name === selectedTable} onClick={() => { setPage(1); setSelectedTable(table.name) }}>
                <TableOutlined /><span><strong>{table.label}</strong><small>{table.description}</small>
                  <small>{table.row_count?.toLocaleString() ?? '—'} 条记录 · {table.column_count ?? Object.keys(table.columns).length} 个字段</small></span>
              </button>)}</div>
                : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可用数据表" />}
          <p className={styles.sidebarNote}>数据记录的时间、单位与来源请以表内字段为准。</p>
        </aside>
        <section className={styles.tableCard} aria-label="数据表记录">
          {selectedTable ? <>
            <div className={styles.cardHeading}><div><h2>{tables.find(table => table.name === selectedTable)?.label || selectedTable}</h2>
              <p className={styles.description}>{selectedTable}</p></div>
              <Button icon={<ReloadOutlined />} loading={dataLoading} onClick={() => void fetchTableData()}>刷新</Button></div>
            {dataLoading ? <div className={styles.loading}><Spin /><span>正在读取数据…</span></div>
              : dataError ? <Alert type="error" showIcon message={dataError} action={<Button onClick={() => void fetchTableData()}>重试</Button>} />
                : <><DataTable columns={tableColumns} rows={tableData} columnNames={tables.find(table => table.name === selectedTable)?.columns} /><div className={styles.pagination}>
                  <span>共 {tableTotal.toLocaleString()} 条记录</span>
                  <Pagination current={page} total={tableTotal} pageSize={PAGE_SIZE} onChange={setPage} showSizeChanger={false} size="small" hideOnSinglePage />
                </div></>}
          </> : <div className={styles.empty}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={tablesLoading ? '正在连接数据表…' : '选择左侧数据表以浏览记录'} /></div>}
        </section>
      </div>
    </div>
  </div>
}
