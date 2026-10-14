"""Run the real showcase through authenticated SSE and retain its complete history."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from demo_access import client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'audit'
QUERY = '围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。'

def save(name, value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kb',default='')
    parser.add_argument('--resume',default='')
    parser.add_argument('--review-request',default='',help='JSON file with bounded additional-review options')
    args=parser.parse_args()
    c,account=client()
    if args.resume:
        sid=args.resume
    else:
        r=c.post('/sessions',json={'title':'2020—2026光学遥感变化检测文献综述','session_type':'deepsearch'})
        r.raise_for_status(); sid=r.json()['id']
        c.post(f'/sessions/{sid}/messages',json={'role':'user','content':QUERY}).raise_for_status()
    params=dict(query=QUERY,session_id=sid,version='v2',profile_id='science',min_papers=60,
                max_iterations=3,search_web=True,search_local=bool(args.kb),kb_name=args.kb or None)
    save('demo-run.json',{'session_id':sid,'username':account['username'],'request':params,
                         'started_at':datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'session_id':sid,'query':QUERY},ensure_ascii=False),flush=True)
    complete=None; counts={}; cancelled=False
    endpoint=f'/research/resume/{sid}' if args.resume else '/research/stream'
    resume_body=json.loads(Path(args.review_request).read_text(encoding='utf-8')) if args.review_request else None
    with (OUT/'demo-events.jsonl').open('a' if args.resume else 'w',encoding='utf-8') as stream:
        with c.stream('POST',endpoint,json=resume_body if args.resume else params,
                      timeout=httpx.Timeout(1800,connect=30,write=60,pool=60)) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':break
                event=json.loads(raw); kind=event.get('type','unknown')
                counts[kind]=counts.get(kind,0)+1
                stream.write(json.dumps(event,ensure_ascii=False)+'\n');stream.flush()
                if kind in ('complete','research_complete'):complete=event
                if kind=='research_cancelled':cancelled=True
                if kind not in ('thinking','token','report_chunk','content','heartbeat','log'):
                    short={k:v for k,v in event.items() if k in ('type','phase','agent','message','content','progress','count','total','checked')}
                    print(datetime.now().isoformat(timespec='seconds'),json.dumps(short,ensure_ascii=False)[:500],flush=True)
    checkpoint=c.get(f'/research/checkpoint/{sid}/full');checkpoint.raise_for_status()
    save('demo-checkpoint.json',checkpoint.json())
    if cancelled and checkpoint.json().get('checkpoint',{}).get('status')=='paused':
        print('RESEARCH_PAUSED',sid,'Continue in the browser or pass --resume.',flush=True)
        return
    if not complete:
        save('demo-failure.json',{'session_id':sid,'event_counts':counts})
        raise RuntimeError('SSE finished without a completion event; inspect demo-events.jsonl')
    save('demo-result.json',complete)
    report=complete.get('final_report') or complete.get('report') or ''
    if not report:raise RuntimeError('Completion returned no final report')
    (OUT/'demo-report.md').write_text(report,encoding='utf-8')
    science={dest:complete.get(src) for src,dest in (
        ('papers','papers'),('evidence_ledger','evidenceLedger'),('claims','claims'),
        ('claim_verification','claimVerification'),('evidence_assessment','evidenceAssessment'),
        ('hypotheses','hypotheses'))}
    payload={'role':'assistant','content':report,'references_data':{
        'references':complete.get('references',[]),'charts':complete.get('charts',[]),
        'science_data':science,'knowledge_graph':complete.get('knowledge_graph',{}),
        'corpus_statistics':complete.get('corpus_statistics',{})},'image_results':[]}
    r=c.post(f'/sessions/{sid}/messages',json=payload);r.raise_for_status()
    history=c.get(f'/sessions/{sid}');history.raise_for_status();save('demo-history.json',history.json())
    save('demo-run-summary.json',{'session_id':sid,'event_counts':counts,
        'papers':len(complete.get('papers',[])),'claims':len(complete.get('claims',[])),
        'claim_verification':complete.get('claim_verification'),
        'charts':len(complete.get('charts',[])),'history_messages':history.json()['message_count'],
        'finished_at':datetime.now(timezone.utc).isoformat()})
    print('HISTORY_SAVED',sid,'papers',len(complete.get('papers',[])),flush=True)

if __name__=='__main__':main()
