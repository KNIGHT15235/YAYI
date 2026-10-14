import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/api/research-types.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { normalizeReference, readScienceData, safeExternalUrl, checkpointDisplayState, findSourceHost } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('citation numbers, source identity and original locations survive normalization', () => {
  const evidence = { id: 17, title: 'A paper', source_type: 'local', document_id: 'doc-a', knowledge_base_id: 'kb-a', evidence_id: 'e-a', doi: '10.1234/example', year: 2024, verified: true, locator: { page: [1, 2], page_id: 0 }, content: 'A source excerpt' }
  const result = normalizeReference(evidence, 0)
  assert.equal(result.id, 17)
  assert.equal(result.source, 'knowledge')
  assert.equal(result.evidence_id, evidence.evidence_id)
  assert.deepEqual(result.locator, evidence.locator)
  assert.equal(result.verified, true)
})

test('old references still work without newly introduced metadata', () => {
  assert.equal(normalizeReference({ id: null }, 0).id, 1)
  assert.equal(normalizeReference({ id: 0 }, 1).id, 2)
  assert.deepEqual(normalizeReference({ title: 'Legacy', link: 'https://example.org', source: 'knowledge', content: 'Text' }, 2), { id: 3, title: 'Legacy', link: 'https://example.org', source: 'knowledge', content: 'Text' })
})

test('completed event and serialized checkpoint retain all scientific fields', () => {
  const state = { papers: [{ source_id: 'p-1', title: 'Paper' }], evidence_ledger: { 'e-1': { title: 'Paper', abstract: 'Evidence' } }, claims: [{ claim_id: 'c-1', claim_text: 'Claim', evidence_ids: ['e-1'] }], claim_verification: { checked: 0, total: 1, skipped: 1 }, evidence_assessment: { sufficient: false, missing_questions: ['Experiment conditions'] }, hypotheses: [{ statement: 'A hypothesis', status: 'insufficient' }] }
  const restored = readScienceData(JSON.parse(JSON.stringify(state)))
  assert.deepEqual(restored, readScienceData(state))
  assert.equal(restored.claimVerification.skipped, 1)
  assert.equal(restored.evidenceAssessment.sufficient, false)
  assert.deepEqual(readScienceData({}).papers, undefined)
})

test('external source navigation only accepts HTTP and HTTPS', () => {
  assert.equal(safeExternalUrl('https://doi.org/10.1234/example'), 'https://doi.org/10.1234/example')
  for (const url of ['javascript:alert(1)', 'data:text/html,example', 'file:///tmp/report', '/private/download', 'not a url']) assert.equal(safeExternalUrl(url), undefined)
})


test('history uses original evidence and restores charts and graph when the UI snapshot is empty', () => {
  const graph = { nodes: [{ id: 'paper-1' }], edges: [] }
  const state = { references: [{ title: 'The real paper title', url: 'https://example.org', year: 2026 }], charts: [{ id: 'corpus_years' }], knowledge_graph: graph, final_report: 'Final report' }
  const restored = checkpointDisplayState({ state_json: state, ui_state_json: { references: [{ title: 'Source 1' }], charts: [], knowledge_graph: { nodes: [], edges: [] } } })
  assert.deepEqual(restored.references, state.references)
  assert.deepEqual(restored.charts, state.charts)
  assert.deepEqual(restored.knowledge_graph, graph)
  assert.equal(restored.streaming_report, 'Final report')
})

const timestampSource = readFileSync(new URL('../src/utils/api-timestamp.ts', import.meta.url), 'utf8')
const timestampJs = ts.transpileModule(timestampSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { normalizeApiTimestamp } = await import(`data:text/javascript;base64,${Buffer.from(timestampJs).toString('base64')}`)
test('naive API datetimes are UTC while explicit zones and calendar dates stay unchanged', () => {
  assert.equal(normalizeApiTimestamp('2026-09-29T08:38:50.123456'), '2026-09-29T08:38:50.123456Z')
  assert.equal(normalizeApiTimestamp('2026-09-29 08:38:50'), '2026-09-29T08:38:50Z')
  for (const value of ['2026-09-29T08:38:50Z', '2026-09-29T16:38:50+08:00', '2026-09-29']) assert.equal(normalizeApiTimestamp(value), value)
})

test('local citations never produce URL errors and public source domains still match', () => {
  const hosts = [{ url: 'www.example.org', name: 'Public source' }]
  const errors = []
  const previousError = console.error
  console.error = (...args) => errors.push(args)
  try {
    for (const url of ['/knowledge-bases/kb/documents/doc/download', './assets/table.json', '../download', 'not a URL', undefined]) {
      assert.equal(findSourceHost(url, hosts), undefined)
    }
    for (const url of ['https://www.example.org/paper', 'https://example.org/paper', 'https://papers.example.org/paper']) {
      assert.equal(findSourceHost(url, hosts)?.name, 'Public source')
    }
    assert.equal(findSourceHost('https://example.org.evil.test/paper', hosts), undefined)
    assert.deepEqual(errors, [])
  } finally { console.error = previousError }
})

const versionsSource = readFileSync(new URL('../src/utils/research-message-versions.ts', import.meta.url), 'utf8')
const versionsJs = ts.transpileModule(versionsSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { researchMessageVersions } = await import(`data:text/javascript;base64,${Buffer.from(versionsJs).toString('base64')}`)
test('research revisions select the latest report within each user turn without changing stored messages', () => {
  const messages = [
    { id: 1, role: 'user', type: 'normal', content: 'First question' },
    { id: 2, role: 'assistant', type: 'deepsearch', content: '# Initial report' },
    { id: 3, role: 'assistant', type: 'deepsearch', content: '# Revised report' },
    { id: 4, role: 'user', type: 'normal', content: 'Second question' },
    { id: 5, role: 'assistant', type: 'deepsearch', content: '# Another report' },
    { id: 6, role: 'assistant', type: 'deepsearch', content: '# Another revision' },
  ]
  const before = JSON.stringify(messages)
  const versions = researchMessageVersions(messages, true)
  assert.equal(versions.get(2).latest, false)
  assert.equal(versions.get(3).latest, true)
  assert.equal(versions.get(3).total, 2)
  assert.equal(versions.get(5).number, 1)
  assert.equal(versions.get(6).latest, true)
  assert.equal(versions.get(6).title, 'Another revision')
  assert.equal(JSON.stringify(messages), before)
  assert.equal(researchMessageVersions(messages, false).size, 0)
})
test('normal assistants and incomplete streams are not treated as saved report revisions', () => {
  const messages = [
    { id: 1, role: 'user', type: 'normal', content: 'Question' },
    { id: 2, role: 'assistant', type: 'normal', content: 'Answer' },
    { id: 3, role: 'assistant', type: 'normal', content: 'More details' },
    { id: 4, role: 'assistant', type: 'deepsearch', content: '# Saved report' },
    { id: 5, role: 'assistant', type: 'deepsearch', content: '# Draft', loading: true },
    { id: 6, role: 'assistant', type: 'deepsearch', content: '' },
  ]
  assert.equal(researchMessageVersions(messages, true).size, 0)
})
