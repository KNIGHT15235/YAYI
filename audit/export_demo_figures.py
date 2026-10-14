"""Export the final real corpus aggregates; do not invent performance charts."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import fontManager,FontProperties

OUT=Path(__file__).resolve().parent
result=json.loads((OUT/'demo-result.json').read_text(encoding='utf-8'))
font_path=Path('/mnt/c/Windows/Fonts/msyh.ttc')
if font_path.exists():
    fontManager.addfont(str(font_path))
    plt.rcParams['font.family']=FontProperties(fname=str(font_path)).get_name()
plt.rcParams['axes.unicode_minus']=False
figures=OUT/'figures';figures.mkdir(exist_ok=True)
for chart in result['charts']:
    data=chart['data'];fig,ax=plt.subplots(figsize=(10,5.5),layout='constrained')
    if chart['id']=='corpus_methods':
        labels=list(data)[::-1];values=[data[x] for x in labels]
        bars=ax.barh(labels,values,color='#375de8');ax.bar_label(bars,padding=4)
        ax.set_xlim(0,max(values)*1.13);ax.set_xlabel('文献数（关键词可重叠）')
    else:
        bars=ax.bar(list(data),list(data.values()),color='#375de8');ax.bar_label(bars,padding=4)
        ax.set_ylim(0,max(data.values())*1.2);ax.set_ylabel('篇')
    ax.set_title(chart['title'],fontsize=16,pad=18)
    ax.spines[['top','right']].set_visible(False)
    fig.text(.99,.01,chart['description'],ha='right',fontsize=9,color='#526174')
    fig.savefig(figures/(chart['id']+'.png'),dpi=180)
    plt.close(fig)
report=result['final_report']
for chart in result['charts']:
    report=report.replace(']('+chart['id']+')','](figures/'+chart['id']+'.png)')
for ref in result['references']:
    if ref.get('title')=='BIT-2103.00208.pdf' and ref.get('url','').startswith('/knowledge-bases/'):
        assert (OUT/'fixtures/BIT-2103.00208.pdf').is_file()
        report=report.replace(']('+ref['url']+')','](fixtures/BIT-2103.00208.pdf)')
(OUT/'demo-report.md').write_text(report,encoding='utf-8')
(OUT/'demo-knowledge-graph.json').write_text(json.dumps(result['knowledge_graph'],ensure_ascii=False,indent=2),encoding='utf-8')
print('Exported portable report, two real corpus figures and the complete graph.')
