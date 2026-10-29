"""Hồ sơ giọng của tài khoản."""

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.routes_auth import current_user, validation
from app.api.routes_jobs import _ALLOWED, data_root, form_text, not_found, write_upload
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.timeutil import iso_seconds
from app.db import get_db
from app.models import User, VoiceProfile
from app.services.diarization import PIPELINE_MODEL
from app.services.dispatch import enqueue

router = APIRouter(prefix="/api", tags=["voice"], dependencies=[Depends(current_user)])


def probe_sample(path: Path) -> tuple[int, int]:
    """Trả duration_ms và số mili giây còn tiếng. Worker có thể đo lại bằng VAD."""
    import json
    import subprocess

    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        duration = float(json.loads(completed.stdout)["format"]["duration"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        raise ApiError(422, "validation", "Không đọc được file âm thanh.", {"file": "Không đọc được file âm thanh."})
    millis = int(duration * 1000)
    return millis, millis


def profile_json(row: VoiceProfile) -> dict:
    stale = bool(row.embedding_model and row.embedding_model != PIPELINE_MODEL)
    return {
        "id": str(row.id),
        "display_name": row.display_name,
        "status": row.status,
        "duration_ms": row.duration_ms,
        "stale": stale,
        "created_at": iso_seconds(row.created_at),
    }


def owned_profile(db: Session, user: User, profile_id: str) -> VoiceProfile:
    try:
        parsed = uuid.UUID(profile_id)
    except ValueError:
        raise not_found()
    row = db.get(VoiceProfile, parsed)
    if row is None or row.user_id != user.id:
        raise not_found()
    return row


@router.get("/voice-profiles")
def list_profiles(request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    rows = list(db.scalars(select(VoiceProfile).where(VoiceProfile.user_id == user.id)).all())
    rows.sort(key=lambda row: row.created_at, reverse=True)
    return {"items": [profile_json(row) for row in rows]}


@router.get("/voice-profiles/{profile_id}")
def get_profile(profile_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    return profile_json(owned_profile(db, user, profile_id))


@router.post("/voice-profiles", status_code=202)
async def create_profile(request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    count = db.scalar(select(func.count()).select_from(VoiceProfile).where(VoiceProfile.user_id == user.id))
    if count is not None and int(count) >= 20:
        raise ApiError(422, "validation", "Mỗi tài khoản chỉ có tối đa 20 hồ sơ giọng.")
    form = await request.form()
    fields: dict[str, str] = {}
    upload = form.get("file")
    suffix = ""
    if not isinstance(upload, UploadFile) or not upload.filename:
        fields["file"] = "Vui lòng chọn file."
    else:
        suffix = Path(upload.filename).suffix.lower().lstrip(".")
        if suffix not in _ALLOWED:
            fields["file"] = "Định dạng file không được hỗ trợ."
    raw_name = form_text(form, "display_name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name or len(name) > 80:
        fields["display_name"] = "Tên hiển thị phải từ 1 đến 80 ký tự."
    validation(fields)
    assert isinstance(upload, UploadFile)
    profile_id = uuid.uuid4()
    dest = data_root() / "voice" / str(user.id) / f"{profile_id}.{suffix}"
    try:
        await write_upload(upload, dest, get_settings().max_voice_bytes)
        duration_ms, speech_ms = probe_sample(dest)
    except ApiError:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if duration_ms < 20_000 or duration_ms > 40_000:
        dest.unlink(missing_ok=True)
        raise ApiError(
            422,
            "validation",
            "Mẫu giọng phải dài từ 20 đến 40 giây.",
            {"file": "Mẫu giọng phải dài từ 20 đến 40 giây."},
        )
    if speech_ms < 15_000:
        dest.unlink(missing_ok=True)
        raise ApiError(
            422,
            "validation",
            "Mẫu giọng còn ít hơn 15 giây có tiếng.",
            {"file": "Mẫu giọng còn ít hơn 15 giây có tiếng."},
        )
    row = VoiceProfile(
        id=profile_id,
        user_id=user.id,
        display_name=name,
        status="processing",
        sample_path=str(dest),
        duration_ms=duration_ms,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    enqueue("app.tasks.enroll_voice", str(row.id))
    return {"profile_id": str(row.id), "status": row.status}


@router.delete("/voice-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    row = owned_profile(db, user, profile_id)
    if row.sample_path:
        path = Path(row.sample_path)
        root = data_root()
        if path.is_file() and (path == root or root in path.resolve().parents):
            path.unlink(missing_ok=True)
        parent = path.parent
        if parent.is_dir() and not any(parent.iterdir()):
            shutil.rmtree(parent, ignore_errors=True)
    db.delete(row)
    db.commit()
    return Response(status_code=204)
