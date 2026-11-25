"""
Kết nối Redis dùng chung cho rate limiter và cost guard.
"""
import redis
from app.config import settings

r = (
    redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    if settings.redis_url
    else None
)


def redis_healthy() -> bool:
    """Ping Redis; trả về False nếu chưa cấu hình hoặc lỗi kết nối."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False
