"""Đánh thức SSE sau khi một dòng job_events đã commit.

Worker publish `{job_id, seq}` lên Redis `job:{job_id}:events`. Không có Redis thì
đánh thức waiter trong cùng tiến trình. Seq bị hổng thì SSE đọc bù từ Postgres.
"""

import json
import logging
import threading

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.gpu_lock import redis_client

log = logging.getLogger(__name__)

_guard = threading.Lock()
_waiters: dict[str, list[threading.Event]] = {}
_installed = False


def reset_job_watches() -> None:
    with _guard:
        _waiters.clear()


def remember_job_event(db: Session, job_id: str, seq: int) -> None:
    pending = db.info.setdefault("stt_job_events", [])
    pending.append((job_id, seq))


def watch_job(job_id: str) -> threading.Event:
    wake = threading.Event()
    with _guard:
        _waiters.setdefault(job_id, []).append(wake)
    return wake


def unwatch_job(job_id: str, wake: threading.Event) -> None:
    with _guard:
        group = _waiters.get(job_id, [])
        if wake in group:
            group.remove(wake)
        if not group:
            _waiters.pop(job_id, None)


def publish_job_event(job_id: str, seq: int) -> None:
    with _guard:
        for wake in _waiters.get(job_id, []):
            wake.set()
    url = get_settings().redis_url
    if not url:
        return
    try:
        redis_client(url).publish(
            f"job:{job_id}:events",
            json.dumps({"job_id": job_id, "seq": seq}, separators=(",", ":")),
        )
    except Exception:
        log.warning("Không phát được sự kiện của job %s", job_id)


def install_job_notify() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, "after_commit")
    def _after_commit(session: Session) -> None:
        pending = session.info.pop("stt_job_events", None)
        if not pending:
            return
        for job_id, seq in pending:
            publish_job_event(str(job_id), int(seq))

    @event.listens_for(Session, "after_rollback")
    def _after_rollback(session: Session) -> None:
        session.info.pop("stt_job_events", None)
