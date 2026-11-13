import asyncio
import time
from collections import defaultdict
from threading import Lock

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.exceptions import RateLimitExceededError
from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Sliding/fixed window rate limiter backed by Redis with safe in-memory fallback."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._redis_loop: asyncio.AbstractEventLoop | None = None
        self._local_buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    async def _get_redis(self) -> aioredis.Redis | None:
        if settings.APP_ENV == "test":
            return None
        loop = asyncio.get_running_loop()
        if self._redis is not None and self._redis_loop is loop:
            return self._redis
        try:
            client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await client.ping()
            self._redis = client
            self._redis_loop = loop
        except Exception:
            logger.warning("Redis unavailable for rate limiting; using in-process fallback")
            return None
        return self._redis

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        client = await self._get_redis()
        if client is not None:
            try:
                redis_key = f"rl:{key}:{int(time.time() // window_seconds)}"
                count = await client.incr(redis_key)
                if count == 1:
                    await client.expire(redis_key, window_seconds)
                if count > limit:
                    raise RateLimitExceededError(
                        f"Rate limit of {limit} requests per {window_seconds}s exceeded.",
                        retry_after=window_seconds,
                    )
                return
            except RateLimitExceededError:
                raise
            except Exception:
                logger.warning("Redis rate-limit check failed; falling back to local memory")

        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = [t for t in self._local_buckets[key] if t > cutoff]
            if len(timestamps) >= limit:
                raise RateLimitExceededError(
                    f"Rate limit of {limit} requests per {window_seconds}s exceeded.",
                    retry_after=window_seconds,
                )
            timestamps.append(now)
            self._local_buckets[key] = timestamps

    async def record_failed_login(self, identifier: str) -> int:
        key = f"login_fail:{identifier.lower()}"
        window = settings.LOGIN_LOCKOUT_MINUTES * 60
        client = await self._get_redis()
        if client is not None:
            try:
                count = await client.incr(key)
                if count == 1:
                    await client.expire(key, window)
                return int(count)
            except Exception:
                pass
        now = time.time()
        cutoff = now - window
        with self._lock:
            attempts = [t for t in self._local_buckets[key] if t > cutoff]
            attempts.append(now)
            self._local_buckets[key] = attempts
            return len(attempts)

    async def is_login_locked(self, identifier: str) -> bool:
        key = f"login_fail:{identifier.lower()}"
        client = await self._get_redis()
        if client is not None:
            try:
                val = await client.get(key)
                return bool(val and int(val) >= settings.LOGIN_MAX_ATTEMPTS)
            except Exception:
                pass
        now = time.time()
        cutoff = now - (settings.LOGIN_LOCKOUT_MINUTES * 60)
        with self._lock:
            attempts = [t for t in self._local_buckets[key] if t > cutoff]
            self._local_buckets[key] = attempts
            return len(attempts) >= settings.LOGIN_MAX_ATTEMPTS

    async def reset_failed_login(self, identifier: str) -> None:
        key = f"login_fail:{identifier.lower()}"
        client = await self._get_redis()
        if client is not None:
            try:
                await client.delete(key)
            except Exception:
                pass
        with self._lock:
            self._local_buckets.pop(key, None)


rate_limiter = RateLimiter()
