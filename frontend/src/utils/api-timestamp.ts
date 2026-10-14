/** The API stores UTC timestamps; only naive datetime strings need a zone suffix. */
export function normalizeApiTimestamp(value: string): string {
  const timestamp = value.trim()
  return /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(timestamp)
    ? `${timestamp.replace(' ', 'T')}Z`
    : timestamp
}
