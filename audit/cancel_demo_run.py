"""Verify real cancellation on the current diagnostic research run."""
import argparse,json,time
from demo_access import client,ROOT

parser=argparse.ArgumentParser()
parser.add_argument('--keep-title',action='store_true')
args=parser.parse_args()
c,_=client()
run=json.loads((ROOT/'audit/demo-run.json').read_text(encoding='utf-8'))
sid=run['session_id']
r=c.post(f'/research/cancel/{sid}');r.raise_for_status()
for _ in range(20):
    info=c.get(f'/research/checkpoint/{sid}').json()
    if info.get('checkpoint',{}).get('status')=='paused':break
    time.sleep(.5)
if not args.keep_title:
    c.put(f'/sessions/{sid}',json={'title':'联调记录：综述初轮审核与取消恢复'}).raise_for_status()
checkpoint=info.get('checkpoint',{})
result={'session_id':sid,'cancel_response':r.json(),'checkpoint_info':{
    key:checkpoint.get(key) for key in ('status','phase','iteration','error_message','updated_at')}}
(ROOT/'audit/demo-cancel-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
