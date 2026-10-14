"""Prepare the copied app's isolated local state without exposing credentials."""
import os
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / 'backend' / '.env'

def configure():
    overrides = {
        'POSTGRES_DB': 'yayi_0929', 'REDIS_DB': '9',
        'MILVUS_DB_NAME': 'yayi_0929', 'APP_PORT': '8029',
        'CORS_ALLOW_ORIGINS': 'http://localhost:5199,http://127.0.0.1:5199',
        'NEWS_COLLECTION_ENABLED': 'false',
        'LITERATURE_MIN_PAPERS': '60',
    }
    lines = ENV.read_text(encoding='utf-8').splitlines()
    seen = set()
    result = []
    for line in lines:
        key = line.split('=', 1)[0].strip()
        if key in overrides:
            if key not in seen:
                result.append(f'{key}={overrides[key]}')
                seen.add(key)
        else:
            result.append(line)
    result.extend(f'{k}={v}' for k,v in overrides.items() if k not in seen)
    ENV.write_text('\n'.join(result)+'\n', encoding='utf-8')
    return dotenv_values(ENV)

if __name__ == '__main__':
    settings = configure()
    import psycopg2
    conn = psycopg2.connect(host=settings.get('POSTGRES_HOST','localhost'),
        port=settings.get('POSTGRES_PORT','15432'), user=settings.get('POSTGRES_USER','postgres'),
        password=settings.get('POSTGRES_PASSWORD'), dbname='postgres')
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_database WHERE datname=%s', ('yayi_0929',))
        if not cursor.fetchone():
            cursor.execute('CREATE DATABASE yayi_0929')
    conn.close()
    from pymilvus import connections, db
    connections.connect(alias='yayi_bootstrap', host=settings.get('MILVUS_HOST','localhost'),
        port=settings.get('MILVUS_PORT','29530'))
    if 'yayi_0929' not in db.list_database(using='yayi_bootstrap'):
        db.create_database('yayi_0929', using='yayi_bootstrap')
    connections.disconnect('yayi_bootstrap')
    print('Configured isolated PostgreSQL=yayi_0929 Redis=9 Milvus=yayi_0929 API=8029 UI=5199')
