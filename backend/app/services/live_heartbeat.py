"""Nhịp sống của phiên nghe. Redis giữ TTL 30 giây. Không có Redis thì giữ trong tiến trình."""

import threading
import time

from app.core.config import get_settings
from app.services.gpu_lock import redis_client

_beats: dict[str, float] = {}
_guard = threading.Lock()


def _key(session_id: str) -> str:
    return f"live:{session_id}:heartbeat"


def touch(session_id: str) -> None:
    now = time.time()
    url = get_settings().redis_url
    if url:
        redis_client(url).set(_key(session_id), str(now), ex=30)
        return
    with _guard:
        _beats[session_id] = now


def age(session_id: str) -> float | None:
    url = get_settings().redis_url
    if url:
        raw = redis_client(url).get(_key(session_id))
        if raw is None:
            return None
        return time.time() - float(raw)
    with _guard:
        stamped = _beats.get(session_id)
    if stamped is None:
        return None
    return time.time() - stamped


def clear_heartbeats() -> None:
    with _guard:
        _beats.clear()
