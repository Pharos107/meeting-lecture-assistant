"""Giới hạn tần suất theo cửa sổ trượt. Một IP không gửi được hàng nghìn request liên tiếp.

Có REDIS_URL thì đếm trong Redis, nên nhiều bản uvicorn dùng chung một trần. Không có Redis,
hoặc Redis lỗi, thì đếm trong tiến trình.
"""

import logging
import threading
import time
import uuid

from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import ApiError

logger = logging.getLogger(__name__)

_MESSAGE = "Thao tác quá nhanh. Vui lòng thử lại sau."

# Xóa mốc cũ, đếm, và chỉ ghi mốc mới khi còn chỗ, trong một lệnh để hai bản không cùng lọt.
_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - period)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, period)
return 1
"""


class SlidingWindow:
    def __init__(self, limit: int, period: float = 60.0, name: str = "default") -> None:
        self.limit = limit
        self.period = period
        self.name = name
        self._hits: dict[str, list[float]] = {}
        self._guard = threading.Lock()

    def _prune(self, now: float) -> None:
        expired = [
            name
            for name, stamps in self._hits.items()
            if not stamps or now - stamps[-1] >= self.period
        ]
        for name in expired:
            del self._hits[name]

    def _hit_memory(self, key: str) -> bool:
        now = time.monotonic()
        with self._guard:
            self._prune(now)
            recent = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.period]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True

    def _hit_redis(self, url: str, key: str) -> bool:
        from app.services.gpu_lock import redis_client

        period_ms = int(self.period * 1000)
        allowed = redis_client(url).eval(
            _SCRIPT,
            1,
            f"rate:{self.name}:{key}",
            str(int(time.time() * 1000)),
            str(period_ms),
            str(self.limit),
            uuid.uuid4().hex,
        )
        return bool(allowed)

    def hit(self, key: str) -> None:
        url = get_settings().redis_url
        allowed = None
        if url:
            try:
                allowed = self._hit_redis(url, key)
            except Exception:
                logger.warning("Không đếm được tần suất trong Redis, đếm trong tiến trình.", exc_info=True)
        if allowed is None:
            allowed = self._hit_memory(key)
        if not allowed:
            raise ApiError(429, "rate_limited", _MESSAGE)


login_attempts = SlidingWindow(60, name="login")
register_attempts = SlidingWindow(60, name="register")
upload_attempts = SlidingWindow(60, name="upload")
chat_attempts = SlidingWindow(60, name="chat")
# Cao hơn các cửa khác: đứng sau Caddy thì mọi người xem liên kết có thể chung một IP.
share_views = SlidingWindow(600, name="share")


def client_key(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host
