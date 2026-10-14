type VersionedMessage = {
  id: number
  role: string
  type: string
  content?: string
  loading?: boolean
}

export type ResearchMessageVersion = { number: number; total: number; latest: boolean; title: string }

/** Versions belong to one user turn; normal conversations and stored messages stay untouched. */
export function researchMessageVersions(messages: readonly VersionedMessage[], researchSession: boolean) {
  const versions = new Map<number, ResearchMessageVersion>()
  if (!researchSession) return versions
  let reports: VersionedMessage[] = []
  const finishTurn = () => {
    if (reports.length > 1) reports.forEach((report, index) => {
      const content = report.content || ''
      const title = (content.match(/^#{1,3}\s+(.+)$/m)?.[1] || content.split('\n').find(line => line.trim()) || '研究报告')
        .replace(/[*_`]/g, '').trim().slice(0, 100)
      versions.set(report.id, { number: index + 1, total: reports.length, latest: index === reports.length - 1, title })
    })
    reports = []
  }
  for (const message of messages) {
    if (message.role === 'user') finishTurn()
    else if (message.role === 'assistant' && message.type === 'deepsearch' && !message.loading && message.content?.trim()) reports.push(message)
  }
  finishTurn()
  return versions
}
