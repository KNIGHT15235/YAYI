"""Authenticated live checks for the public research demo tables and news module."""
import argparse
from collections import Counter
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from demo_access import client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'audit/database-news-live'


def save(name, value):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('inspect', 'collect', 'queries'))
    args = parser.parse_args()
    c, _ = client()
    if args.mode == 'inspect':
        tables = c.get('/database/tables')
        tables.raise_for_status()
        news = c.get('/news/check')
        news.raise_for_status()
        print(json.dumps({'tables': tables.json(), 'news': news.json()}, ensure_ascii=False), flush=True)
        save('before.json', {'tables': tables.json(), 'news': news.json()})
        return
    if args.mode == 'collect':
        response = c.post('/news/collect', params={'industry_id': 'remote_sensing',
                          'max_news': 30, 'max_bidding': 1}, timeout=240)
        response.raise_for_status()
        result = response.json()
        save('collection.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        assert result['success'], 'The real news collection did not succeed'
        listing = c.get('/news/list', params={'industry_id': 'remote_sensing', 'limit': 100})
        listing.raise_for_status()
        news = listing.json()
        save('news.json', news)
        assert news['total'] > 0
        assert news['stats']['total'] == news['total'] == result['available_count']
        assert len({item['source_url'] for item in news['data']}) == len(news['data'])
        publication_dates = [item['publish_time'] or '' for item in news['data']]
        assert publication_dates == sorted(publication_dates, reverse=True)
        assert not any(re.search(r'\b(?:procurement|tenders?)\b|招标|采购公告', item['title'], re.I)
                       for item in news['data'])
        hosts = {}
        for item in news['data']:
            host = urlparse(item['source_url']).hostname
            assert host and urlparse(item['source_url']).scheme in ('http', 'https')
            hosts[host] = hosts.get(host, 0) + 1
        first = c.get('/news/' + news['data'][0]['id'])
        first.raise_for_status()
        assert first.json()['data']['title'] == news['data'][0]['title']
        print(json.dumps({'news_total': news['total'], 'source_hosts': hosts}, ensure_ascii=False), flush=True)
        return
    catalog = c.get('/database/catalog')
    catalog.raise_for_status()
    tables = c.get('/database/tables')
    tables.raise_for_status()
    save('catalog.json', catalog.json())
    save('tables.json', tables.json())
    visible = {table['name']: table['row_count'] for table in tables.json()}
    assert visible.get('research_papers') == 120, visible
    assert visible.get('research_paper_methods', 0) > 0
    for table in ('research_papers', 'research_paper_methods'):
        response = c.get(f'/database/tables/{table}/data', params={'limit': 20})
        response.raise_for_status()
        save(table + '-preview.json', response.json())
        assert response.json()['rows']
    for path in ('/database/tables/users/data', '/database/tables/users/schema'):
        assert c.get(path).status_code in (400, 403, 404), path
    assert c.post('/database/query', json={'sql': 'SELECT id FROM users', 'limit': 1}).status_code in (400, 403)
    questions = [
        ('按年份统计文献数量，并绘制柱状图。', 'trend'),
        ('比较不同方法标签的文献数量。', 'comparison'),
        ('列出2025年以来的文献标题、年份和DOI。', 'detail'),
    ]
    checks = []
    papers = json.loads((ROOT / 'audit/demo-result.json').read_text(encoding='utf-8'))['papers']
    expected_years = Counter(int(p['year']) for p in papers)
    for index, (question, intent) in enumerate(questions, 1):
        response = c.post('/database/text2sql', json={'question': question, 'intent': intent}, timeout=180)
        response.raise_for_status()
        data = response.json()
        save(f'query-{index}.json', {'question': question, 'result': data})
        print(json.dumps({'question': question, 'success': data.get('success'),
                          'rows': data.get('row_count'), 'sql': data.get('sql'),
                          'error': data.get('error')}, ensure_ascii=False), flush=True)
        assert data['success'] and data['data'], data.get('error')
        if index == 1:
            actual = {}
            for row in data['data']:
                values = list(row.values())
                assert len(values) == 2, 'Year-count demo should return two fields'
                year = next(int(v) for v in values if str(v).isdigit() and 2020 <= int(v) <= 2026)
                count = next(int(v) for v in values if int(v) != year)
                actual[year] = count
            assert actual == dict(expected_years), (actual, dict(expected_years))
        elif index == 2:
            truth = c.post('/database/query', json={'sql': 'SELECT method_name, COUNT(*) AS paper_count FROM research_paper_methods GROUP BY method_name', 'limit': 100})
            truth.raise_for_status()
            expected = {(row['method_name'], row['paper_count']) for row in truth.json()['rows']}
            names = {name for name, _ in expected}
            actual = set()
            for row in data['data']:
                name = next(value for value in row.values() if isinstance(value, str) and value in names)
                count = next(int(value) for value in row.values() if value != name)
                actual.add((name, count))
            assert actual == expected
        else:
            expected_titles = {p['title'] for p in papers if int(p['year']) >= 2025}
            actual_titles = {v for row in data['data'] for v in row.values() if isinstance(v, str) and v in expected_titles}
            assert actual_titles == expected_titles
        checks.append({'question': question, 'row_count': data['row_count'],
                       'visualization_hint': data.get('visualization_hint')})
    save('summary.json', {'tables': visible, 'queries': checks, 'private_tables_blocked': True})


if __name__ == '__main__':
    main()
