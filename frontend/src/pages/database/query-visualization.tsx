import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import type { Text2SQLResponse } from '@/api/database'

export function buildQueryChart(result: Text2SQLResponse): EChartsOption | null {
  if (!result.success || !result.data?.length) return null
  const hint = result.visualization_hint?.toLowerCase().trim()
  if (!['bar', 'line', 'pie', 'scatter'].includes(hint)) return null
  const columns = result.columns?.length ? result.columns : Object.keys(result.data[0])
  const numberValue = (value: unknown): number | null => {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null
    const number = Number(value)
    return Number.isFinite(number) ? number : null
  }
  const numeric = columns.filter(column => result.data.some(row => numberValue(row[column]) !== null)
    && result.data.every(row => row[column] == null || numberValue(row[column]) !== null))
  if (!numeric.length) return null
  const dimension = columns.find(column => !numeric.includes(column)) || (columns.length > 1 ? columns[0] : undefined)
  const measures = numeric.filter(column => column !== dimension)
  if (hint === 'scatter') {
    if (numeric.length < 2) return null
    return {
      tooltip: { trigger: 'item' },
      xAxis: { type: 'value', name: numeric[0] }, yAxis: { type: 'value', name: numeric[1] },
      series: [{ type: 'scatter', data: result.data.flatMap(row => {
        const x = numberValue(row[numeric[0]]), y = numberValue(row[numeric[1]])
        return x === null || y === null ? [] : [[x, y]]
      }) }],
    }
  }
  if (!measures.length) return null
  const labels = result.data.map((row, index) => dimension ? String(row[dimension] ?? '未标注') : String(index + 1))
  if (hint === 'pie') {
    if (result.data.some(row => (numberValue(row[measures[0]]) ?? 0) < 0)) return null
    return {
      tooltip: { trigger: 'item' }, legend: { type: 'scroll', bottom: 0 },
      series: [{ type: 'pie', radius: '60%', name: measures[0], data: result.data.flatMap((row, index) => {
        const value = numberValue(row[measures[0]])
        return value === null ? [] : [{ name: labels[index], value }]
      }) }],
    }
  }
  return {
    tooltip: { trigger: 'axis' }, legend: { type: 'scroll', bottom: 0 },
    grid: { left: 60, right: 25, top: 35, bottom: 75, containLabel: true },
    xAxis: { type: 'category', data: labels, axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value' },
    series: measures.map(name => ({ name, type: hint as 'line' | 'bar', data: result.data.map(row => numberValue(row[name])) })),
  }
}

export default function QueryVisualization({ result }: { result: Text2SQLResponse }) {
  const option = useMemo(() => {
    const chart = buildQueryChart(result)
    return chart ? { ...chart, color: ['#397ac3', '#63a3d8', '#8bbcd4', '#527396', '#a9c5e8'], textStyle: { color: '#526780' } } : null
  }, [result])
  if (!option) return null
  return <section aria-label="查询结果图表" style={{ padding: '16px 0', borderBottom: '1px solid #e3eaf2', marginBottom: 16 }}>
    <div style={{ marginBottom: 8, color: '#294462', fontSize: 14, fontWeight: 600 }}>查询结果可视化</div>
    <ReactECharts option={option} notMerge style={{ height: 340, width: '100%' }} />
  </section>
}
