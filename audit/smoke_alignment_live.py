"""Live verification of added features using synthetic files and disposable users."""
import io
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
results = []
accounts = []
resources = {}
clients = [httpx.Client(base_url='http://127.0.0.1:8000', timeout=180) for _ in range(2)]


def check(name, passed, **details):
    result = {'test': name, 'passed': bool(passed), **details}
    results.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return passed


def request(client, name, method, path, status=200, **kwargs):
    response = client.request(method, path, **kwargs)
    check(name, response.status_code == status, status=response.status_code)
    return response


try:
    for number, client in enumerate(clients):
        username = 'alignment_' + uuid.uuid4().hex[:12]
        password = secrets.token_urlsafe(18)
        accounts.append(username)
        response = request(client, f'register disposable user {number}', 'POST', '/auth/register', 201,
                           json={'username': username, 'password': password, 'email': username + '@example.com'})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    owner, other = clients
    for path in ('/research/checkpoint/unknown', '/attachments/00000000-0000-0000-0000-000000000000'):
        response = httpx.get('http://127.0.0.1:8000' + path)
        check('anonymous rejected ' + path.split('/')[1], response.status_code == 401)
    session = request(owner, 'create owned session', 'POST', '/sessions', 201, json={'title': '补齐功能临时核对'}).json()['id']
    resources['session'] = session
    request(other, 'other user cannot resume session', 'POST', f'/research/resume/{session}', 404)
    request(other, 'other user cannot start research in session', 'POST', '/research/stream', 404,
            json={'query': 'synthetic unauthorized request', 'session_id': session, 'search_modes': []})
    kb = request(owner, 'create KB', 'POST', '/knowledge-bases', 201,
                 json={'name': '补齐核对_' + uuid.uuid4().hex[:12]}).json()['id']
    resources['kb'] = kb
    payload = '本文件仅用于软件测试。合成项目的编号为紫藤73，测试收入为42个单位。'.encode()
    doc = request(owner, 'upload retained original', 'POST', f'/knowledge-bases/{kb}/documents',
                  files={'file': ('核对原文.txt', payload, 'text/plain')}).json()['id']
    for _ in range(90):
        docs = owner.get(f'/knowledge-bases/{kb}/documents').json()
        record = next(row for row in docs if row['id'] == doc)
        if record['status'] in ('completed', 'failed'):
            break
        time.sleep(1)
    check('new document parsed and indexed', record['status'] == 'completed', state=record['status'])
    check('original advertised as downloadable', record.get('download_available') is True)
    download_path = f'/knowledge-bases/{kb}/documents/{doc}/download'
    original = request(owner, 'download retained original', 'GET', download_path)
    check('download matches uploaded bytes', original.content == payload)
    request(other, 'other user cannot download original', 'GET', download_path, 404)
    request(other, 'other user cannot search KB', 'POST', f'/knowledge-bases/{kb}/search', 404,
            json={'query': '测试编号'})
    response = request(owner, 'real semantic search with rerank', 'POST', f'/knowledge-bases/{kb}/search',
                       json={'query': '合成项目编号与收入是多少？', 'top_k': 10, 'rerank': True})
    answer = response.json()
    check('semantic search finds original content', any('紫藤73' in hit['content'] for hit in answer.get('results', [])))
    check('real rerank produces scores', answer.get('reranked') is True,
          warning=answer.get('warning'), hits=len(answer.get('results', [])))
    check('search resolves PG document/download metadata',
          all(hit['document_id'] == doc and hit['download_available'] and hit['download_url'] == download_path
              for hit in answer.get('results', [])) and bool(answer.get('results')))
    request(owner, 'reject empty search text', 'POST', f'/knowledge-bases/{kb}/search', 422, json={'query': '   '})
    request(owner, 'rename KB with retained file', 'PUT', f'/knowledge-bases/{kb}',
            json={'name': '补齐改名_' + uuid.uuid4().hex[:12]})
    renamed = request(owner, 'search after rename', 'POST', f'/knowledge-bases/{kb}/search',
                      json={'query': '合成项目编号', 'rerank': False}).json()
    check('rename preserves search result', any('紫藤73' in hit['content'] for hit in renamed.get('results', [])))
    check('rename preserves original file', owner.get(download_path).content == payload)
    from core.database import SessionLocal
    from models.knowledge import Document
    from models.chat import ChatAttachment
    with SessionLocal() as db:
        stored_path = db.query(Document).filter(Document.id == doc).first().file_path
    request(owner, 'delete document', 'DELETE', f'/knowledge-bases/{kb}/documents/{doc}', 204)
    check('delete removes retained original', not Path(stored_path).exists())
    request(owner, 'deleted original unavailable', 'GET', download_path, 404)

    # Create a synthetic scanned image, never a user's file.
    from PIL import Image, ImageDraw, ImageFont
    picture = Image.new('RGB', (1000, 220), 'white')
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    font = ImageFont.truetype(str(font_path), 42) if font_path.exists() else ImageFont.load_default()
    ImageDraw.Draw(picture).text((40, 70), 'YAYI OCR AUDIT 7342', fill='black', font=font)
    buffer = io.BytesIO()
    picture.save(buffer, format='PNG')
    response = request(owner, 'upload OCR image', 'POST', '/attachments', 201,
                       data={'session_id': session}, files={'file': ('scan.png', buffer.getvalue(), 'image/png')})
    attachment = response.json()['id']
    resources['attachment'] = attachment
    for _ in range(170):
        state = owner.get('/attachments/' + attachment).json()
        if state['status'] in ('completed', 'failed'):
            break
        time.sleep(2)
    check('real DocMind image OCR completes', state['status'] == 'completed', state=state['status'], error=state.get('error_message'))
    with SessionLocal() as db:
        parsed = db.query(ChatAttachment).filter(ChatAttachment.id == attachment).first()
        check('OCR result contains synthetic number', '7342' in (parsed.content_text or ''))
    request(other, 'other user cannot read attachment', 'GET', '/attachments/' + attachment, 404)
    request(other, 'other user cannot delete attachment', 'DELETE', '/attachments/' + attachment, 404)
    request(other, 'other user cannot upload into session', 'POST', '/attachments', 404,
            data={'session_id': session}, files={'file': ('audit.txt', b'synthetic', 'text/plain')})
    response = request(owner, 'Text2SQL with live Schema', 'POST', '/database/text2sql',
                       json={'question': '统计industry_stats表的总行数，仅生成COUNT查询。', 'intent': 'stats'})
    value = response.json()
    check('Text2SQL actual execution succeeds', value.get('success') is True, row_count=value.get('row_count'))
    news = owner.get('/news/list?limit=1').json().get('data', [])
    if news:
        detail = request(owner, 'news detail endpoint', 'GET', '/news/' + news[0]['id']).json()
        check('news detail ID matches list', detail.get('data', {}).get('id') == news[0]['id'])
    request(owner, 'missing news returns 404', 'GET', '/news/' + str(uuid.uuid4()), 404)
finally:
    for key, prefix in (('attachment', '/attachments/'), ('kb', '/knowledge-bases/'), ('session', '/sessions/')):
        if resources.get(key):
            try:
                response = clients[0].delete(prefix + resources[key])
                check('cleanup own ' + key, response.status_code in (204, 404), status=response.status_code)
            except Exception as error:
                check('cleanup own ' + key, False, error=type(error).__name__)
    from core.database import SessionLocal
    from models import User
    with SessionLocal() as db:
        for username in accounts:
            user = db.query(User).filter(User.username == username).first()
            if user:
                db.delete(user)
        db.commit()
        check('cleanup own accounts', not db.query(User).filter(User.username.in_(accounts)).count())
    for client in clients:
        client.close()
    (ROOT / 'audit' / 'alignment-live-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'RESULT {sum(row["passed"] for row in results)}/{len(results)}', flush=True)
