"""Opt-in new-message queue; never scans historical conversations for model work."""
import logging
import os
import time
import uuid

import redis

from core.database import SessionLocal
from models.chat import ChatSession, ChatMessage, LongTermMemory

PREFIX = "memory:v1"
SUMMARY_JOBS = f"{PREFIX}:summary_jobs"
INDEX_JOBS = f"{PREFIX}:index_jobs"


def memory_cache():
    return redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")),
                       password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True,
                       socket_connect_timeout=3, socket_timeout=5)


def interval_minutes():
    return max(1, int(os.getenv("MEMORY_INTERVAL_MINUTES", "30")))


def enqueue_message(user_id, session_id, message_id, content, created_at):
    """Only called after a new, owned PG message commits; existing rows are not enrolled."""
    from service.memory_service import memory_enabled, memory_threshold, estimate_memory_tokens
    if not memory_enabled("MEMORY_AUTO_ENABLED"):
        return False
    user_id, session_id, message_id = (str(uuid.UUID(str(value))) for value in (user_id, session_id, message_id))
    cache = memory_cache()
    key = f"{PREFIX}:session:{session_id}"
    return bool(cache.eval("""
        redis.call('HSET', KEYS[1], 'user_id', ARGV[1], 'session_id', ARGV[2])
        local added = redis.call('ZADD', KEYS[2], ARGV[4], ARGV[3])
        local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens') or '0')
        if added == 1 then tokens = redis.call('HINCRBY', KEYS[1], 'tokens', ARGV[5]) end
        redis.call('ZADD', KEYS[3], 'NX', ARGV[6], ARGV[2])
        if tokens >= tonumber(ARGV[7]) then
            redis.call('ZADD', KEYS[3], ARGV[8], ARGV[2]); return 1
        end
        return 0
    """, 3, key, key + ":messages", SUMMARY_JOBS, user_id, session_id, message_id, created_at.timestamp(),
       estimate_memory_tokens(content), time.time() + interval_minutes() * 60, memory_threshold(), time.time()))


def discard_session(user_id, session_id):
    """Remove only this owner's pending summary work after PG session deletion."""
    cache = memory_cache()
    key = f"{PREFIX}:session:{session_id}"
    return bool(cache.eval("""
        local owner = redis.call('HGET', KEYS[1], 'user_id')
        if owner and owner ~= ARGV[1] then return 0 end
        redis.call('ZREM', KEYS[3], ARGV[2])
        redis.call('DEL', KEYS[1], KEYS[2])
        return 1
    """, 3, key, key + ":messages", SUMMARY_JOBS, str(user_id), str(session_id)))


def enqueue_index(memory_id, user_id):
    cache = memory_cache()
    cache.hset(f"{PREFIX}:index:{memory_id}", mapping={"user_id": str(user_id)})
    cache.zadd(INDEX_JOBS, {str(memory_id): time.time()}, nx=True)


def retry_job(cache, queue, identifier, meta_key):
    attempts = cache.hincrby(meta_key, "attempts", 1)
    maximum = max(1, int(os.getenv("MEMORY_MAX_RETRIES", "3")))
    if attempts >= maximum:
        cache.zrem(queue, identifier)
        cache.hset(meta_key, "status", "failed")
    else:
        cache.zadd(queue, {identifier: time.time() + min(1800, 60 * (2 ** (attempts - 1)))})
    return attempts


