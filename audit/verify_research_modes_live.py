"""Live authenticated regression; separate artifacts/history from the original showcase."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from demo_access import client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'audit' / 'review-only-live'
ORIGINAL = '164f6c9b-5eb2-400f-83d4-cb3f0b169997'
QUERIES = {
    'science': '围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。',
    'industry': '仅检索公开资料，调研城市轨道交通信号系统行业，比较产业链环节、主要企业与技术应用。资料不足处明确说明，不作市场规模预测。',
}


def save(name, value):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def original_digest(c):
    r = c.get(f'/research/checkpoint/{ORIGINAL}/full')
    r.raise_for_status()
    state = r.json()['checkpoint']['state_json']
    payload = {k: state.get(k) for k in ('final_report', 'claims', 'hypotheses', 'papers')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('inspect', 'science', 'industry'))
    parser.add_argument('--resume-session', help='Resume an existing audit session through the normal API')
    parser.add_argument('--artifact-prefix', help='Keep a separate artifact set for a targeted stage replay')
    args = parser.parse_args()
    c, _ = client()
    before = original_digest(c)
    if args.mode == 'inspect':
        sys.path.insert(0, str(ROOT / 'backend/app'))
        from dotenv import load_dotenv
        load_dotenv(ROOT / 'backend/.env')
        from service.research_guard import ResearchLease
        user = c.get('/auth/me').json()['id']
        lease = ResearchLease(user, 'audit-read-only')
        active = bool(lease.client.exists(lease.keys[0]))
        print(json.dumps({'active_research': active, 'original_digest': before}))
        save('original-before.json', {'digest': before})
        return
    mode = args.mode
    query = QUERIES[mode]
    if args.resume_session:
        sid = args.resume_session
    else:
        r = c.post('/sessions', json={'title': f'模式与补检验证 · {mode} · 0930', 'session_type': 'deepsearch'})
        r.raise_for_status()
        sid = r.json()['id']
        c.post(f'/sessions/{sid}/messages', json={'role': 'user', 'content': query}).raise_for_status()
    prefix = args.artifact_prefix or (f'{mode}-resumed' if args.resume_session else mode)
    params = {'query': query, 'session_id': sid, 'version': 'v2', 'profile_id': mode,
              'search_web': True, 'search_local': False, 'max_iterations': 1}
    if mode == 'science':
        params['min_papers'] = 60
    endpoint = f'/research/resume/{sid}' if args.resume_session else '/research/stream'
    request_body = {} if args.resume_session else params
    save(f'{prefix}-request.json', {'session_id': sid, 'endpoint': endpoint, 'request': request_body, 'original_digest': before})
    print(json.dumps({'session_id': sid, 'mode': mode}), flush=True)
    counts, phases, complete = {}, [], None
    with (OUT / f'{prefix}-events.jsonl').open('w', encoding='utf-8') as output:
        with c.stream('POST', endpoint, json=request_body,
                      timeout=httpx.Timeout(1800, connect=30, write=60, pool=60)) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                    continue
                event = json.loads(line[5:].strip())
                kind = event.get('type', '')
                counts[kind] = counts.get(kind, 0) + 1
                output.write(json.dumps(event, ensure_ascii=False) + '\n')
                output.flush()
                if kind == 'phase':
                    phases.append(event.get('phase'))
                if kind in ('research_complete', 'complete'):
                    complete = event
                if kind in ('phase', 'error', 'research_complete', 'review_search_decision', 'warning'):
                    print(datetime.now(timezone.utc).isoformat(), kind,
                          str(event.get('phase') or event.get('content') or '')[:250], flush=True)
    checkpoint = c.get(f'/research/checkpoint/{sid}/full')
    checkpoint.raise_for_status()
    full = checkpoint.json()['checkpoint']
    save(f'{prefix}-checkpoint.json', full)
    if not complete:
        raise RuntimeError('No completion event; see saved SSE and checkpoint')
    report = complete.get('final_report') or complete.get('report') or ''
    if not report:
        raise RuntimeError('Missing report')
    save(f'{prefix}-result.json', complete)
    (OUT / f'{prefix}-report.md').write_text(report, encoding='utf-8')
    science = {dest: complete.get(src) for src, dest in (
        ('papers', 'papers'), ('evidence_ledger', 'evidenceLedger'), ('claims', 'claims'),
        ('claim_verification', 'claimVerification'), ('evidence_assessment', 'evidenceAssessment'),
        ('hypotheses', 'hypotheses'), ('profile_id', 'profileId'))}
    c.post(f'/sessions/{sid}/messages', json={'role': 'assistant', 'content': report,
        'references_data': {'references': complete.get('references', []),
                            'charts': complete.get('charts', []), 'science_data': science}}).raise_for_status()
    state = full['state_json']
    summary = {'session_id': sid, 'status': full['status'], 'mode': state['research_profile']['mode'],
               'phases': phases, 'event_counts': counts, 'papers': len(state.get('papers', [])),
               'charts': len(state.get('charts', [])), 'claims': len(state.get('claims', [])),
               'verification': state.get('claim_verification'), 'retrieval': state.get('science_retrieval'),
               'quality_review_status': state.get('quality_review_status'),
               'review_search_round': state.get('review_search_round', 0),
               'analysis_search_round': state.get('analysis_search_round', 0),
               'original_showcase_unchanged': before == original_digest(c)}
    save(f'{prefix}-summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('verification', 'retrieval', 'event_counts')}, ensure_ascii=False), flush=True)
    assert summary['mode'] == mode and summary['original_showcase_unchanged']
    if mode == 'science':
        assert summary['analysis_search_round'] == 0
        assert summary['papers'] > 50 and summary['charts'] >= 2
        assert all(eid in state['evidence_ledger'] for claim in state['claims'] for eid in claim['evidence_ids'])


if __name__ == '__main__':
    main()
