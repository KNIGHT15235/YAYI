import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'/'app'))
from service.deep_research_v2.literature_sources import collect_literature

async def main():
    query='围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。'
    papers=await collect_literature(query,60,lambda x:print(json.dumps(x,ensure_ascii=False),flush=True))
    (ROOT/'audit'/'literature_candidates.json').write_text(json.dumps(papers,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FINAL papers',len(papers),'abstracts',sum(bool(p['abstract']) for p in papers))

asyncio.run(main())
