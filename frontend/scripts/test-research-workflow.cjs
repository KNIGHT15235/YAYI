// Offline behavioral checks of the actual TypeScript helpers used by the UI.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
const root = path.resolve(__dirname, '..')
function load(relative) {
  const filename = path.join(root, relative)
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const loaded = new Module(filename, module)
  loaded.filename = filename
  loaded.paths = Module._nodeModulePaths(path.dirname(filename))
  loaded._compile(code, filename)
  return loaded.exports
}
let count = 0
function test(name, run) { run(); count += 1; console.log(`PASS ${name}`) }
const { ResearchStreamScope } = load('src/utils/research-stream.ts')
const { locatorWindow } = load('src/utils/document-locator.ts')

test('large locator lists initially show four without losing source data', () => {
  const locators = Object.freeze(Array.from({ length: 52 }, (_, index) => Object.freeze({ page: index + 1, bbox: [1, 2, 3, 4] })))
  const collapsed = locatorWindow(locators)
  assert.equal(collapsed.total, 52)
  assert.equal(collapsed.visible.length, 4)
  assert.equal(collapsed.hidden, 48)
  assert.equal(collapsed.visible[0], locators[0])
  assert.equal(locators.length, 52)
  assert.deepEqual(locators[51].bbox, [1, 2, 3, 4])
})

test('expand and collapse restore all exact locator objects in source order', () => {
  const locators = Array.from({ length: 52 }, (_, index) => ({ page: index + 1, row_index: index }))
  const expanded = locatorWindow(locators, true)
  assert.equal(expanded.visible, locators)
  assert.equal(expanded.hidden, 0)
  assert.equal(expanded.visible[51], locators[51])
  assert.deepEqual(locatorWindow(locators, false).visible, locators.slice(0, 4))
})

test('empty and short locator lists do not require an expand control', () => {
  assert.deepEqual(locatorWindow(undefined), { visible: [], total: 0, hidden: 0 })
  assert.deepEqual(locatorWindow([]), { visible: [], total: 0, hidden: 0 })
  assert.equal(locatorWindow([{ page: 1 }, { page: 2 }]).hidden, 0)
})

test('new session aborts and rejects old SSE', () => {
  const scope = new ResearchStreamScope()
  const old = scope.begin('A'); const current = scope.begin('B')
  assert.equal(old.controller.signal.aborted, true)
  assert.equal(scope.accepts(old, 'A'), false)
  assert.equal(scope.accepts(current, 'B'), true)
  assert.equal(scope.accepts(current, 'A'), false)
})
test('reconnecting rejects previous connection generation', () => {
  const scope = new ResearchStreamScope()
  const old = scope.begin('A'); const current = scope.begin('A')
  assert.equal(scope.accepts(old), false)
  assert.equal(scope.accepts(current), true)
  scope.close(); assert.equal(scope.accepts(current), false)
})
const { upsertResearchStep, completeSupplementarySearch, revisionPresentation, reviewPresentation, withQualityReviewNotice, restoredStepStatus, acceptedResumeCheckpoint, checkpointKnowledgeBase, checkpointSearchSelection } = load('src/pages/chat/shared.ts')

test('durable supplementary search to Analysis transition closes only that running step', () => {
  const searching = { type: 'searching', status: 'completed', subtitle: '已检索' }
  const supplement = { type: 're_researching', status: 'running', subtitle: '执行 re_researching...', stats: { resultsCount: 20 } }
  const unrelated = { type: 'reviewing', status: 'running', subtitle: '审核中' }
  const next = completeSupplementarySearch([searching, supplement, unrelated], 'analyzing')
  assert.equal(next[0], searching)
  assert.equal(next[1].status, 'completed')
  assert.equal(next[1].subtitle, '')
  assert.equal(next[1].stats, supplement.stats)
  assert.equal(next[2], unrelated)
  assert.equal(supplement.status, 'running')
})

