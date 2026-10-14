"""Package audited artifacts without changing model output or application state."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'audit'
SOURCE=ROOT.parent/'source/industry_information_assistant'

def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))

def main():
    result=read('demo-result.json'); source_audit=read('demo-literature-source-audit.json')
    verified={x['source_id']:x for x in source_audit['results']}
    assert len(result['papers'])==120
    assert all(p['source_id'] in verified and verified[p['source_id']]['passed'] and
               verified[p['source_id']]['url']==p['url'] and
               verified[p['source_id']]['title']==p['title'] for p in result['papers'])
    audit=read('demo-output-audit.json')
    assert audit['passed']==audit['total_checks']
    (OUT/'demo-corpus.json').write_text(json.dumps(result['papers'],ensure_ascii=False,indent=2),encoding='utf-8')
    for relative in ('frontend/src','backend/app'):
        assert (SOURCE/relative).is_dir()
    original={str(p.relative_to(SOURCE)):p for relative in ('frontend/src','backend/app')
              for p in (SOURCE/relative).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    current={str(p.relative_to(ROOT)):p for relative in ('frontend/src','backend/app')
             for p in (ROOT/relative).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    changes=[]; unchanged=0
    for key,p in original.items():
        if key not in current: changes.append({'file':key,'status':'missing'})
        elif p.read_bytes()==current[key].read_bytes():unchanged+=1
        else:changes.append({'file':key,'status':'modified'})
    for key in current.keys()-original.keys():changes.append({'file':key,'status':'added'})
    manifest={'original_application_files':len(original),'unchanged':unchanged,
              'changes':sorted(changes,key=lambda x:x['file'])}
    (OUT/'application-change-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    proof={'session_id':audit['session_id'],'canonical_source_audit_matches_final_corpus':True,
           'files':{name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in
             ('demo-result.json','demo-history.json','demo-checkpoint.json','demo-report.md',
              'demo-output-audit.json','demo-literature-source-audit.json','demo-knowledge-graph.json','demo-corpus.json')}}
    (OUT/'delivery-integrity.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'source_identity_match':True,'original_files':len(original),'unchanged':unchanged,
                      'modified':sum(x['status']=='modified' for x in changes),
                      'added':sum(x['status']=='added' for x in changes)},ensure_ascii=False))

if __name__=='__main__':main()
