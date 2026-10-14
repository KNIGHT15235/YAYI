"""Audit a real completed run and export portable corpus figures."""
import json,re
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'audit'

def main():
    result=json.loads((OUT/'demo-result.json').read_text(encoding='utf-8'))
    papers=result['papers'];ledger=result['evidence_ledger'];claims=result['claims']
    refs=result['references']; graph=result['knowledge_graph']; stats=result['corpus_statistics']
    report=result['final_report']
    checks={}
    checks['more_than_50_papers']=len(papers)>50
    checks['unique_source_ids']=len({p['source_id'] for p in papers})==len(papers)
    checks['years_in_requested_range']=all(2020<=int(p['year'])<=2026 for p in papers)
    checks['paper_source_urls']=all(p.get('url','').startswith(('http://','https://')) for p in papers)
    checks['all_claims_have_valid_evidence']=all(c.get('evidence_ids') and all(i in ledger for i in c['evidence_ids']) for c in claims)
    checks['all_claims_supported']=bool(claims) and all(c.get('verification_status')=='supported' for c in claims)
    verification=result.get('claim_verification',{})
    checks['all_claims_reviewed']=verification.get('checked')==len(claims) and verification.get('unverified',0)==0
    nodes={n['id'] for n in graph['nodes']}
    checks['unique_graph_nodes']=len(nodes)==len(graph['nodes'])
    checks['valid_graph_endpoints']=all(e['source'] in nodes and e['target'] in nodes for e in graph['edges'])
    checks['all_papers_in_graph']=all(p['source_id'] in nodes for p in papers)
    years=dict(sorted(Counter(str(p['year']) for p in papers).items()))
    checks['year_statistics_recomputed']=years==stats['year_distribution']
    mentions=dict(Counter(tag for tags in stats['paper_tags'].values() for tag in set(tags)))
    checks['method_statistics_recomputed']=mentions==stats['method_mentions']
    checks['chart_data_matches_statistics']=all(c['data']==stats['year_distribution' if c['id']=='corpus_years' else 'method_mentions'] for c in result['charts'])
    ref_by_id={str(r['id']):r for r in refs}
    citations=re.findall(r'\[(\d+)\]\(([^)]*)\)',report)
    checks['citation_numbers_and_urls_match']=bool(citations) and all(n in ref_by_id and u==(ref_by_id[n].get('url') or ref_by_id[n].get('link','')) for n,u in citations)
    checks['no_internal_ids_in_prose']=not re.search(r'\[(?:ev|src|claim)_[^\]]*\]',report)
    history=json.loads((OUT/'demo-history.json').read_text(encoding='utf-8'))
    checks['history_contains_exact_report']=any(m['role']=='assistant' and m['content']==report for m in history['messages'])
    checks['has_explicit_conclusion']=bool(re.search(r'^## .*结论',report,re.M))
    summary={'checks':checks,'passed':sum(checks.values()),'total_checks':len(checks),'papers':len(papers),
        'content_bearing_papers':sum(p.get('evidence_level')!='metadata' and len(p.get('content') or p.get('abstract') or '')>=80 for p in papers),
        'references':len(refs),'claims':len(claims),'claim_statuses':dict(Counter(c.get('verification_status') for c in claims)),
        'body_cited_sources':len({n for n,u in citations}),'graph_nodes':len(nodes),'graph_edges':len(graph['edges']),
        'charts':len(result['charts']),'year_distribution':years,'method_mentions':mentions,
        'session_id':history['id'],'history_messages':history['message_count']}
    (OUT/'demo-output-audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
