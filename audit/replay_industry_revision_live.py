"""Replay actual public industry draft through the repaired revision and Review stages.

This is a separate audit fixture/session, not a new full retrieval run. The source
run and formal scientific showcase are retained unchanged.
"""
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from demo_access import client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'audit/review-only-live'
load_dotenv(ROOT / 'backend/.env')
sys.path.insert(0, str(ROOT / 'backend/app'))
from service.checkpoint_service import get_checkpoint_service


def main():
    source = json.loads((OUT / 'industry-resumed-checkpoint.json').read_text(encoding='utf-8'))
    events = [json.loads(line) for line in (OUT / 'industry-resumed-events.jsonl').read_text(encoding='utf-8').splitlines()]
    draft = next(e['content']['content'] for e in events if e.get('type') == 'report_draft')
    assert len(draft) > 6000, 'The authentic original draft must exercise the former truncation'
    state = copy.deepcopy(source['state_json'])
    assert state['research_profile']['mode'] == 'industry'
    assert state['search_local'] is False and not state.get('kb_name')
    c, _ = client()
    owner = c.get('/auth/me').json()['id']
    response = c.post('/sessions', json={'title': '行业修订完整性复测 · 0930', 'session_type': 'deepsearch'})
    response.raise_for_status()
    sid = response.json()['id']
    c.post(f'/sessions/{sid}/messages', json={'role': 'user', 'content': state['query']}).raise_for_status()
    state.update(session_id=sid, phase='revising', _next_step='revising', final_report=draft,
                 _user_id=owner, audit_stage_replay={'source_session': source['session_id'],
                 'stage': 'industry_revision', 'original_draft_chars': len(draft),
                 'note': 'Replay of actual public draft and feedback; not a fresh retrieval run'})
    ui = copy.deepcopy(source.get('ui_state_json') or {})
    ui['final_report'] = draft
    checkpoint = get_checkpoint_service().save_checkpoint(sid, state, user_id=owner,
                                                          ui_state=ui, final_report=draft)
    assert checkpoint, 'Could not save isolated replay fixture'
    (OUT / 'industry-revision-replay-origin.json').write_text(json.dumps({
        'session_id': sid, 'source_session': source['session_id'],
        'original_draft_chars': len(draft), 'kind': 'targeted_stage_replay',
        'input_report': draft}, ensure_ascii=False, indent=2), encoding='utf-8')
    subprocess.run([sys.executable, '-u', str(ROOT / 'audit/verify_research_modes_live.py'),
                    'industry', '--resume-session', sid,
                    '--artifact-prefix', 'industry-revision-replay'], check=True)
    final = json.loads((OUT / 'industry-revision-replay-checkpoint.json').read_text(encoding='utf-8'))['state_json']
    expected_headings = re.findall(r'^## .+$', draft, flags=re.MULTILINE)
    missing_headings = [heading for heading in expected_headings if heading not in final['final_report']]
    assert not missing_headings, f'Missing original sections: {missing_headings}'
    print(json.dumps({'session_id': sid, 'input_chars': len(draft),
                      'output_chars': len(final['final_report']),
                      'sections_preserved': len(expected_headings),
                      'report_changed': draft != final['final_report'],
                      'quality_score': final.get('quality_score'),
                      'quality_review_status': final.get('quality_review_status')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
