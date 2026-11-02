"""Chia sẻ transcript bằng liên kết: ai có liên kết cũng đọc được, không cần đăng nhập."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_auth import current_user
from app.api.routes_jobs import current_segments, invalid_state, load_aliases, not_found, owned_job, speaker_name
from app.core.rate_limit import client_key, share_views
from app.core.timeutil import iso_seconds
from app.db import get_db
from app.models import Job, JobShare

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
    if job.status != "ready":
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
    if job is None or job.status != "ready":
        raise not_found()
    _, segments = current_segments(db, job)
    aliases = load_aliases(db, job)
    body = {
        "title": job.title,
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
