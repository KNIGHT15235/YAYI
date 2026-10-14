"""Redis leases and a rolling research-start limit shared by backend workers."""
import asyncio
import json
import uuid
import os
import redis

from fastapi import HTTPException


ACQUIRE = """
-- ACQUIRE
local now = redis.call('TIME')
local ms = now[1] * 1000 + math.floor(now[2] / 1000)
if redis.call('EXISTS', KEYS[2]) == 1 then return 2 end
if redis.call('EXISTS', KEYS[1]) == 1 then return 1 end
if ARGV[3] == '1' then
  redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', ms - 60000)
  if redis.call('ZCARD', KEYS[3]) >= 10 then return 3 end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
if ARGV[3] == '1' then
  redis.call('ZADD', KEYS[3], ms, ARGV[1])
  redis.call('EXPIRE', KEYS[3], 60)
end
return 0
"""
RENEW = """
-- RENEW
if redis.call('GET', KEYS[1]) ~= ARGV[1] or redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[2])
return 1
"""
RELEASE = """
-- RELEASE
for i = 1, 2 do
  if redis.call('GET', KEYS[i]) == ARGV[1] then redis.call('DEL', KEYS[i]) end
end
return 1
"""


class ResearchLease:
    ttl = 120

    def __init__(self, user_id, session_id, client=None):
        self.client = client if client is not None else redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True,
            db=int(os.getenv("REDIS_DB", "0")),
            socket_connect_timeout=.3, socket_timeout=.3)
        self.keys = [f"research:active:user:{user_id}", f"research:active:session:{session_id}",
                     f"research:starts:{user_id}"]
        self.token = uuid.uuid4().hex
        self.session_id = session_id

    async def acquire(self, count_start=True):
        try:
            result = await asyncio.to_thread(self.client.eval, ACQUIRE, 3, *self.keys, self.token, self.ttl, int(count_start))
        except Exception as error:
            raise HTTPException(503, "研究调度暂不可用，请稍后重试") from error
        if result == 2:
            raise HTTPException(409, "该研究会话正在运行，请等待或取消后再恢复")
        if result == 1:
            raise HTTPException(429, "当前已有研究运行，每个用户同时只能运行一项研究", headers={"Retry-After": "30"})
        if result == 3:
            raise HTTPException(429, "每分钟最多启动或恢复 10 次研究", headers={"Retry-After": "60"})
        return self

    async def release(self):
        try:
            await asyncio.to_thread(self.client.eval, RELEASE, 2, *self.keys[:2], self.token)
        except Exception:
            pass  # A bounded TTL also releases leases after worker/network failure.

    async def _renew(self):
        while True:
            await asyncio.sleep(30)
            result = await asyncio.to_thread(self.client.eval, RENEW, 2, *self.keys[:2], self.token, self.ttl)
            if result != 1:
                raise RuntimeError("研究运行许可已失效，请从检查点恢复")

    async def stream(self, source):
        renewal = asyncio.create_task(self._renew())
        pending = None
        try:
            while True:
                pending = asyncio.create_task(source.__anext__())
                done, _ = await asyncio.wait({pending, renewal}, return_when=asyncio.FIRST_COMPLETED)
                if renewal in done:
                    renewal.result()
                try:
                    yield pending.result()
                except StopAsyncIteration:
                    break
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            yield "data: " + json.dumps({"type": "error", "content": "研究执行或运行许可中断，请从检查点恢复",
                                         "run_id": self.session_id, "session_id": self.session_id}, ensure_ascii=False) + "\n\n"
        finally:
            tasks = [renewal] + ([pending] if pending else [])
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await source.aclose()
            finally:
                await self.release()
