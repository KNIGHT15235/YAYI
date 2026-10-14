import httpx, json
from pathlib import Path

url='https://api.crossref.org/works'
params={'query.bibliographic':'optical remote sensing change detection',
    'filter':'from-pub-date:2020-01-01,until-pub-date:2026-09-29,type:journal-article', 'rows':100}
r=httpx.get(url, params=params, timeout=60, follow_redirects=True)
print('Crossref status',r.status_code)
r.raise_for_status()
items=r.json().get('message',{}).get('items',[])
Path(__file__).with_name('crossref_probe.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
print('Items',len(items),'abstracts',sum(bool(x.get('abstract')) for x in items))
print(json.dumps([(x.get('title'),x.get('DOI'),len(x.get('abstract',''))) for x in items[:12]],ensure_ascii=False))
