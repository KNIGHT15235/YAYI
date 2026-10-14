"""Public scholarly metadata retrieval with reproducible, DOI-grounded provenance.

Crossref responses verify bibliographic identity, not the scientific truth of claims.
Only publisher-deposited abstracts are used as reading evidence here. Full text is
never inferred from a title, and metadata-only records are identified explicitly.
"""
import asyncio
import hashlib
import html
import inspect
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)
API = 'https://api.crossref.org/works'
CACHE_VERSION = 4
CACHE_DIR = Path(os.getenv('LITERATURE_CACHE_DIR', str(Path(__file__).resolve().parents[3] / 'storage' / 'literature')))


def plain_text(value: Any) -> str:
    text = re.sub(r'<[^>]+>', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def query_scope(query: str) -> dict:
    years = [int(y) for y in re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query)]
    today = date.today()
    start, end = (min(years), max(years)) if years else (today.year - 5, today.year)
    end = min(end, today.year)
    if start > end:
        raise ValueError('研究起始年份晚于当前年份')
    optical_cd = bool(re.search(r'变化检测|change\s+detection', query, re.I) and re.search(r'遥感|optical|remote\s+sensing', query, re.I))
    if optical_cd:
        searches = [
            'optical remote sensing image change detection',
            'remote sensing change detection transformer siamese deep learning',
            'high resolution aerial building change detection attention',
            'remote sensing change detection foundation model SAM Mamba',
            'remote sensing change detection generalization self supervised',
            'optical remote sensing change detection review benchmark',
        ]
    else:
        cleaned = re.sub(r'围绕|开展文献调研|生成文献综述|请|文献综述|[，。]', ' ', query)
        searches = [re.sub(r'\s+', ' ', cleaned).strip()]
    return {'start_year': start, 'end_year': end, 'until': min(date(end,12,31),today).isoformat(),
        'original_query': query,
        'optical_change_detection': optical_cd, 'searches': searches}


class RetrievalBudgetExhausted(Exception):
    """A persisted study-wide budget has been consumed; keep acquired evidence."""