test('supplementary transition does not invent progress or erase paused or failed states', () => {
  const running = [{ type: 're_researching', status: 'running' }]
  for (const phase of [undefined, 'searching', 're_researching', 'writing', 'completed']) {
    assert.equal(completeSupplementarySearch(running, phase), running)
  }
  for (const status of ['paused', 'failed', 'completed', 'pending']) {
    const previous = [{ type: 're_researching', status, subtitle: '保留原因' }]
    assert.equal(completeSupplementarySearch(previous, 'analyzing'), previous)
  }
  const noSupplement = [{ type: 'analyzing', status: 'running' }]
  assert.equal(completeSupplementarySearch(noSupplement, 'analyzing'), noSupplement)
})

test('old connection Analysis event cannot complete the current supplementary step', () => {
  const scope = new ResearchStreamScope()
  const old = scope.begin('A')
  const current = scope.begin('A')
  const previous = [{ type: 're_researching', status: 'running' }]
  const apply = ticket => scope.accepts(ticket, 'A') ? completeSupplementarySearch(previous, 'analyzing') : previous
  assert.equal(apply(old), previous)
  assert.equal(apply(current)[0].status, 'completed')
  scope.begin('B')
  assert.equal(apply(current), previous)
})

test('new accepted phase restarts an existing step without changing unrelated history', () => {
  for (const status of ['paused', 'failed', 'completed']) {
    const history = { type: 'planning', status: 'completed' }
    const previous = { type: 'revising', status, subtitle: '已暂停', stats: { wordCount: 100 } }
    const next = upsertResearchStep([history, previous], { type: 'revising', status: 'running', subtitle: '执行 revising...' })
    assert.equal(next.length, 2)
    assert.equal(next[0], history)
    assert.equal(next[1].status, 'running')
    assert.equal(next[1].subtitle, '执行 revising...')
    assert.equal(next[1].stats, previous.stats)
    assert.equal(previous.status, status)
    assert.equal(previous.subtitle, '已暂停')
  }
})

test('step progress replaces obsolete pause text and new steps append once', () => {
  const previous = [{ type: 'revising', status: 'paused', subtitle: '已暂停并保存检查点' }]
  const running = upsertResearchStep(previous, { type: 'revising', status: 'running', subtitle: '' })
  assert.equal(running[0].subtitle, '')
  const reviewing = { type: 'reviewing', status: 'running', subtitle: '审核中' }
  assert.deepEqual(upsertResearchStep(running, reviewing), [...running, reviewing])
})

test('stale connection cannot restart a paused research step', () => {
  const scope = new ResearchStreamScope()
  const old = scope.begin('A')
  const current = scope.begin('B')
  const previous = [{ type: 'revising', status: 'paused', subtitle: '已暂停' }]
  const update = (ticket, session) => scope.accepts(ticket, session)
    ? upsertResearchStep(previous, { type: 'revising', status: 'running', subtitle: '' }) : previous
  assert.equal(update(old, 'A'), previous)
  assert.equal(update(current, 'A'), previous)
  assert.equal(update(current, 'B')[0].status, 'running')
})

test('revision counts distinguish missing telemetry from a confirmed zero', () => {
  for (const unknown of [undefined, null, '3', -1, 1.5, NaN, Infinity]) {
    assert.equal(revisionPresentation(unknown), '📝 修订阶段结束，等待复核')
    assert.doesNotMatch(revisionPresentation(unknown), /0 处/)
  }
  assert.match(revisionPresentation(0), /共 0 处修改/)
  assert.match(revisionPresentation(3), /共 3 处修改/)
})

test('accepted resume updates execution without fabricating quality or mutating saved result', () => {
  const checkpoint = { session_id: 'A', status: 'failed', error_message: 'old failure', state_json: { review_verdict: 'not_reviewed' } }
  const next = acceptedResumeCheckpoint(checkpoint, 'A')
  assert.equal(next.status, 'running')
  assert.equal(next.error_message, null)
  assert.equal(next.state_json.review_verdict, 'not_reviewed')
  assert.equal(checkpoint.status, 'failed')
})

