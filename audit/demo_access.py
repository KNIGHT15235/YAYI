"""Create/reuse the local demonstration account; never print its auth token."""
import json,secrets
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
ACCESS=ROOT/'backend/storage/demo-access.json'
BASE='http://127.0.0.1:8029'

def client():
    ACCESS.parent.mkdir(parents=True,exist_ok=True)
    if ACCESS.exists():
        account=json.loads(ACCESS.read_text(encoding='utf-8'))
    else:
        account={'username':'yayi_demo','password':'Yayi0929-'+secrets.token_urlsafe(9),'email':'yayi-demo@example.com'}
        ACCESS.write_text(json.dumps(account,ensure_ascii=False,indent=2),encoding='utf-8')
    c=httpx.Client(base_url=BASE,timeout=60)
    r=c.post('/auth/login',json={'username':account['username'],'password':account['password']})
    if r.status_code in (400,401,404):r=c.post('/auth/register',json=account)
    r.raise_for_status()
    c.headers['Authorization']='Bearer '+r.json()['access_token']
    return c,account

if __name__=='__main__':
    c,account=client()
    print(json.dumps({'username':account['username'],'user_id':c.get('/auth/me').json()['id'],'credentials_file':str(ACCESS)},ensure_ascii=False))
