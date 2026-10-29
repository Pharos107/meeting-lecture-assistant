"""SSE tiến độ của một job."""

import asyncio
import json
import logging
import os
import threading

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_auth import _bearer, current_user
from app.api.routes_jobs import owned_job
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.db import get_engine
from app.models import Job, JobEvent
from app.services.gpu_lock import redis_client
from app.services.job_notify import unwatch_job, watch_job

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"])


def parse_after(raw: str | None) -> int:
    if raw is None:
        return 0
    if not raw.isdigit():
        message = "after_seq phải là số nguyên không âm."
        raise ApiError(422, "validation", message, {"after_seq": message})
    return int(raw)


_TERMINAL = {"ready", "failed", "cancelled"}
_TERMINAL_EVENTS = {"done", "error"}


def read_snapshot(job_id, after: int) -> tuple[list[tuple[int, str, dict]], str | None]:
    """Một session cho cả sự kiện mới và trạng thái job."""
    with Session(get_engine()) as db:
        rows = db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq > after)
            .order_by(JobEvent.seq)
        ).all()
        found = []
        for row in rows:
            payload = dict(row.payload) if isinstance(row.payload, dict) else {"seq": row.seq}
            payload.setdefault("seq", row.seq)
            found.append((row.seq, row.event_type, payload))
        job = db.get(Job, job_id)
        status = None if job is None else job.status
        return found, status


def _listen_redis(job_id: str, loop: asyncio.AbstractEventLoop, inbox: asyncio.Queue, stop: threading.Event) -> None:
    client = redis_client(get_settings().redis_url)
    pubsub = client.pubsub()
    try:
        pubsub.subscribe(f"job:{job_id}:events")
        while not stop.is_set():
            message = pubsub.get_message(timeout=0.5)
            if message and message.get("type") == "message":
                loop.call_soon_threadsafe(inbox.put_nowait, True)
    except Exception:
        log.warning("Kênh sự kiện của job %s bị đứt", job_id)
    finally:
        try:
            pubsub.close()
        except Exception:
            return


@router.get("/jobs/{job_id}/events", dependencies=[Depends(_bearer)])
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    with Session(get_engine()) as db:
        user = current_user(request, db)
        job = owned_job(db, user, job_id)
        target = job.id
    after = parse_after(request.query_params.get("after_seq"))

    async def frames():
        last = after
        wake = watch_job(str(target))
        stop = threading.Event()
        inbox: asyncio.Queue = asyncio.Queue()
        redis_url = get_settings().redis_url
        if redis_url:
            threading.Thread(
                target=_listen_redis,
                args=(str(target), asyncio.get_running_loop(), inbox, stop),
                name=f"job-events-{str(target)[:8]}",
                daemon=True,
            ).start()
        try:
            while True:
                if await request.is_disconnected():
                    break
                rows, status = await asyncio.to_thread(read_snapshot, target, last)
                finished = False
                for seq, event_type, payload in rows:
                    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"
                    last = seq
                    if event_type in _TERMINAL_EVENTS:
                        finished = True
                if finished or (not rows and status in _TERMINAL):
                    break
                if os.environ.get("STT_SSE_ONCE") == "1":
                    break
                if redis_url:
                    try:
                        await asyncio.wait_for(inbox.get(), 15)
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.to_thread(wake.wait, 1.0)
                    wake.clear()
        finally:
            stop.set()
            unwatch_job(str(target), wake)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