test('resume confirmation cannot mark another session running', () => {
  const checkpoint = { session_id: 'B', status: 'paused' }
  assert.equal(acceptedResumeCheckpoint(checkpoint, 'A'), checkpoint)
  assert.equal(acceptedResumeCheckpoint(null, 'A'), null)
})

test('restored knowledge selector requires current session and server-bound local identity', () => {
  const checkpoint = { session_id: 'A', state_json: { search_local: true, kb_name: 'owned', knowledge_base_id: 'kb-id' } }
  assert.deepEqual(checkpointKnowledgeBase(checkpoint, 'A'), { name: 'owned', id: 'kb-id' })
  assert.equal(checkpointKnowledgeBase(checkpoint, 'B'), null)
  assert.equal(checkpointKnowledgeBase({ ...checkpoint, state_json: { search_local: true, kb_name: 'unbound' } }, 'A'), null)
  assert.equal(checkpointKnowledgeBase({ ...checkpoint, state_json: { ...checkpoint.state_json, search_local: false } }, 'A'), null)
})

test('switching from local A to nonlocal B clears inherited knowledge selection', () => {
  const b = { session_id: 'B', state_json: { search_local: false, search_web: false, kb_name: 'obsolete' } }
  assert.deepEqual(checkpointSearchSelection(b, 'B'), { modes: [], knowledgeBase: null })
  assert.deepEqual(checkpointSearchSelection({ ...b, state_json: { search_local: false, search_web: true } }, 'B'),
    { modes: ['web'], knowledgeBase: null })
  assert.equal(checkpointSearchSelection(b, 'A'), null)
})

test('new research and preupload sessions both persist deepsearch classification', () => {
  const filename = path.join(root, 'src/pages/chat/newchat.tsx')
  const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let creates = 0
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === 'api.session.createSession') {
      creates += 1
      const argument = node.arguments[0]
      assert.ok(ts.isObjectLiteralExpression(argument))
      const type = argument.properties.find(property => property.name?.getText(source) === 'session_type')
      assert.equal(type?.initializer?.text, 'deepsearch')
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  assert.equal(creates, 2)
})

test('completed task does not turn failed or pending stages green', () => {
  assert.equal(restoredStepStatus({ type: 'analyzing', status: 'failed' }, { status: 'completed' }), 'failed')
  assert.equal(restoredStepStatus({ type: 'writing', status: 'pending' }, { status: 'completed' }), 'pending')
  assert.equal(restoredStepStatus({ type: 'writing' }, { status: 'completed' }), 'pending')
})
test('legacy provider failures override incorrect completed telemetry', () => {
  assert.equal(restoredStepStatus({ type: 'analyzing', status: 'completed' }, { status: 'completed', state_json: { stop_reason: 'analysis_unavailable' } }), 'failed')
  assert.equal(restoredStepStatus({ type: 'reviewing', status: 'completed' }, { status: 'completed', state_json: { stop_reason: 'review_unavailable' } }), 'failed')
})
test('paused and failed checkpoints restore active step status', () => {
  assert.equal(restoredStepStatus({ type: 'writing', status: 'running' }, { status: 'paused' }), 'paused')
  assert.equal(restoredStepStatus({ type: 'writing', status: 'running' }, { status: 'failed' }), 'failed')
})
test('numeric score does not imply approval', () => {
  assert.equal(reviewPresentation({ quality_score: 9, quality_review_status: 'confirmed' }).passed, false)
  assert.equal(reviewPresentation({ quality_score: 9, review_verdict: 'needs_revision' }).passed, false)
})
test('confirmed but failed report has warning', () => {
  assert.match(withQualityReviewNotice('report', { quality_score: 9, quality_review_status: 'confirmed', review_verdict: 'needs_revision' }), /审核未通过/)
})
test('unconfirmed and approved results differ', () => {
  assert.match(withQualityReviewNotice('report', { quality_score: null, quality_review_status: 'unconfirmed' }), /待确认/)
  assert.equal(withQualityReviewNotice('report', { quality_score: 9, review_verdict: 'pass', outcome: 'passed' }), 'report')
})
test('server quality summary is not duplicated', () => {
  const report = '<!-- research-quality-summary --> report'
  assert.equal(withQualityReviewNotice(report, { quality_score: null }), report)
})
const { resolveClaimEvidence, mergeScienceData, resolveLocalDocumentSource } = load('src/api/research-types.ts')
const data = { claims: [{ claim_id: 'claim:a', claim_text: 'result', evidence_ids: ['ev1'], evidence_links: [{ evidence_id: 'ev1', asset_id: 'table1', document_version: 1, quote: '91' }] }], evidenceLedger: { ev1: { title: 'Paper', document_version: 1 } } }