def process_session(session_id):
    from service.memory_service import get_memory_service, memory_enabled, estimate_memory_tokens
    if not memory_enabled("MEMORY_AUTO_ENABLED"):
        return {"status": "disabled"}
    cache = memory_cache()
    key = f"{PREFIX}:session:{session_id}"
    lock = cache.lock(f"{key}:lock", timeout=120, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        metadata = cache.hgetall(key)
        ids = cache.zrange(key + ":messages", 0, 199)
        if not metadata or not ids:
            cache.zrem(SUMMARY_JOBS, session_id)
            return {"status": "empty"}
        with SessionLocal() as db:
            owned = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == metadata["user_id"]).first()
            if not owned:
                cache.zrem(SUMMARY_JOBS, session_id)
                cache.delete(key, key + ":messages")
                return {"status": "removed"}
            messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id, ChatMessage.id.in_(ids)).order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()
            if messages:
                memory = get_memory_service().create_memory(db, metadata["user_id"], session_id, messages)
                if memory is None:
                    raise RuntimeError("No memory produced")
            saved = db.query(LongTermMemory).filter(LongTermMemory.user_id == metadata["user_id"], LongTermMemory.session_id == session_id).all()
            completed_ids = {mid for row in saved for mid in (row.key_insights or {}).get("_source_message_ids", [])}
            present_ids = {str(row.id) for row in messages}
            remove_ids = [mid for mid in ids if mid in completed_ids or mid not in present_ids]
            # Atomic cleanup cannot remove a job enqueued by a simultaneous new
            # chat message. Subtract only this batch, preserving new tokens.
            cache.eval("""
                for i=4,#ARGV do redis.call('ZREM', KEYS[2], ARGV[i]) end
                local tokens = math.max(0, tonumber(redis.call('HGET',KEYS[1],'tokens') or '0') - tonumber(ARGV[2]))
                redis.call('HSET',KEYS[1],'tokens',tokens,'attempts',0,'status','pending')
                if redis.call('ZCARD',KEYS[2]) == 0 then
                    redis.call('ZREM',KEYS[3],ARGV[1])
                else
                    redis.call('ZADD',KEYS[3],ARGV[3],ARGV[1])
                end
            """, 3, key, key + ":messages", SUMMARY_JOBS, session_id,
                sum(estimate_memory_tokens(row.content) for row in messages if str(row.id) in remove_ids),
                time.time() + interval_minutes() * 60, *remove_ids)
        return {"status": "completed"}
    except Exception as exc:
        retry_job(cache, SUMMARY_JOBS, session_id, key)
        logging.warning("Memory job failed (%s); retained for bounded retry", type(exc).__name__)
        return {"status": "retry"}
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


def process_index(memory_id):
    from service.memory_service import get_memory_service, memory_enabled
    cache = memory_cache()
    key = f"{PREFIX}:index:{memory_id}"
    lock = cache.lock(key + ":lock", timeout=300, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        owner = cache.hget(key, "user_id")
        with SessionLocal() as db:
            memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id, LongTermMemory.user_id == owner).first()
            if not memory:
                cache.zrem(INDEX_JOBS, memory_id)
                cache.delete(key)
                return {"status": "removed"}
            details = dict(memory.key_insights or {})
            if not memory_enabled("MEMORY_VECTOR_ENABLED"):
                details["_indexing_status"] = "disabled"
                ids = []
            else:
                ids = get_memory_service()._store_memory_vectors(memory_id, owner, str(memory.session_id or ""), details)
                expected = bool(details.get("summary")) + len([v for v in details.get("key_insights", []) if v]) + bool(details.get("topics"))
                if len(ids) < expected:
                    raise RuntimeError("Embedding or vector storage incomplete")
                details["_indexing_status"] = "completed"
            memory.milvus_ids = ids
            memory.key_insights = details
            db.commit()
            cache.zrem(INDEX_JOBS, memory_id)
            cache.delete(key)
        return {"status": "completed"}
    except Exception as exc:
        attempts = retry_job(cache, INDEX_JOBS, memory_id, key)
        with SessionLocal() as db:
            row = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
            if row:
                info = dict(row.key_insights or {})
                info["_indexing_status"] = "failed" if cache.hget(key, "status") == "failed" else "pending"
                info["_indexing_attempts"] = attempts
                row.key_insights = info
                db.commit()
        logging.warning("Memory index job failed: %s", type(exc).__name__)
        return {"status": "retry"}
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


def run_due_jobs():
    """Bounded work only on explicitly enrolled new-message and vector job IDs."""
    from service.memory_service import memory_enabled
    cache = memory_cache()
    limit = max(1, min(20, int(os.getenv("MEMORY_JOBS_PER_RUN", "5"))))
    if memory_enabled("MEMORY_AUTO_ENABLED"):
        for sid in cache.zrangebyscore(SUMMARY_JOBS, "-inf", time.time(), start=0, num=limit):
            process_session(sid)
    for memory_id in cache.zrangebyscore(INDEX_JOBS, "-inf", time.time(), start=0, num=limit):
        process_index(memory_id)
