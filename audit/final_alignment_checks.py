"""Final read-only runtime/document integrity checks; no credentials printed."""
import hashlib
import json
import subprocess
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
results = []
def check(name, passed, **details):
    row = dict(test=name, passed=bool(passed), **details)
    results.append(row)
    print(json.dumps(row, ensure_ascii=False))

with httpx.Client(timeout=20) as client:
    for name, url in [('backend', 'http://127.0.0.1:8000/hello'), ('frontend', 'http://127.0.0.1:5183/login')]:
        response = client.get(url)
        check(name+' reachable', response.status_code == 200)
    for origin, expected in [('http://localhost:5183', 200), ('http://127.0.0.1:5183', 200), ('https://untrusted.example', 400)]:
        response = client.options('http://127.0.0.1:8000/auth/login', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type'})
        check('CORS '+origin, response.status_code == expected and
              (expected != 200 or response.headers.get('access-control-allow-origin') == origin), status=response.status_code)
original = Path('/mnt/c/Users/28436/Downloads/雅意.md')
preserved = root/'audit'/'雅意-原始文档.md'
check('Downloads original unchanged', original.read_bytes() == preserved.read_bytes(),
      sha256=hashlib.sha256(original.read_bytes()).hexdigest())
edits = json.loads((root/'audit'/'alignment_doc_changes.json').read_text(encoding='utf-8'))
check('document edits ordered and nonoverlapping', all(a['end'] < b['start'] for a,b in zip(edits, edits[1:])), changes=len(edits))
for name in ['雅意-代码对齐版.md','文档逐项修改清单.md','功能补齐实施报告.md','代码修改清单.md']:
    check('deliverable exists '+name, (root/'audit'/name).is_file())
containers = [json.loads(line) for line in subprocess.check_output(
    ['docker', 'compose', 'ps', '--format', 'json'], cwd=root, text=True).splitlines() if line.strip()]
services = {row['Service']: row.get('Health') for row in containers}
check('six project containers healthy', len(services) == 6 and all(value == 'healthy' for value in services.values()), services=services)
(root/'audit'/'alignment-final-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
assert all(row['passed'] for row in results)
