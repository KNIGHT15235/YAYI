"""Real authenticated resume from a synthetic pre-analysis checkpoint."""
import json
import math
import secrets
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / 'backend' / '.env')
sys.path.insert(0, str(ROOT / 'backend' / 'app'))
from core.database import SessionLocal
from models import User
from service.checkpoint_service import get_checkpoint_service
from service.deep_research_v2.state import create_initial_state

results = []
username = 'alignment_resume_' + uuid.uuid4().hex[:10]
session_id = user_id = None
client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=90)


def check(name, passed, **details):
    row = {'test': name, 'passed': bool(passed), **details}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


try:
    response = client.post('/auth/register', json={'username': username, 'password': secrets.token_urlsafe(18), 'email': username + '@example.com'})
    response.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    user_id = client.get('/auth/me').json()['id']
    session_id = client.post('/sessions', json={'title': '恢复与图表合成测试'}).json()['id']
    question = '软件集成测试：请仅根据提供的虚构企业测试数据，生成一份简短的收入趋势报告和图表。明确说明数据是合成测试样本，不代表真实市场，不检索外部信息。'
    state = create_initial_state(question, session_id, search_web=False, search_local=False)
    state.update(phase='researching', _next_step='analyzing', max_iterations=1, version='v2')
    state['outline'] = [{'id': 'sec_a', 'title': '合成收入趋势', 'description': '用已提供的三年合成数据做趋势图与说明',
                         'status': 'researched', 'requires_data': True, 'requires_chart': True, 'section_type': 'quantitative'}]
    state['data_points'] = [{'id': f'data_{year}', 'name': f'{year}年合成企业收入', 'value': amount,
                             'unit': '测试单位', 'year': year, 'source': '本次合成测试输入', 'confidence': 1.0}
                            for year, amount in [(2023, 10), (2024, 20), (2025, 30)]]
    state['facts'] = [{'id': 'fact_a', 'content': '本次合成测试设定：虚构企业2023年收入10、2024年20、2025年30测试单位。仅用于软件验收，不代表真实市场。',
                       'source_name': '用户提供的合成测试数据', 'source_url': '', 'credibility_score': 1.0,
                       'related_sections': ['sec_a']}]
    checkpoints = get_checkpoint_service()
    check('seed only own synthetic checkpoint', checkpoints.save_checkpoint(session_id, state, user_id=user_id,
                                                                           ui_state={'audit_marker': 'preserved'}))
    checkpoints.update_status(session_id, 'paused', user_id=user_id)
    events = {}
    resumed = completed = False
    final = None
    started = time.monotonic()
    with client.stream('POST', f'/research/resume/{session_id}') as response:
        check('authenticated resume SSE accepted', response.status_code == 200)
        response.raise_for_status()
        for line in response.iter_lines():
            if time.monotonic() - started > 600:
                raise TimeoutError('bounded research test exceeded 600 seconds')
            if not line.startswith('data: '):
                continue
            if line[6:].strip() == '[DONE]':
                break
            item = json.loads(line[6:])
            event = item.get('type', 'unknown')
            events[event] = events.get(event, 0) + 1
            if event == 'research_resumed':
                resumed = True
            if event in ('phase', 'research_complete', 'error'):
                print(json.dumps({'event': event, 'phase': item.get('phase'), 'elapsed_s': int(time.monotonic() - started)}), flush=True)
            if event == 'research_complete':
                completed = True
    final = checkpoints.load_full_checkpoint(session_id, user_id=user_id)
    state = final.get('state_json', {}) if final else {}
    check('resume completes without redoing planning/search', resumed and completed and not events.get('outline') and not events.get('search_results'),
          elapsed_s=int(time.monotonic() - started), events=events)
    check('report and final checkpoint saved', bool(final and final.get('status') == 'completed' and len(final.get('final_report') or '') > 100),
          report_chars=len((final or {}).get('final_report') or ''))
    charts = state.get('charts', [])
    check('real model produces chart output from seeded data', bool(charts), charts=len(charts))
    score = state.get('quality_score')
    check('final weighted review has a valid score', isinstance(score, (int, float)) and not isinstance(score, bool)
          and math.isfinite(score) and 1 <= score <= 10 and state.get('quality_review_status') == 'confirmed',
          score=score, quality_review_status=state.get('quality_review_status'))
    weights = {'source_completeness': .3, 'logical_rigor': .3, 'objectivity': .2, 'timeliness': .1, 'completeness': .1}
    dimensions = state.get('quality_dimensions', {})
    check('real review score equals weighted dimensions', set(weights).issubset(dimensions)
          and all(isinstance(dimensions[key], (int, float)) and not isinstance(dimensions[key], bool)
                  and math.isfinite(dimensions[key]) and 1 <= dimensions[key] <= 10 for key in weights)
          and isinstance(score, (int, float))
          and abs(sum(dimensions[key] * value for key, value in weights.items()) - score) < .011,
          dimensions=dimensions)
    check('seeded UI state is preserved', (final.get('ui_state_json') or {}).get('audit_marker') == 'preserved')
finally:
    if session_id:
        try:
            client.post('/research/cancel/' + session_id)
            check('cleanup own checkpoint', get_checkpoint_service().delete_checkpoint(session_id, user_id=user_id))
            check('cleanup own session', client.delete('/sessions/' + session_id).status_code == 204)
        except Exception as error:
            check('cleanup own research resources', False, error=type(error).__name__)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user:
            db.delete(user)
            db.commit()
        check('cleanup own account', db.query(User).filter(User.username == username).first() is None)
    client.close()
    (ROOT / 'audit' / 'alignment-research-live-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

sys.exit(0 if results and all(row['passed'] for row in results) else 1)
