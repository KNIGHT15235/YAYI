"""Bounded real-model SSE test on synthetic inputs; no web search or user documents."""
import collections
import json
import time
import uuid
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=240)
results = []
session_id = 'audit-research-' + uuid.uuid4().hex
def check(name, passed, **details):
    row = {'test': name, 'passed': bool(passed), **details}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

try:
    # A chat without session_id creates no Redis conversation and tests real streaming.
    response = client.post('/chat/completion/v3', json={
        'question': '功能测试，请只回复中文“核对通过”，不要解释。',
        'search_web': False, 'search_knowledge': False})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: {')]
    answer = ''.join(e.get('content', '') for e in events if not e.get('thinking'))
    check('real chat SSE decoded answer', response.status_code == 200 and '核对通过' in answer,
          status=response.status_code, answer=answer[:150])
    counts = collections.Counter()
    complete = None
    errors = []
    started = time.monotonic()
    query = ('这是软件集成测试，以下完全是虚构数据：银杏测试企业2023年营收10万元，2024年20万元，2025年30万元。'
             '请只依据题目提供数据生成简短三章分析，说明测试性质，不调用网络、不补充市场事实，每章约100字，'
             '包含一张趋势图，缺乏来源应明确标注为测试输入。')
    with client.stream('POST', '/research/stream', json={
        'query': query, 'session_id': session_id, 'version': 'v2',
        'max_iterations': 1, 'search_modes': []}, timeout=90) as stream:
        check('real research HTTP SSE', stream.status_code == 200,
              content_type=stream.headers.get('content-type'))
        for line in stream.iter_lines():
            if time.monotonic() - started > 720:
                client.post('/research/cancel/' + session_id)
                check('real research within audit time bound', False)
                break
            if not line.startswith('data: ') or line == 'data: [DONE]':
                continue
            event = json.loads(line[6:])
            event_type = event.get('type', 'unknown')
            counts[event_type] += 1
            if event_type in ('phase', 'error', 'research_complete'):
                print(json.dumps({'event': event_type, 'phase': event.get('phase'),
                                  'elapsed_s': round(time.monotonic()-started)}, ensure_ascii=False), flush=True)
            if event_type == 'research_complete':
                complete = event
            if event_type == 'error':
                errors.append(str(event.get('content', ''))[:250])
    check('real six-agent research completion', complete is not None and not errors,
          elapsed_s=round(time.monotonic()-started), events=dict(counts), errors=errors,
          report_chars=len(complete.get('final_report', '')) if complete else 0,
          chart_count=complete.get('charts_count') if complete else 0)
    checkpoint_response = client.get('/research/checkpoint/' + session_id + '/full').json()
    checkpoint = checkpoint_response.get('checkpoint', {})
    check('real research final checkpoint', checkpoint.get('status') == 'completed',
          checkpoint_status=checkpoint.get('status'), response_keys=list(checkpoint))
except Exception as error:
    check('real model test exception', False, error=type(error).__name__ + ': ' + str(error)[:200])
finally:
    try:
        response = client.delete('/research/checkpoint/' + session_id)
        check('cleanup audit research checkpoint', response.status_code == 200)
    finally:
        client.close()
        (root / 'audit' / 'smoke_research_live.json').write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
