"""Một người ghi PCM, kênh nháp xuống client, và cờ dừng phiên.

Không có Redis thì mọi thứ nằm trong tiến trình. Có Redis thì lượt ghi, cờ dừng,
bản nháp đang mở, và kênh `live:{session_id}:out` dùng chung giữa các tiến trình.
"""

import json
import logging
import queue
import threading
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.gpu_lock import redis_client

log = logging.getLogger(__name__)

_guard = threading.Lock()
_generation: dict[str, int] = {}
_closed: set[str] = set()
_local_feeds: dict[str, list[queue.Queue]] = {}
_drafts: dict[str, tuple[float, str]] = {}
_pcm_locks: dict[str, threading.Lock] = {}


def reset_live_channel() -> None:
    with _guard:
        _generation.clear()
        _closed.clear()
        _local_feeds.clear()
        _drafts.clear()
        _pcm_locks.clear()


def pcm_lock(session_id: str) -> threading.Lock:
    with _guard:
        lock = _pcm_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _pcm_locks[session_id] = lock
        return lock


def unlink_pcm(path: str | None) -> None:
    if not path:
        return
    file = Path(path)
    try:
        if file.is_file():
            file.unlink()
    except OSError:
        return


def _redis():
    url = get_settings().redis_url
    if not url:
        return None
    return redis_client(url)


def _out_channel(session_id: str) -> str:
    return f"live:{session_id}:out"


def capture_closed(session_id: str) -> bool:
    with _guard:
        if session_id in _closed:
            return True
    client = _redis()
    if client is None:
        return False
    try:
        return client.get(f"live:{session_id}:closed") is not None
    except Exception:
        log.warning("Không đọc được cờ dừng của phiên %s", session_id)
        return False


def close_session(session_id: str) -> None:
    """Chặn mọi socket đang ghi và báo vòng lặp WebSocket thoát."""
    with _guard:
        _closed.add(session_id)
        _generation[session_id] = _generation.get(session_id, 0) + 1
    client = _redis()
    if client is not None:
        try:
            client.set(f"live:{session_id}:closed", "1", ex=120)
            client.incr(f"live:{session_id}:writer")
        except Exception:
            log.warning("Không ghi được cờ dừng của phiên %s", session_id)
    publish_live(session_id, {"type": "session_closed"})


def claim_writer(session_id: str) -> int | None:
    """Lấy lượt ghi. Socket đang giữ lượt cũ nhận `writer_replaced` và phải dừng."""
    if capture_closed(session_id):
        return None
    client = _redis()
    if client is not None:
        try:
            token = int(client.incr(f"live:{session_id}:writer"))
        except Exception:
            log.warning("Không lấy được lượt ghi PCM %s", session_id)
            return None
        if capture_closed(session_id):
            return None
        publish_live(session_id, {"type": "writer_replaced"})
        return token
    with _guard:
        if session_id in _closed:
            return None
        token = _generation.get(session_id, 0) + 1
        _generation[session_id] = token
    publish_live(session_id, {"type": "writer_replaced"})
    return token


def writer_current(session_id: str, token: int) -> bool:
    if capture_closed(session_id):
        return False
    client = _redis()
    if client is not None:
        try:
            raw = client.get(f"live:{session_id}:writer")
        except Exception:
            log.warning("Không đọc được lượt ghi PCM %s", session_id)
            return False
        if raw is None:
            return False
        return int(raw) == token
    with _guard:
        return _generation.get(session_id) == token


def publish_live(session_id: str, payload: dict) -> None:
    client = _redis()
    if client is not None:
        try:
            client.publish(_out_channel(session_id), json.dumps(payload, ensure_ascii=False))
        except Exception:
            log.warning("Không phát được kênh nháp của phiên %s", session_id)
        return
    with _guard:
        feeds = list(_local_feeds.get(session_id, []))
    for feed in feeds:
        feed.put(payload)


def put_open_draft(session_id: str, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    client = _redis()
    if client is not None:
        try:
            client.set(f"live:{session_id}:open_draft", raw, ex=60)
        except Exception:
            log.warning("Không ghi được câu nháp đang mở %s", session_id)
        return
    with _guard:
        _drafts[session_id] = (time.monotonic() + 60, raw)


def read_open_draft(session_id: str) -> dict | None:
    client = _redis()
    raw: str | None = None
    if client is not None:
        try:
            stored = client.get(f"live:{session_id}:open_draft")
        except Exception:
            log.warning("Không đọc được câu nháp đang mở %s", session_id)
            return None
        if stored is None:
            return None
        raw = stored.decode() if isinstance(stored, bytes) else str(stored)
    else:
        with _guard:
            item = _drafts.get(session_id)
            if item is None:
                return None
            expires, text = item
            if time.monotonic() > expires:
                _drafts.pop(session_id, None)
                return None
            raw = text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


class LiveFeed:
    """Hàng bản nháp của một socket. Publish từ thread khác chỉ cần queue.Queue."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_id = ""
        self._box: queue.Queue | None = None

    def start(self, session_id: str) -> None:
        self._session_id = session_id
        box: queue.Queue = queue.Queue()
        self._box = box
        client = _redis()
        if client is None:
            with _guard:
                _local_feeds.setdefault(session_id, []).append(box)
            return
        self._thread = threading.Thread(
            target=self._listen_redis,
            args=(session_id, client, box),
            name=f"live-out-{session_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def drain(self) -> list[dict]:
        if self._box is None:
            return []
        found: list[dict] = []
        while True:
            try:
                payload = self._box.get_nowait()
            except queue.Empty:
                return found
            if isinstance(payload, dict):
                found.append(payload)

    def _listen_redis(self, session_id: str, client, box: queue.Queue) -> None:
        pubsub = client.pubsub()
        try:
            pubsub.subscribe(_out_channel(session_id))
            while not self._stop.is_set():
                message = pubsub.get_message(timeout=0.2)
                if not message or message.get("type") != "message":
                    continue
                data = message.get("data")
                text = data.decode() if isinstance(data, bytes) else str(data)
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    box.put(payload)
        except Exception:
            log.warning("Kênh nháp của phiên %s bị đứt", session_id)
        finally:
            try:
                pubsub.close()
            except Exception:
                return

    def close(self) -> None:
        self._stop.set()
        if self._box is None:
            return
        with _guard:
            group = _local_feeds.get(self._session_id, [])
            if self._box in group:
                group.remove(self._box)
            if not group:
                _local_feeds.pop(self._session_id, None)
