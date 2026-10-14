"""Read back a study completed and saved by the actual browser UI."""
import json,time
from datetime import datetime,timezone
from demo_access import client,ROOT

OUT=ROOT/'audit'
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

c,_=client();run=json.loads((OUT/'demo-run.json').read_text(encoding='utf-8'));sid=run['session_id']
last=None
for _ in range(180):
    response=c.get(f'/research/checkpoint/{sid}/full');response.raise_for_status()
    envelope=response.json();checkpoint=envelope.get('checkpoint',{})
    state=checkpoint.get('state_json') or {}
    signal=(checkpoint.get('status'),checkpoint.get('phase'),checkpoint.get('iteration'))
    if signal!=last:
        print(datetime.now().isoformat(timespec='seconds'),signal,flush=True);last=signal
    if checkpoint.get('status')=='failed':
        save('demo-checkpoint.json',envelope)
        raise RuntimeError(checkpoint.get('error_message') or 'Research failed')
    if checkpoint.get('status')=='completed':
        history_response=c.get(f'/sessions/{sid}');history_response.raise_for_status();history=history_response.json()
        assistants=[m for m in history['messages'] if m['role']=='assistant' and m['content']]
        if assistants and assistants[-1]['content'].startswith(checkpoint.get('final_report') or '\0'):
            result={k:state.get(k) for k in ('final_report','quality_score','references','charts','knowledge_graph','papers',
                'evidence_ledger','claims','claim_verification','evidence_assessment','hypotheses','corpus_statistics',
                'profile_id','quality_dimensions','quality_review_status','quality_review_note')}
            result.update(type='research_complete',iterations=state.get('iteration'),
                final_report=checkpoint['final_report'],retrieved_from='completed checkpoint and browser-saved history')
            if assistants[-1]['content']!=checkpoint['final_report']:
                result['history_quality_notice']=assistants[-1]['content'][len(checkpoint['final_report']):]
            save('demo-result.json',result);save('demo-checkpoint.json',envelope);save('demo-history.json',history)
            (OUT/'demo-report.md').write_text(result['final_report'],encoding='utf-8')
            save('demo-run-summary.json',{'session_id':sid,'execution':'API start, real cancellation, browser resume and automatic history save',
                'papers':len(result['papers']),'claims':len(result['claims']),'claim_verification':result['claim_verification'],
                'charts':len(result['charts']),'history_messages':history['message_count'],
                'finished_at':datetime.now(timezone.utc).isoformat()})
            print('BROWSER_HISTORY_VERIFIED',sid,'papers',len(result['papers']),flush=True)
            break
    time.sleep(10)
else:raise TimeoutError('No completed report saved by the browser within 30 minutes')
