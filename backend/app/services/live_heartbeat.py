"""Nhịp sống của phiên nghe. Redis giữ TTL 30 giây. Không có Redis thì giữ trong tiến trình."""

import threading
import time

from app.core.config import get_settings
from app.services.gpu_lock import redis_client

_beats: dict[str, float] = {}
_workers: dict[str, float] = {}
_guard = threading.Lock()
TTL_S = 30


def _key(session_id: str) -> str:
    return f"live:{session_id}:heartbeat"


def _worker_key(session_id: str) -> str:
    return f"live:{session_id}:worker"


def touch(session_id: str) -> None:
    now = time.time()
    url = get_settings().redis_url
    if url:
        redis_client(url).set(_key(session_id), str(now), ex=TTL_S)
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


def mark_worker(session_id: str) -> None:
    """Worker của phiên còn chạy. FastAPI thấy dấu này thì để worker quyết định nhả khóa."""
    url = get_settings().redis_url
    if url:
        redis_client(url).set(_worker_key(session_id), "1", ex=TTL_S)
        return
    with _guard:
        _workers[session_id] = time.time() + TTL_S


def clear_worker(session_id: str) -> None:
    url = get_settings().redis_url
    if url:
        redis_client(url).delete(_worker_key(session_id))
        return
    with _guard:
        _workers.pop(session_id, None)


def worker_alive(session_id: str) -> bool:
    url = get_settings().redis_url
    if url:
        return redis_client(url).get(_worker_key(session_id)) is not None
    with _guard:
        deadline = _workers.get(session_id)
    return deadline is not None and deadline > time.time()


def clear_heartbeats() -> None:
    with _guard:
        _beats.clear()
        _workers.clear()
