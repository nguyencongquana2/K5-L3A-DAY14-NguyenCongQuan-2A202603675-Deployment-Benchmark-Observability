"""
Rate limiting (tiêu chí 7) — Sliding window lưu trong Redis.
"""
import logging
import time
import uuid
from fastapi import HTTPException
from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Kiểm tra rate limit theo sliding window 60s trong Redis; vượt → HTTP 429."""
    if r is None:
        return

    redis_key = f"ratelimit:{key}"
    now = time.time()
    window_start = now - WINDOW_SECONDS
    limit = settings.rate_limit_per_minute

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = (
                max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
                if oldest
                else WINDOW_SECONDS
            )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now}:{uuid.uuid4().hex[:8]}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Redis rate limit check failed: {exc}")
