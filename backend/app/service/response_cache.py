"""Bounded Redis cache; outages never prevent the underlying API call."""
import hashlib
import json
import os

import redis


class RedisJSONCache:
    def __init__(self, namespace, ttl):
        self.namespace = namespace
        self.ttl = max(0, int(ttl))
        self.client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'), port=int(os.getenv('REDIS_PORT', '6379')),
            password=os.getenv('REDIS_PASSWORD') or None, decode_responses=True,
            socket_connect_timeout=.3, socket_timeout=.3,
        )

    def key(self, value):
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return f'yayi:cache:{self.namespace}:' + hashlib.sha256(serialized.encode()).hexdigest()

    def get(self, value):
        if not self.ttl:
            return None
        try:
            raw = self.client.get(self.key(value))
            return json.loads(raw) if raw is not None else None
        except (redis.RedisError, ValueError, TypeError):
            return None

    def set(self, value, result):
        if not self.ttl:
            return
        try:
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) <= 2 * 1024 * 1024:
                self.client.setex(self.key(value), self.ttl, encoded)
        except (redis.RedisError, ValueError, TypeError):
            pass
