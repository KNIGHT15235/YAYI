"""Independently re-fetch canonical records; this checks identity, not claims."""
import argparse,asyncio,json,re,sys,time
from pathlib import Path
from urllib.parse import quote
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'/'app'))
from service.deep_research_v2.literature_sources import plain_text

def title_key(title):return re.sub(r'\W','',plain_text(title).casefold())

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='audit/literature_candidates.json')
    parser.add_argument('--output',default='audit/literature-source-audit.json')
    args=parser.parse_args()
    data=json.loads((ROOT/args.input).read_text(encoding='utf-8'))
    papers=data.get('papers',[]) if isinstance(data,dict) else data
    semaphore=asyncio.Semaphore(3)
    results=[]
    async with httpx.AsyncClient(timeout=45,follow_redirects=True,headers={'User-Agent':'YAYI-Research/1.0'}) as client:
        async def verify(paper):
            async with semaphore:
                result={'source_id':paper['source_id'],'title':paper['title'],'doi':paper.get('doi'),'url':paper['url']}
                url='https://api.crossref.org/works/'+quote(paper['doi'],safe='') if paper.get('doi') else paper.get('arxiv_url',paper['url'])
                for attempt in range(3):
                    try:
                        r=await client.get(url)
                        result['http_status']=r.status_code
                        if r.status_code in (429,502,503,504) and attempt<2:
                            await asyncio.sleep(2*(attempt+1));continue
                        r.raise_for_status()
                        if 'api.crossref.org' in url:
                            item=r.json()['message']
                            actual=plain_text(item['title'][0])
                            result.update(canonical_title=actual,title_match=title_key(actual)==title_key(paper['title']),doi_match=item['DOI'].lower()==paper['doi'].lower())
                            result['passed']=result['title_match'] and result['doi_match']
                        else:
                            from bs4 import BeautifulSoup
                            soup=BeautifulSoup(r.text,'html.parser')
                            meta=soup.find('meta',attrs={'name':'citation_title'})
                            actual=meta.get('content','') if meta else ''
                            result.update(canonical_title=actual,title_match=title_key(actual)==title_key(paper['title']))
                            result['passed']=result['title_match']
                        break
                    except Exception as exc:
                        result.update(passed=False,error=type(exc).__name__)
                        if attempt<2:await asyncio.sleep(attempt+1)
                results.append(result)
                if len(results)%10==0: print('Verified',len(results),'/',len(papers),'failures',sum(not x['passed'] for x in results),flush=True)
                await asyncio.sleep(.25)
        await asyncio.gather(*(verify(p) for p in papers))
        fixtures=ROOT/'audit/fixtures'
        fixtures.mkdir(exist_ok=True)
        pdf=fixtures/'BIT-2103.00208.pdf'
        if not pdf.exists():
            r=await client.get('https://arxiv.org/pdf/2103.00208')
            r.raise_for_status()
            if not r.content.startswith(b'%PDF'):raise ValueError('Not PDF')
            pdf.write_bytes(r.content)
        print('Real paper fixture',pdf.name,pdf.stat().st_size,flush=True)
    results.sort(key=lambda x:x['source_id'])
    summary={'total':len(results),'passed':sum(x['passed'] for x in results),'failed':sum(not x['passed'] for x in results),'check':'canonical source identity and title, not claim support','results':results}
    (ROOT/args.output).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False))

asyncio.run(main())
