"""Small random-key diagnostic; does not inspect or modify real research keys."""
import asyncio
import json
from pathlib import Path
import sys
import time
import uuid

from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / "backend" / ".env")
sys.path.insert(0, str(PROJECT / "backend" / "app"))
from fastapi import HTTPException
from service.research_guard import ResearchLease


async def main():
    identifier = "audit-lease-diagnostic-" + uuid.uuid4().hex
    lease = ResearchLease(identifier + "-user", identifier + "-session")
    started = time.monotonic()
    result = {}
    try:
        try:
            await lease.acquire()
            result["acquire"] = "success"
        except HTTPException as exc:
            result.update(acquire="rejected", http_status=exc.status_code)
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["own_user_lock_after_call"] = lease.client.get(lease.keys[0]) == lease.token
        result["own_session_lock_after_call"] = lease.client.get(lease.keys[1]) == lease.token
        result["recorded_starts"] = lease.client.zcard(lease.keys[2])
        print(json.dumps(result))
    finally:
        lease.client.delete(*lease.keys)


if __name__ == "__main__":
    asyncio.run(main())
