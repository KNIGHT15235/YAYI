import type { DocumentLocator } from '@/api/knowledge'

type LocatorRecord = Record<string, unknown>

function index(value: unknown): number | undefined {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return undefined
  const number = Number(value)
  return Number.isInteger(number) && number >= 0 ? number : undefined
}

function rangeLabel(records: LocatorRecord[], keys: string[], unit: string): string | undefined {
  const values = records.flatMap(record => keys.map(key => index(record[key]))).filter((value): value is number => value != null)
  if (!values.length) return undefined
  // The parser supplies zero-based, inclusive row and column indices.
  const start = Math.min(...values) + 1
  const end = Math.max(...values) + 1
  return `第 ${start === end ? start : `${start}–${end}`} ${unit}`
}

/** Readable labels only; preserve the original locator separately for inspection. */
export function locatorLabels(locator: DocumentLocator): string[] {
  const labels: string[] = []
  if (locator.page != null) labels.push(`第 ${Array.isArray(locator.page) ? locator.page.join('、') : locator.page} 页`)
  else if (locator.page_id != null) {
    const id = Array.isArray(locator.page_id) ? locator.page_id.join('、') : String(locator.page_id)
    labels.push(`页标识 ${id.length > 20 ? `${id.slice(0, 16)}…` : id}`)
  }
  if (locator.equation_number != null) labels.push(`公式 ${locator.equation_number}`)
  if (locator.figure_number != null) labels.push(`图 ${locator.figure_number}`)

  const rows: LocatorRecord[] = Array.isArray(locator.table_rows)
    ? locator.table_rows.filter((row): row is LocatorRecord => row != null && typeof row === 'object' && !Array.isArray(row)) : []
  const records: LocatorRecord[] = [locator, ...rows]
  // Markdown table fallback stores rows with cells instead of individual cell bounds.
  for (const row of rows) if (Array.isArray(row.cells) && row.cells.length) {
    records.push({ column_start: 0, column_end: row.cells.length - 1 })
  }
  const rowRange = rangeLabel(records, ['row_start', 'row_end', 'row_index'], '行')
  const columnRange = rangeLabel(records, ['column_start', 'column_end', 'column_index'], '列')
  if (rowRange) labels.push(rowRange)
  if (columnRange) labels.push(columnRange)
  const cells = rows.reduce((count, row) => count + (Array.isArray(row.cells) ? row.cells.length
    : ['row_start', 'row_end', 'column_start', 'column_end'].some(key => index(row[key]) != null) ? 1 : 0), 0)
  if (cells) labels.push(`${cells} 个单元格`)
  return labels
}

export function hasLocatorDetails(locator: DocumentLocator): boolean {
  return Object.keys(locator).some(key => !['page', 'equation_number', 'figure_number'].includes(key))
}
