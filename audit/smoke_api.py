"""Live API audit. Uses a disposable account and removes only its own records.

Run with yayi_b Python from backend; --external additionally calls configured APIs.
No tokens, credentials, or user data are written to the result file.
"""
import argparse
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend' / 'app'))
load_dotenv(ROOT / 'backend' / '.env')
parser = argparse.ArgumentParser()
parser.add_argument('--external', action='store_true')
parser.add_argument('--output', default='smoke_core.json')
args = parser.parse_args()
results = []
username = 'audit_' + uuid.uuid4().hex[:12]
password = secrets.token_urlsafe(18)
session_id = kb_id = memory_id = attachment_id = None
client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=240)


def check(name, ok, **details):
    result = {'test': name, 'passed': bool(ok), **details}
    results.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return ok


def request(name, method, path, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    check(name, response.status_code == expected, status=response.status_code)
    return response


try:
    request('backend hello', 'GET', '/hello')
    schema = request('OpenAPI', 'GET', '/openapi.json').json()
    (ROOT / 'audit' / 'openapi_paths.json').write_text(json.dumps(
        {p: list(v) for p, v in schema['paths'].items()}, ensure_ascii=False, indent=2), encoding='utf-8')
    request('auth requires login', 'GET', '/auth/me', 401)
    response = request('register', 'POST', '/auth/register', 201, json={
        'username': username, 'email': username + '@example.com', 'password': password})
    response.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    request('login', 'POST', '/auth/login', json={'username': username, 'password': password})
    request('wrong password', 'POST', '/auth/login', 401, json={'username': username, 'password': 'incorrect'})
    request('current user', 'GET', '/auth/me')
    session_id = request('create session', 'POST', '/sessions', 201, json={'title': '临时核对会话'}).json()['id']
    request('list sessions', 'GET', '/sessions')
    request('rename session', 'PUT', f'/sessions/{session_id}', json={'title': '临时核对会话已改名'})
    for role, content in [('user', '我关注新能源汽车产业，喜欢用中文表格查看销量趋势。'),
                          ('assistant', '本次测试仅核对功能，不包含真实市场数据。')]:
        request('save ' + role + ' message', 'POST', f'/sessions/{session_id}/messages', 201,
                json={'role': role, 'content': content})
    detail = request('session history', 'GET', f'/sessions/{session_id}').json()
    check('session history round trip', detail.get('message_count') == 2)
    kb_id = request('create Chinese knowledge base', 'POST', '/knowledge-bases', 201,
                    json={'name': '核对测试_' + username, 'description': '自动测试临时知识库'}).json()['id']
    request('list knowledge bases', 'GET', '/knowledge-bases')
    request('knowledge detail', 'GET', f'/knowledge-bases/{kb_id}')
    request('list documents', 'GET', f'/knowledge-bases/{kb_id}/documents')
    tables = request('database tables', 'GET', '/database/tables').json()
    table_names = [t['name'] for t in tables] if isinstance(tables, list) else []
    for table in ('industry_stats', 'company_data', 'policy_data'):
        if table in table_names:
            request('table schema ' + table, 'GET', f'/database/tables/{table}/schema')
            request('table rows ' + table, 'GET', f'/database/tables/{table}/data?limit=1')
    request('read only SQL', 'POST', '/database/query', json={'sql': 'SELECT 1 AS audit_value', 'limit': 1})
    request('reject modifying SQL', 'POST', '/database/query', 400, json={'sql': 'DELETE FROM audit_table_never_exists'})
    for endpoint in ['/news/list', '/news/bidding/list', '/news/stats', '/news/check', '/news/industries', '/news/scheduler/status', '/memories']:
        request(endpoint, 'GET', endpoint)
    response = request('upload text attachment', 'POST', '/attachments', 201,
        data={'session_id': session_id}, files={'file': ('audit.txt', '附件核对暗号：银杏42。'.encode(), 'text/plain')})
    attachment_id = response.json()['id']
    for _ in range(20):
        attachment = client.get(f'/attachments/{attachment_id}').json()
        if attachment.get('status') in ('completed', 'failed'):
            break
        time.sleep(0.25)
    check('text attachment processed', attachment.get('status') == 'completed', state=attachment.get('status'))
    if args.external:
        response = request('Text2SQL real model', 'POST', '/database/text2sql', json={
            'question': '请统计 industry_stats 表总行数，只返回 COUNT(*)；不查询任何用户表。', 'intent': 'stats'})
        data = response.json()
        check('Text2SQL execution', data.get('success') is True, row_count=data.get('row_count'), error=data.get('error'))
        response = request('chat SSE real model', 'POST', '/chat/completion/v3', json={
            'session_id': session_id, 'question': '附件核对暗号是什么？只回答暗号。',
            'attachment_ids': [attachment_id], 'search_knowledge': False, 'search_web': False})
        chat_events = [json.loads(line[6:]) for line in response.text.splitlines()
                       if line.startswith('data: {')]
        chat_answer = ''.join(event.get('content', '') for event in chat_events if not event.get('thinking'))
        check('chat SSE contains answer', '银杏' in chat_answer and 'event: error' not in response.text,
              content_type=response.headers.get('content-type'), response_length=len(response.text))
        response = request('memory real compression', 'POST', '/memories/create', json={'session_id': session_id})
        if response.status_code == 200:
            memory_state = response.json()
            memory_id = memory_state['id']
            # Summaries commit before asynchronous indexing. A keyword fallback
            # hit is useful but must not be reported as a successful vector hit.
            deadline = time.monotonic() + 120
            while memory_state.get('indexing_status') == 'pending' and time.monotonic() < deadline:
                time.sleep(2)
                poll = client.get(f'/memories/{memory_id}')
                if poll.status_code != 200:
                    break
                memory_state = poll.json()
            check('memory vector index completed', memory_state.get('indexing_status') == 'completed',
                  indexing_status=memory_state.get('indexing_status'))
            response = request('memory hybrid recall', 'POST', '/memories/search', json={'query': '新能源汽车销量趋势', 'top_k': 3})
            recalled = response.json()
            check('memory hybrid recall returns saved memory', isinstance(recalled, list) and
                  any(item.get('id') == memory_id for item in recalled),
                  indexing_status=memory_state.get('indexing_status'))
        # Use a tiny synthetic PDF; never send user's documents to external parsing APIs.
        from PyPDF2 import PdfWriter
        import io
        writer = PdfWriter()
        from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject
        page = writer.add_blank_page(width=300, height=200)
        page = writer.pages[0]
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 100 Td (Audit synthetic fact: YAYI test revenue is 42 units.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        buf = io.BytesIO()
        writer.write(buf)
        response = request('knowledge PDF upload', 'POST', f'/knowledge-bases/{kb_id}/documents',
            files={'file': ('audit.pdf', buf.getvalue(), 'application/pdf')})
        if response.status_code == 200:
            doc_id = response.json()['id']
            for _ in range(90):
                docs = client.get(f'/knowledge-bases/{kb_id}/documents').json()
                doc = next((d for d in docs if d['id'] == doc_id), {})
                if doc.get('status') in ('completed', 'failed'):
                    break
                time.sleep(2)
            check('knowledge PDF parse and vectors', doc.get('status') == 'completed',
                  state=doc.get('status'), chunks=doc.get('chunk_count'), error=doc.get('error_message'))
            if doc.get('status') == 'completed':
                chunks = request('knowledge chunks', 'GET', f'/knowledge-bases/{kb_id}/documents/{doc_id}/chunks').json()
                check('knowledge chunks returned', bool(chunks.get('chunks')))
                from service.retrieval_service import retrieve_from_knowledge_base
                matches = retrieve_from_knowledge_base('核对测试_' + username, 'What is the YAYI test revenue?', top_k=3)
                check('knowledge real semantic retrieval', any('42' in hit.get('content_with_weight', '') for hit in matches), hits=len(matches))
                request('rename populated Chinese KB', 'PUT', f'/knowledge-bases/{kb_id}', json={'name': '核对改名_' + username})
                matches = retrieve_from_knowledge_base('核对改名_' + username, 'What is the YAYI test revenue?', top_k=3)
                check('semantic retrieval after rename', any('42' in hit.get('content_with_weight', '') for hit in matches), hits=len(matches))
            request('delete audit PDF', 'DELETE', f'/knowledge-bases/{kb_id}/documents/{doc_id}', 204)
    request('rename Chinese knowledge base', 'PUT', f'/knowledge-bases/{kb_id}', json={'name': '核对改名_' + username})
finally:
    for name, resource_id, path in [('memory', memory_id, '/memories'), ('attachment', attachment_id, '/attachments'), ('knowledge', kb_id, '/knowledge-bases'), ('session', session_id, '/sessions')]:
        if resource_id:
            try:
                request('cleanup ' + name, 'DELETE', path + '/' + resource_id, 204)
            except Exception as error:
                check('cleanup ' + name, False, error=type(error).__name__)
    # There is no account deletion endpoint. Delete only the uniquely generated test account.
    from core.database import SessionLocal
    from models import User
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user:
            db.delete(user)
            db.commit()
        check('cleanup disposable account', db.query(User).filter(User.username == username).first() is None)
    client.close()
    (ROOT / 'audit' / args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'RESULT {sum(r["passed"] for r in results)}/{len(results)}', flush=True)
