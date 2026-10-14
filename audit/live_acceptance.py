"""Scoped live acceptance helpers. Never print credentials or mutate existing data.

Run from the existing WSL environment. Provider calls are opt-in subcommands.
Runtime manifests and credentials live under git-ignored backend/storage.
"""
from pathlib import Path
import argparse
import json
import os
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "backend" / "storage" / "live-acceptance-20261014"
sys.path.insert(0, str(ROOT / "backend" / "app"))


def settings():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / "backend" / ".env")
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)
    return values


def safe_error(error, values):
    message = str(error)
    for key, value in values.items():
        if value and len(value) >= 4 and any(s in key.upper() for s in ("KEY", "SECRET", "PASSWORD", "TOKEN")):
            message = message.replace(value, "[REDACTED]")
    return {"type": type(error).__name__, "message": message[:700]}


def preflight():
    values = settings()
    result = {"runtime": sys.version.split()[0], "external_calls": False}
    result["configured"] = {key: bool(os.getenv(key)) for key in (
        "DASHSCOPE_API_KEY", "BOCHA_API_KEY", "DOCMIND_ACCESS_KEY_ID", "DOCMIND_ACCESS_KEY_SECRET")}
    result["targets"] = {key: os.getenv(key) for key in (
        "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "REDIS_HOST", "REDIS_PORT", "REDIS_DB",
        "MILVUS_HOST", "MILVUS_PORT", "MILVUS_DB_NAME", "APP_PORT", "NEWS_COLLECTION_ENABLED")}
    result["model_host"] = urlsplit(os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")).hostname
    try:
        from core.database import engine
        from sqlalchemy import text
        with engine.connect() as connection:
            result["postgres"] = bool(connection.execute(text("SELECT 1")).scalar())
    except Exception as exc:
        result["postgres"] = safe_error(exc, values)
    try:
        import redis
        client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")), password=os.getenv("REDIS_PASSWORD") or None,
            socket_connect_timeout=5, socket_timeout=5)
        result["redis"] = client.ping()
        # Read only: confirm a planned development restart will not interrupt
        # another active study; never print lease keys or owner identities.
        result["active_research_leases"] = sum(1 for _ in client.scan_iter(match="research:active:*", count=100))
        client.close()
    except Exception as exc:
        result["redis"] = safe_error(exc, values)
    try:
        from pymilvus import connections, utility
        connections.connect(alias="live_acceptance_readonly", host=os.getenv("MILVUS_HOST", "localhost"),
            port=os.getenv("MILVUS_PORT", "19530"), db_name=os.getenv("MILVUS_DB_NAME", "default"), timeout=15)
        result["milvus"] = {"version": utility.get_server_version(using="live_acceptance_readonly"),
                            "collections": len(utility.list_collections(using="live_acceptance_readonly"))}
        connections.disconnect("live_acceptance_readonly")
    except Exception as exc:
        result["milvus"] = safe_error(exc, values)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["preflight"])
    args = parser.parse_args()
    preflight()