class RetrievalBudget:
    """Charge actual HTTP attempts and inspected records before the work occurs.

    Counters live directly in checkpoint state. An interrupted request is charged,
    and retrying it costs another request; cache hits never consume HTTP budget.
    """
    def __init__(self, counters, limits, *, deadline=None):
        self.counters, self.limits, self.deadline = counters, limits, deadline
        self.exhausted_reason = None

    def check_time(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.exhausted_reason = 'time_budget'
            raise RetrievalBudgetExhausted('time_budget')

    def charge(self, kind):
        self.check_time()
        key, limit = {'request': ('requests_used', 'max_requests'),
                      'document': ('documents_used', 'max_documents')}[kind]
        if int(self.counters.get(key, 0)) >= int(self.limits[limit]):
            self.exhausted_reason = limit
            raise RetrievalBudgetExhausted(limit)
        self.counters[key] = int(self.counters.get(key, 0)) + 1


def targeted_searches(scope, terms=None):
    """Keep the original scope separate from the new, effective provider query."""
    if not terms:
        return list(scope['searches'])
    anchor = scope['searches'][0]
    result = []
    for value in terms:
        term = plain_text(value)[:700]
        if not term:
            continue
        # A follow-up mentioning a year cannot expand the original date filter.
        actual = term if anchor.casefold() in term.casefold() else anchor + ' ' + term
        if actual.casefold() not in {x.casefold() for x in result}:
            result.append(actual)
    return result or list(scope['searches'])


def publication_date(item: dict) -> Optional[date]:
    dates = []
    for key in ('published-online', 'published-print', 'published', 'issued'):
        for parts in item.get(key, {}).get('date-parts', []):
            try:
                dates.append(date(parts[0], parts[1] if len(parts)>1 else 1, parts[2] if len(parts)>2 else 1))
            except (ValueError, TypeError, IndexError):
                pass
    return min(dates) if dates else None


def method_tags(text: str) -> list[str]:
    patterns = [
        ('基础模型与预训练', r'foundation model|segment anything|\bSAM\b|pre.train|vision.language|vision language'),
        ('状态空间与Mamba', r'\bmamba\b|state.space'),
        ('Transformer与注意力', r'transformer|attention|token'),
        ('孪生与卷积网络', r'siamese|convolution|\bCNN\b|\bUNet\b|U.Net|deep learning|neural network'),
        ('弱监督与自监督', r'self.supervis|semi.supervis|weak.supervis|unsupervis|contrastive'),
        ('传统与统计方法', r'copula|change vector|threshold|random forest|support vector|statistical'),
    ]
    return [label for label, pattern in patterns if re.search(pattern,text,re.I)] or ['其他变化检测方法']


def relevant(title: str, abstract: str, scope: dict) -> bool:
    if not scope['optical_change_detection']:
        # Match original-topic anchors, never generated follow-up words. These
        # guards remove obvious fuzzy-search drift while retaining multilingual
        # records. Arbitrary untranslated Chinese topics still rely on the
        # anchored provider query and subsequent evidence/claim review.
        original = scope.get('original_query', '')
        combined = title + ' ' + abstract
        aliases = {
            '遥感': r'remote[ -]?sensing|遥感', '量子': r'quantum|量子',
            '脑电': r'electroencephal|\bEEG\b|脑电', '纠错': r'error[ -]?correct|纠错',
            '蛋白质': r'protein|蛋白质', '基因': r'genetic|genom|gene\b|基因',
            '药物': r'drug|pharmac|药物', '医学影像': r'medical imag|medical image|医学影像',
            '医学图像': r'medical imag|medical image|医学图像',
            '知识图谱': r'knowledge graph|知识图谱', '机器学习': r'machine learning|机器学习',
            '深度学习': r'deep learning|neural network|深度学习',
            '大语言模型': r'large language model|\bLLM[s]?\b|大语言模型',
            '锂电池': r'lithium|li.ion|锂电池', '钙钛矿': r'perovskite|钙钛矿',
        }
        anchors = [pattern for term, pattern in aliases.items() if term in original]
        if anchors and not all(re.search(pattern, combined, re.I) for pattern in anchors):
            return False
        ignored = {'around', 'about', 'between', 'from', 'through', 'research', 'review', 'literature',
                   'study', 'studies', 'survey', 'generate', 'methods', 'method', 'analysis', 'please',
                   'conduct', 'write', 'recent', 'current', 'state', 'with', 'into', 'year', 'years',
                   'models', 'model', 'based', 'using', 'applications', 'application'}
        words = list(dict.fromkeys(w.lower() for w in re.findall(r'[A-Za-z][A-Za-z-]{3,}', original)
                                   if w.lower() not in ignored))
        if words:
            hits = sum(bool(re.search(r'\b' + re.escape(w) + r'\b', combined, re.I)) for w in words)
            return hits >= min(2, len(words))
        return True
    t = title.lower()
    if not re.search(r'change[ -]?detection|change[ -]?detecting', t):
        return False
    # The demonstration is optical image CD, not radar/hyperspectral or
    # cross-modality change detection, ecological time-series, or medical CD.
    if re.search(r'\bSAR\b|radar|polarimetric|hyperspectral|heterogeneous|cross.modality|multimodal|multi.modal|optical.sar|sar.optical', title, re.I):
        return False
    combined = title+' '+abstract
    return bool(re.search(r'remote.sensing|optical|aerial|satellite|LEVIR|WHU.CD|SYSU.CD|building change', combined,re.I))


def normalize(item: dict, scope: dict) -> Optional[dict]:
    title = plain_text((item.get('title') or [''])[0])
    doi = str(item.get('DOI') or '').strip().lower()
    abstract = plain_text(item.get('abstract'))
    published = publication_date(item)
    if not title or not re.match(r'^10\.\d{4,9}/\S+$',doi):
        return None
    if item.get('type') not in ('journal-article','proceedings-article','posted-content'):
        return None
    if not published or not scope['start_year'] <= published.year <= scope['end_year'] or published > date.today():
        return None
    if not relevant(title,abstract,scope):
        return None
    # Corrections/retractions are not counted as distinct research papers.
    if re.search(r'^(correction|erratum|retraction|corrigendum)\b',title,re.I) or item.get('update-to'):
        return None
    authors = [' '.join(x for x in (a.get('given',''),a.get('family','')) if x).strip() or a.get('name','') for a in item.get('author',[])]
    authors = [a for a in authors if a]
    source_id = 'paper_' + hashlib.sha256(doi.encode()).hexdigest()[:20]
    metadata_url = API + '/' + quote(doi,safe='')
    return {
        'source_id':source_id, 'id':source_id, 'title':title, 'doi':doi,
        'url':'https://doi.org/'+doi, 'year':published.year, 'publication_date':published.isoformat(),
        'authors':authors, 'author':'; '.join(authors),
        'venue':plain_text((item.get('container-title') or [''])[0]),
        'abstract':abstract, 'content':abstract or title, 'snippet':abstract or title,
        'provider':'Crossref', 'source_type':'academic', 'document_type':item.get('type'),
        'verified':True, 'verification':{
            'identity':'registered_doi', 'metadata_url':metadata_url,
            'checked_at':datetime.now(timezone.utc).isoformat(),
            'content_level':'publisher_abstract' if abstract else 'metadata_only',
            'claim_support':'requires_claim_review',
        },
        'evidence_level':'abstract' if abstract else 'metadata',
        'method_tags':method_tags(title+' '+abstract),
        'citation_count':item.get('is-referenced-by-count',0),
        'metadata_source':metadata_url,
    }


async def _notify(callback, event):
    if callback:
        result = callback(event)
        if inspect.isawaitable(result):
            await result


async def _request(client, params, budget=None):
    # A model may trace an already acquired DOI. Resolve that identity directly
    # instead of letting a bibliographic fuzzy search substitute a different work.
    dois = re.findall(r'10\.\d{4,9}/[^\s"<>]+', str(params.get('query.bibliographic', '')), re.I)
    doi = dois[0].rstrip('.,;') if len(dois) == 1 else None
    url = API + '/' + quote(doi, safe='') if doi else API
    for attempt in range(3):
        try:
            if budget:
                budget.charge('request')
            response = await client.get(url,params={} if doi else params)
            if response.status_code in (429,502,503,504) and attempt < 2:
                try: delay = min(12,max(1,float(response.headers.get('retry-after','2'))))
                except ValueError: delay=2
                await asyncio.sleep(delay*(attempt+1))
                continue
            response.raise_for_status()
            message = response.json()['message']
            return [message] if doi else message['items']
        except (httpx.RequestError,httpx.HTTPStatusError,KeyError,ValueError):
            if attempt == 2:
                raise
            await asyncio.sleep(attempt+1)
    return []


def _select(papers: list[dict], limit: int) -> list[dict]:
    # Prefer reading evidence, then sample across the requested years. Counts
    # describe the retrieved sample, never the complete scientific literature.
    groups=defaultdict(list)
    for paper in papers:
        groups[paper['year']].append(paper)
    for group in groups.values():
        group.sort(key=lambda x:(bool(x['abstract']),len(x['abstract'])>=400,x['citation_count']),reverse=True)
    chosen=[]
    while groups and len(chosen)<limit:
        for year in sorted(list(groups)):
            chosen.append(groups[year].pop(0))
            if not groups[year]:del groups[year]
            if len(chosen)>=limit:break
    return sorted(chosen,key=lambda x:(x['year'],x['title'].casefold()))


async def _arxiv(client, scope: dict, search_terms=None, budget=None) -> list[dict]:
    if not scope['optical_change_detection']:
        return []
    search='ti:"change detection" AND (all:"remote sensing" OR all:"optical" OR all:"aerial")'
    if search_terms:
        # Treat generated terms as data, not arXiv query-language operators.
        focus = ' '.join(plain_text(t) for t in search_terms)
        tokens = re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}', focus)
        ignored = {'and', 'or', 'not', 'all', 'change', 'detection', 'remote', 'sensing', 'optical', 'image', 'images', 'research', 'evidence'}
        tokens = list(dict.fromkeys(t.lower() for t in tokens if t.lower() not in ignored))[:16]
        if tokens:
            search += ' AND (' + ' OR '.join('all:"' + t + '"' for t in tokens) + ')'
    search+=f" AND submittedDate:[{scope['start_year']}01010000 TO {scope['until'].replace('-','')}2359]"
    if budget:
        budget.charge('request')
    response=await client.get('https://export.arxiv.org/api/query',params={
        'search_query':search,'start':0,'max_results':80,'sortBy':'relevance','sortOrder':'descending'})
    response.raise_for_status()
    root=ET.fromstring(response.content)
    ns={'a':'http://www.w3.org/2005/Atom','ar':'http://arxiv.org/schemas/atom'}
    papers=[]
    for entry in root.findall('a:entry',ns):
        if budget:
            try:
                budget.charge('document')
            except RetrievalBudgetExhausted:
                break
        title=plain_text(entry.findtext('a:title','',ns))
        abstract=plain_text(entry.findtext('a:summary','',ns))
        if not relevant(title,abstract,scope):continue
        identifier=entry.findtext('a:id','',ns).rsplit('/',1)[-1]
        if not re.match(r'^\d{4}\.\d{4,5}(v\d+)?$',identifier):continue
        identifier=re.sub(r'v\d+$','',identifier)
        published=entry.findtext('a:published','',ns)[:10]
        try:
            publication=date.fromisoformat(published)
            year=publication.year
        except ValueError:continue
        if not scope['start_year']<=year<=scope['end_year'] or publication>date.fromisoformat(scope['until']):continue
        doi=entry.findtext('ar:doi','',ns).strip().lower()
        authors=[plain_text(x.findtext('a:name','',ns)) for x in entry.findall('a:author',ns)]
        url='https://arxiv.org/abs/'+identifier
        source_id='paper_'+hashlib.sha256((doi or url).encode()).hexdigest()[:20]
        papers.append({'source_id':source_id,'id':source_id,'title':title,'doi':doi,'arxiv_id':identifier,
            'url':('https://doi.org/'+doi) if doi else url,'arxiv_url':url,'pdf_url':'https://arxiv.org/pdf/'+identifier,
            'year':year,'publication_date':published,'authors':authors,'author':'; '.join(authors),'venue':'arXiv',
            'abstract':abstract,'content':abstract,'snippet':abstract,'provider':'arXiv','source_type':'academic',
            'document_type':'preprint','verified':True,'verification':{'identity':'arxiv_record',
                'metadata_url':url,'checked_at':datetime.now(timezone.utc).isoformat(),
                'content_level':'author_abstract','claim_support':'requires_claim_review'},
            'evidence_level':'abstract','method_tags':method_tags(title+' '+abstract),'citation_count':0,'metadata_source':url})
    return papers