test('report_draft claims synchronize with the same resumed message evidence snapshot', () => {
  const before = { evidenceLedger: data.evidenceLedger, claims: [] }
  const after = mergeScienceData(before, { content: '[source](#claim-evidence:claim%3Aa:0)', claims: data.claims })
  assert.equal(resolveClaimEvidence('#claim-evidence:claim%3Aa:0', after).link.asset_id, 'table1')
  assert.equal(after.evidenceLedger, before.evidenceLedger)
  assert.equal(before.claims.length, 0)
})

test('revision replaces claim identities without borrowing claims from another report', () => {
  const after = mergeScienceData(data, { claims: [{ ...data.claims[0], claim_id: 'claim:revised' }] })
  assert.equal(resolveClaimEvidence('#claim-evidence:claim%3Aa:0', after), undefined)
  assert.ok(resolveClaimEvidence('#claim-evidence:claim%3Arevised:0', after))
  assert.ok(resolveClaimEvidence('#claim-evidence:claim%3Aa:0', data))
  assert.equal(resolveClaimEvidence('#claim-evidence:claim%3Aa:0', mergeScienceData(data, { claims: [] })), undefined)
})

test('legacy local source links resolve only saved, versioned report identities', () => {
  const kb = '11111111-1111-1111-1111-111111111111', doc = '22222222-2222-2222-2222-222222222222'
  const href = `/knowledge-bases/${kb}/documents/${doc}/download`
  const source = { title: 'owned', knowledge_base_id: kb, document_id: doc, document_version: 'v1' }
  const snapshot = { evidenceLedger: { ev1: source } }
  assert.equal(resolveLocalDocumentSource(href, snapshot), source)
  for (const unsafe of [href + '?token=secret', href + '#page=1', 'https://example.com' + href, '//example.com' + href,
    href.replace(doc, '33333333-3333-3333-3333-333333333333')]) assert.equal(resolveLocalDocumentSource(unsafe, snapshot), undefined)
  assert.equal(resolveLocalDocumentSource(href, { evidenceLedger: {} }), undefined)
  assert.equal(resolveLocalDocumentSource(href, { evidenceLedger: { ev1: { ...source, document_version: undefined } } }), undefined)
  assert.equal(resolveLocalDocumentSource(href, { evidenceLedger: { ev1: source, ev2: { ...source, document_version: 'v2' } } }), undefined)
})
test('citation is scoped to displayed report snapshot', () => {
  const resolved = resolveClaimEvidence('#claim-evidence:claim%3Aa:0', data)
  assert.equal(resolved.link.asset_id, 'table1')
  assert.equal(resolved.link.document_version, 1)
  assert.equal(resolveClaimEvidence('#claim-evidence:claim%3Aa:0', { claims: [], evidenceLedger: {} }), undefined)
})
test('unknown, malformed, and unbound links are rejected', () => {
  for (const href of ['https://example.com', '#claim-evidence:%ZZ:0', '#claim-evidence:claim%3Aa:-1', '#claim-evidence:claim%3Aa:9']) assert.equal(resolveClaimEvidence(href, data), undefined)
  assert.equal(resolveClaimEvidence('#claim-evidence:claim%3Aa:0', { ...data, claims: [{ ...data.claims[0], evidence_ids: [] }] }), undefined)
})
console.log(`${count} frontend workflow checks passed`)
