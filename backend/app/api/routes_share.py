"""Chia sẻ transcript bằng liên kết: ai có liên kết cũng đọc được, không cần đăng nhập.

Bản ghi trực tiếp chia sẻ được ngay khi đang ghi: người xem nhận bản nháp qua SSE, rồi bản chuẩn khi xong.
"""

import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_auth import current_user
from app.api.routes_jobs import current_segments, invalid_state, load_aliases, not_found, owned_job, speaker_name
from app.core.rate_limit import client_key, share_views
from app.core.timeutil import iso_seconds
from app.db import get_db, get_engine
from app.models import Job, JobShare, LiveSession, Segment
from app.services.live_channel import LiveFeed, read_open_draft

# Bản ghi trực tiếp đang thu hoặc đang chạy bản chuẩn vẫn xem được qua liên kết.
_LIVE_VISIBLE = {"capturing", "preprocessing", "transcribing", "diarizing"}
_DRAFT_FIELDS = ("segment_id", "start_ms", "end_ms", "text", "stable")
STATUS_CHECK_S = 2.0
PING_S = 15.0
POLL_S = 0.2


def viewable(job: Job | None) -> bool:
    if job is None:
        return False
    return job.status == "ready" or (job.source == "live" and job.status in _LIVE_VISIBLE)


def shared_state(job: Job) -> str:
    if job.status == "capturing":
        return "live"
    return "ready" if job.status == "ready" else "processing"

router = APIRouter(prefix="/api", tags=["share"], dependencies=[Depends(current_user)])
public_router = APIRouter(prefix="/api", tags=["share"])


def share_json(row: JobShare | None) -> dict:
    if row is None:
        return {"enabled": False, "token": None, "url": None}
    return {"enabled": True, "token": row.token, "url": f"/shared/{row.token}"}


@router.get("/jobs/{job_id}/share")
def get_share(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    return share_json(db.get(JobShare, job.id))


@router.put("/jobs/{job_id}/share")
def enable_share(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    if not viewable(job):
        raise invalid_state()
    row = db.get(JobShare, job.id)
    if row is None:
        row = JobShare(job_id=job.id, token=secrets.token_urlsafe(32), created_at=datetime.now(timezone.utc))
        db.add(row)
        db.commit()
    return share_json(row)


@router.delete("/jobs/{job_id}/share", status_code=204)
def disable_share(job_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    row = db.get(JobShare, job.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=204)


@public_router.get("/shared/{token}")
def get_shared(token: str, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    share_views.hit(client_key(request))
    row = db.scalar(select(JobShare).where(JobShare.token == token))
    job = db.get(Job, row.job_id) if row is not None else None
    # Liên kết đã tắt, không tồn tại, hay bản ghi đang chạy lại đều trả cùng một mã.
    if not viewable(job):
        raise not_found()
    _, segments = current_segments(db, job)
    aliases = load_aliases(db, job)
    body = {
        "title": job.title,
        "state": shared_state(job),
        "duration_ms": job.duration_ms,
        "created_at": iso_seconds(job.created_at),
        "segments": [
            {
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text_edited or segment.text_raw,
                "speaker": speaker_name(segment.speaker_label, aliases),
            }
            for segment in segments
        ],
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


def _shared_live_target(token: str):
    with Session(get_engine()) as db:
        row = db.scalar(select(JobShare).where(JobShare.token == token))
        job = db.get(Job, row.job_id) if row is not None else None
        if job is None or job.source != "live" or job.status != "capturing":
            return None
        session = db.scalar(select(LiveSession).where(LiveSession.job_id == job.id))
        if session is None:
            return None
        return str(session.id), job.id


def _pass_one(job_id) -> list[dict]:
    with Session(get_engine()) as db:
        rows = db.scalars(
            select(Segment).where(Segment.job_id == job_id, Segment.pass_index == 1).order_by(Segment.position)
        ).all()
        return [
            {
                "segment_id": str(row.id),
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "text": row.text_edited or row.text_raw,
                "stable": True,
            }
            for row in rows
        ]


def _still_shared_and_capturing(token: str, job_id) -> bool:
    """Chủ tắt chia sẻ hoặc phiên rời `capturing` thì stream đang mở phải đóng."""
    with Session(get_engine()) as db:
        row = db.scalar(select(JobShare).where(JobShare.token == token))
        if row is None or row.job_id != job_id:
            return False
        job = db.get(Job, job_id)
        return job is not None and job.status == "capturing"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _public_draft(payload: dict) -> dict:
    return {key: payload.get(key) for key in _DRAFT_FIELDS}


@public_router.get("/shared/{token}/live")
async def shared_live(token: str, request: Request) -> StreamingResponse:
    """Bản nháp của phiên đang ghi cho người có liên kết. Hết phiên thì gửi `ended` rồi đóng."""
    share_views.hit(client_key(request))
    target = await asyncio.to_thread(_shared_live_target, token)
    if target is None:
        raise not_found()
    session_id, job_id = target

    async def frames():
        # Nghe kênh trước rồi mới đọc câu đã chốt, để câu chốt ở giữa hai bước không bị lỡ.
        feed = LiveFeed()
        feed.start(session_id)
        try:
            yield _sse("snapshot", {"segments": await asyncio.to_thread(_pass_one, job_id)})
            draft = read_open_draft(session_id)
            if draft is not None:
                yield _sse("draft", _public_draft(draft))
            checked = pinged = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                for payload in feed.drain():
                    kind = payload.get("type")
                    if kind == "draft":
                        yield _sse("draft", _public_draft(payload))
                    elif kind in {"session_closed", "stopped", "error"}:
                        yield _sse("ended", {})
                        return
                now = time.monotonic()
                if now - checked >= STATUS_CHECK_S:
                    checked = now
                    if not await asyncio.to_thread(_still_shared_and_capturing, token, job_id):
                        yield _sse("ended", {})
                        return
                if now - pinged >= PING_S:
                    pinged = now
                    yield ": ping\n\n"
                if os.environ.get("STT_SSE_ONCE") == "1":
                    return
                await asyncio.sleep(POLL_S)
        finally:
            feed.close()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "X-Robots-Tag": "noindex"},
    )