async def collect_literature(query: str, min_papers: int=60, progress: Optional[Callable]=None,
                             *, original_scope=None, search_terms=None, budget=None,
                             on_papers=None) -> list[dict]:
    """Collect real unique papers; never pad a short retrieval with LLM records."""
    minimum=max(1,min(int(min_papers),200))
    scope=dict(original_scope) if original_scope else query_scope(query)
    actual_queries=targeted_searches(scope,search_terms)
    key=hashlib.sha256(json.dumps([CACHE_VERSION,minimum,scope,actual_queries],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    CACHE_DIR.mkdir(parents=True,exist_ok=True)
    cache=CACHE_DIR/(key+'.json')
    if cache.exists() and time.time()-cache.stat().st_mtime<86400:
        try:
            data=json.loads(cache.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            data={}
        papers=data.get('papers',[])
        if data.get('complete') or len(papers)>=minimum:
            retained=[]
            for row in papers:
                if budget:
                    try: budget.charge('document')
                    except RetrievalBudgetExhausted: break
                retained.append(row)
            papers=retained
            if on_papers:
                await _notify(on_papers,papers)
            await _notify(progress,{'type':'literature_progress','provider':'Crossref','papers_count':len(papers),'cached':True,'message':'复用已核对 DOI 的论文检索记录'})
            return papers
    collected={}
    titles=set()
    errors=[]
    query_log=[]
    stopped=False
    filters=f"from-pub-date:{scope['start_year']}-01-01,until-pub-date:{scope['until']}"
    headers={'User-Agent':'YAYI-Research/1.0 (scholarly literature research; local application)','Accept':'application/json'}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60,connect=15),follow_redirects=True,headers=headers) as client:
        for term in actual_queries:
            params={'query.bibliographic':term,'filter':filters,'rows':100,'sort':'relevance'}
            try:
                records=await _request(client,params,budget=budget)
                query_log.append({'query':term,'count':len(records),'provider':'Crossref'})
                for item in records:
                    if budget:
                        try: budget.charge('document')
                        except RetrievalBudgetExhausted as exc:
                            errors.append({'query':term,'error':str(exc)})
                            stopped=True
                            break
                    paper=normalize(item,scope)
                    if not paper:continue
                    title_key=re.sub(r'\W','',paper['title'].casefold())
                    existing=collected.get(paper['doi']) or next((p for p in collected.values() if re.sub(r'\W','',p['title'].casefold())==title_key),None)
                    if existing:
                        if len(paper.get('abstract',''))>len(existing.get('abstract','')):
                            existing.update(paper)
                        continue
                    collected[paper['doi']]=paper
                    titles.add(title_key)
                if on_papers:
                    await _notify(on_papers,_select(list(collected.values()),min(120,max(minimum,minimum*2))))
                await _notify(progress,{'type':'literature_progress','provider':'Crossref','papers_count':len(collected),'abstracts_count':sum(bool(x['abstract']) for x in collected.values()),'message':f'已检索并按 DOI/题名去重 {len(collected)} 篇相关论文'})
            except RetrievalBudgetExhausted as exc:
                errors.append({'query':term,'error':str(exc)})
                stopped=True
            except (httpx.RequestError,httpx.HTTPStatusError,KeyError,ValueError) as exc:
                errors.append({'query':term,'error':type(exc).__name__})
                log.warning('Literature metadata query failed: %s',type(exc).__name__)
            if stopped or (len(collected)>=minimum*3 and sum(bool(x['abstract']) for x in collected.values())>=minimum*2):
                break
            await asyncio.sleep(0.5)
        try:
            arxiv=[] if stopped else await _arxiv(client,scope,search_terms=search_terms,budget=budget)
            by_title={re.sub(r'\W','',p['title'].casefold()):p for p in collected.values()}
            for paper in arxiv:
                title_key=re.sub(r'\W','',paper['title'].casefold())
                existing=collected.get(paper.get('doi')) or by_title.get(title_key)
                if existing:
                    existing['arxiv_url']=paper['arxiv_url']
                    existing['pdf_url']=paper['pdf_url']
                    if not existing['abstract']:
                        for field in ('abstract','content','snippet','evidence_level','method_tags'):
                            existing[field]=paper[field]
                        existing['verification']['content_level']='author_abstract'
                        existing['verification']['content_source']=paper['arxiv_url']
                else:
                    collected[paper.get('doi') or paper['arxiv_url']]=paper
            query_log.append({'query':'arXiv topic search','count':len(arxiv),'provider':'arXiv'})
            if on_papers:
                await _notify(on_papers,_select(list(collected.values()),min(120,max(minimum,minimum*2))))
        except RetrievalBudgetExhausted as exc:
            errors.append({'query':'arxiv','error':str(exc)})
            stopped=True
        except (httpx.RequestError,httpx.HTTPStatusError,ET.ParseError,ValueError) as exc:
            errors.append({'query':'arxiv','error':type(exc).__name__})
            log.warning('arXiv metadata unavailable: %s',type(exc).__name__)
    papers=_select(list(collected.values()),min(120,max(minimum,minimum*2)))
    stopped = stopped or bool(budget and budget.exhausted_reason)
    data={'schema_version':CACHE_VERSION,'query':query,'scope':scope,'queries':query_log,'errors':errors,'complete':not stopped and not errors,
        'retrieved_at':datetime.now(timezone.utc).isoformat(),'candidates_count':len(collected),
        'papers_count':len(papers),'abstracts_count':sum(bool(x['abstract']) for x in papers),
        'years':dict(sorted(Counter(x['year'] for x in papers).items())),'papers':papers}
    # A budget-limited result must not replace a complete cache entry.
    if not stopped:
        cache.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    await _notify(progress,{'type':'literature_progress','provider':'Crossref/arXiv','papers_count':len(papers),'abstracts_count':data['abstracts_count'],'message':f'完成文献筛选：{len(papers)} 篇，其中 {data["abstracts_count"]} 篇具有可追溯摘要','complete':True,'minimum_met':len(papers)>=minimum})
    if len(papers)<minimum:
        log.warning('Only %s/%s verified papers retrieved; do not invent the remainder',len(papers),minimum)
    return papers
