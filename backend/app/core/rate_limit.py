"""Giới hạn tần suất trong tiến trình. Một IP không gửi được hàng nghìn request liên tiếp."""

import threading
import time

from fastapi import Request

from app.core.exceptions import ApiError

_MESSAGE = "Thao tác quá nhanh. Vui lòng thử lại sau."


class SlidingWindow:
    def __init__(self, limit: int, period: float = 60.0) -> None:
        self.limit = limit
        self.period = period
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

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._guard:
            self._prune(now)
            recent = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.period]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                raise ApiError(429, "rate_limited", _MESSAGE)
            recent.append(now)
            self._hits[key] = recent


login_attempts = SlidingWindow(60)
register_attempts = SlidingWindow(60)
upload_attempts = SlidingWindow(60)


def client_key(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host
