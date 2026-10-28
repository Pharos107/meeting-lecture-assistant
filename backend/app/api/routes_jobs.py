"""Job, transcript, đánh dấu, việc tại câu, và token nghe lại."""

import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.routes_auth import current_user, read_object, validation
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.rate_limit import client_key, upload_attempts
from app.services.dispatch import enqueue
from app.services.gpu_lock import get_gpu_lock, keeper
from app.services.live_channel import close_session, unlink_pcm
from app.services.housekeeping import purge_expired_secrets
from app.core.security import hash_refresh_token
from app.core.timeutil import as_utc, iso_micros, iso_seconds
from app.db import get_db
from app.models import ActionItem, Highlight, Job, LiveSession, MediaToken, Segment, SpeakerAlias, User, Word

router = APIRouter(prefix="/api", tags=["jobs"], dependencies=[Depends(current_user)])
media_router = APIRouter(prefix="/api", tags=["media"])

_ALLOWED = {"mp3", "wav", "m4a", "aac", "ogg", "opus", "flac", "mp4", "mkv", "webm", "mov"}
_OPUS = {"ogg", "opus"}
_NOT_FOUND = "Không tìm thấy."
_INVALID_STATE = "Trạng thái hiện tại không cho phép thao tác này."
_CANCEL_OK = {"queued", "capturing", "preprocessing", "transcribing"}


def not_found() -> ApiError:
    return ApiError(404, "not_found", _NOT_FOUND)


def invalid_state() -> ApiError:
    return ApiError(409, "invalid_state", _INVALID_STATE)


def form_text(form, name: str) -> str | None:
    value = form.get(name)
    if value is None or isinstance(value, UploadFile):
        return None
    return str(value)


def owned_job(db: Session, user: User, job_id: str) -> Job:
    try:
        parsed = uuid.UUID(job_id)
    except ValueError:
        raise not_found()
    job = db.get(Job, parsed)
    if job is None or job.user_id != user.id:
        raise not_found()
    return job


def job_summary(job: Job) -> dict:
    warnings = job.warnings if isinstance(job.warnings, list) else []
    return {
        "id": str(job.id),
        "title": job.title,
        "source": job.source,
        "status": job.status,
        "duration_ms": job.duration_ms,
        "warnings": warnings,
        "created_at": iso_seconds(job.created_at),
    }


def job_detail(job: Job) -> dict:
    body = job_summary(job)
    body.update(
        {
            "error_code": job.error_code,
            "error_message": job.error_message,
            "vocabulary": job.vocabulary,
            "num_speakers": job.num_speakers,
            "diarization_device": job.diarization_device,
            "started_at": iso_seconds(job.started_at),
            "finished_at": iso_seconds(job.finished_at),
        }
    )
    return body


def parse_limit(raw: str | None) -> int:
    message = "limit phải từ 1 đến 100."
    if raw is None:
        return 20
    if not raw.isdigit():
        raise ApiError(422, "validation", message, {"limit": message})
    value = int(raw)
    if value < 1 or value > 100:
        raise ApiError(422, "validation", message, {"limit": message})
    return value


def parse_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    message = "Cursor không hợp lệ."
    stamp_text, separator, id_text = raw.partition("|")
    if not separator:
        raise ApiError(422, "validation", message, {"cursor": message})
    try:
        stamp = datetime.strptime(stamp_text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        job_id = uuid.UUID(id_text)
    except ValueError:
        raise ApiError(422, "validation", message, {"cursor": message})
    return stamp, job_id


def page_jobs(db: Session, user: User, limit: int, cursor: str | None) -> tuple[list[Job], str | None]:
    stmt = select(Job).where(Job.user_id == user.id)
    if cursor:
        stamp, job_id = parse_cursor(cursor)
        stmt = stmt.where(or_(Job.created_at < stamp, and_(Job.created_at == stamp, Job.id < job_id)))
    rows = list(db.scalars(stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)).all())
    page = rows[:limit]
    next_cursor = f"{iso_micros(page[-1].created_at)}|{page[-1].id}" if len(rows) > limit else None
    return page, next_cursor


def data_root() -> Path:
    return Path(get_settings().data_dir).resolve()


def remove_job_files(job: Job) -> None:
    root = data_root()
    tmp = root / "tmp" / str(job.id)
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    opus = root / "audio" / f"{job.id}.opus"
    opus.unlink(missing_ok=True)
    if not job.audio_path:
        return
    candidate = Path(job.audio_path).resolve()
    if candidate != opus and (candidate == root or root in candidate.parents):
        candidate.unlink(missing_ok=True)


async def write_upload(upload: UploadFile, dest: Path, limit: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with dest.open("wb") as handle:
            while True:
                piece = await upload.read(1024 * 1024)
                if not piece:
                    break
                size += len(piece)
                if size > limit:
                    raise ApiError(413, "file_too_large", "File vượt quá kích thước cho phép.")
                handle.write(piece)
        if size == 0:
            raise ApiError(422, "validation", "Vui lòng chọn file.", {"file": "Vui lòng chọn file."})
    except ApiError:
        dest.unlink(missing_ok=True)
        raise


def highest_pass(db: Session, job: Job) -> int | None:
    passes = db.scalars(select(Segment.pass_index).where(Segment.job_id == job.id)).all()
    if not passes:
        return None
    return max(passes)


def ensure_mutable(job: Job, pass_no: int | None) -> None:
    if job.status == "ready":
        return
    if job.status == "failed" and pass_no == 1:
        return
    raise invalid_state()


def load_aliases(db: Session, job: Job) -> dict[str, SpeakerAlias]:
    rows = db.scalars(select(SpeakerAlias).where(SpeakerAlias.job_id == job.id)).all()
    return {row.speaker_label: row for row in rows}


def speaker_name(label: str | None, aliases: dict[str, SpeakerAlias]) -> str | None:
    if label is None:
        return None
    alias = aliases.get(label)
    if alias is None:
        return label
    return alias.display_name


def load_words(db: Session, segment_id: uuid.UUID) -> list[Word]:
    return list(db.scalars(select(Word).where(Word.segment_id == segment_id).order_by(Word.position)).all())


def load_words_by_segment(db: Session, job: Job, pass_no: int) -> dict[uuid.UUID, list[Word]]:
    """Đọc từ của cả pass trong một truy vấn."""
    rows = db.scalars(
        select(Word)
        .join(Segment, Segment.id == Word.segment_id)
        .where(Segment.job_id == job.id, Segment.pass_index == pass_no)
        .order_by(Word.segment_id, Word.position)
    ).all()
    grouped: dict[uuid.UUID, list[Word]] = {}
    for word in rows:
        grouped.setdefault(word.segment_id, []).append(word)
    return grouped


def segment_json(segment: Segment, words: list[Word], aliases: dict[str, SpeakerAlias]) -> dict:
    return {
        "id": str(segment.id),
        "position": segment.position,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "text_raw": segment.text_raw,
        "text_cleaned": segment.text_cleaned,
        "text_edited": segment.text_edited,
        "speaker_label": segment.speaker_label,
        "speaker_name": speaker_name(segment.speaker_label, aliases),
        "words": [
            {
                "text": word.text,
                "start_ms": word.start_ms,
                "end_ms": word.end_ms,
                "speaker_label": word.speaker_label,
            }
            for word in words
        ],
    }


def current_segments(db: Session, job: Job) -> tuple[int | None, list[Segment]]:
    pass_no = highest_pass(db, job)
    if pass_no is None:
        return None, []
    rows = list(
        db.scalars(
            select(Segment)
            .where(Segment.job_id == job.id, Segment.pass_index == pass_no)
            .order_by(Segment.position)
        ).all()
    )
    return pass_no, rows


def segment_on_pass(db: Session, job: Job, segment_id: str, pass_no: int | None) -> Segment:
    try:
        parsed = uuid.UUID(segment_id)
    except ValueError:
        raise not_found()
    segment = db.get(Segment, parsed)
    if segment is None or segment.job_id != job.id or pass_no is None or segment.pass_index != pass_no:
        raise not_found()
    return segment


@router.post("/jobs", status_code=201)
async def create_job(request: Request, db: Session = Depends(get_db)) -> dict:
    upload_attempts.hit(client_key(request))
    user = current_user(request, db)
    form = await request.form()
    fields: dict[str, str] = {}
    upload = form.get("file")
    suffix = ""
    filename = ""
    if not isinstance(upload, UploadFile) or not upload.filename:
        fields["file"] = "Vui lòng chọn file."
    else:
        filename = Path(upload.filename).name
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in _ALLOWED:
            fields["file"] = "Định dạng file không được hỗ trợ."

    title_raw = form_text(form, "title")
    title = ""
    if title_raw is None or not title_raw.strip():
        title = (Path(filename).stem[:200] if filename else "") or "audio"
    else:
        title = title_raw.strip()
        if len(title) > 200:
            fields["title"] = "Tiêu đề tối đa 200 ký tự."

    vocabulary_raw = form_text(form, "vocabulary")
    vocabulary: str | None = None
    if vocabulary_raw is not None and vocabulary_raw.strip():
        vocabulary = vocabulary_raw.strip()
        if len(vocabulary) > 800:
            fields["vocabulary"] = "Danh sách thuật ngữ tối đa 800 ký tự."

    speakers_raw = form_text(form, "num_speakers")
    num_speakers: int | None = None
    if speakers_raw is not None and speakers_raw.strip():
        text = speakers_raw.strip()
        if not text.isdigit() or not 1 <= int(text) <= 20:
            fields["num_speakers"] = "Số người nói phải từ 1 đến 20."
        else:
            num_speakers = int(text)
    if fields and isinstance(upload, UploadFile):
        await upload.close()
    validation(fields)

    assert isinstance(upload, UploadFile)
    settings = get_settings()
    limit = settings.max_opus_bytes if suffix in _OPUS else settings.max_original_bytes
    job_id = uuid.uuid4()
    dest = data_root() / "tmp" / str(job_id) / f"source.{suffix}"
    try:
        await write_upload(upload, dest, limit)
    except ApiError:
        tmp = dest.parent
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        await upload.close()

    job = Job(
        id=job_id,
        user_id=user.id,
        title=title,
        source="upload",
        status="queued",
        warnings=[],
        vocabulary=vocabulary,
        num_speakers=num_speakers,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    enqueue("app.tasks.transcribe_upload", str(job.id))
    return {"job_id": str(job.id), "status": job.status}


@router.get("/jobs")
def list_jobs(request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    limit = parse_limit(request.query_params.get("limit"))
    cursor = request.query_params.get("cursor")
    if cursor == "":
        cursor = None
    page, next_cursor = page_jobs(db, user, limit, cursor)
    return {"items": [job_summary(job) for job in page], "next_cursor": next_cursor}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    return job_detail(owned_job(db, user, job_id))


def end_live_capture(session: LiveSession) -> None:
    """Dừng thu, nhả khóa GPU, và xóa PCM. Giữ các câu pass 1."""
    close_session(str(session.id))
    keeper.stop(str(session.id))
    get_gpu_lock().release(str(session.id))
    session.status = "failed"
    session.ended_at = datetime.now(timezone.utc)
    unlink_pcm(session.pcm_path)


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    if job.status not in _CANCEL_OK:
        raise invalid_state()
    if job.status == "capturing":
        session = db.scalar(select(LiveSession).where(LiveSession.job_id == job.id))
        if session is not None:
            end_live_capture(session)
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return job_detail(job)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    if job.status != "failed":
        raise invalid_state()
    segment_ids = list(
        db.scalars(select(Segment.id).where(Segment.job_id == job.id, Segment.pass_index == 2)).all()
    )
    if segment_ids:
        db.query(Highlight).filter(Highlight.segment_id.in_(segment_ids)).delete(synchronize_session=False)
        db.query(Word).filter(Word.segment_id.in_(segment_ids)).delete(synchronize_session=False)
        db.query(ActionItem).filter(ActionItem.segment_id.in_(segment_ids)).update(
            {ActionItem.segment_id: None},
            synchronize_session=False,
        )
        db.query(Segment).filter(Segment.id.in_(segment_ids)).delete(synchronize_session=False)
    job.status = "queued"
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    db.commit()
    enqueue("app.tasks.transcribe_upload", str(job.id))
    return job_detail(job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    session = db.scalar(select(LiveSession).where(LiveSession.job_id == job.id))
    if job.status == "capturing" and session is not None:
        end_live_capture(session)
    remove_job_files(job)
    db.delete(job)
    db.commit()
    return Response(status_code=204)


@router.get("/jobs/{job_id}/transcript")
def get_transcript(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    pass_no, segments = current_segments(db, job)
    aliases = load_aliases(db, job)
    words_by_segment = load_words_by_segment(db, job, pass_no) if pass_no is not None else {}
    seen: list[str] = []
    rendered = []
    for segment in segments:
        rendered.append(segment_json(segment, words_by_segment.get(segment.id, []), aliases))
        if segment.speaker_label and segment.speaker_label not in seen:
            seen.append(segment.speaker_label)
    speakers = []
    for label in seen:
        alias = aliases.get(label)
        speakers.append(
            {
                "label": label,
                "display_name": alias.display_name if alias is not None else label,
                "source": alias.source if alias is not None else None,
            }
        )
    return {"pass": pass_no, "segments": rendered, "speakers": speakers}


@router.patch("/jobs/{job_id}/segments/{segment_id}")
async def patch_segment(
    job_id: str,
    segment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    pass_no = highest_pass(db, job)
    ensure_mutable(job, pass_no)
    data = await read_object(request)
    if "text_edited" not in data or (data["text_edited"] is not None and not isinstance(data["text_edited"], str)):
        validation({"text_edited": "Nội dung sửa không hợp lệ."})
    segment = segment_on_pass(db, job, segment_id, pass_no)
    segment.text_edited = data["text_edited"]
    db.commit()
    return segment_json(segment, load_words(db, segment.id), load_aliases(db, job))


@router.patch("/jobs/{job_id}/speakers/{label}")
async def patch_speaker(job_id: str, label: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    pass_no, segments = current_segments(db, job)
    ensure_mutable(job, pass_no)
    if not any(segment.speaker_label == label for segment in segments):
        raise not_found()
    data = await read_object(request)
    raw = data.get("display_name")
    if not isinstance(raw, str):
        validation({"display_name": "Vui lòng nhập tên."})
    name = raw.strip()
    existing = db.get(SpeakerAlias, (job.id, label))
    if not name:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return {"label": label, "display_name": label, "source": None}
    if len(name) > 80:
        validation({"display_name": "Tên hiển thị phải từ 1 đến 80 ký tự."})
    if existing is None:
        existing = SpeakerAlias(job_id=job.id, speaker_label=label, display_name=name, source="manual")
        db.add(existing)
    else:
        existing.display_name = name
        existing.source = "manual"
    db.commit()
    return {"label": label, "display_name": name, "source": "manual"}


def highlight_json(row: Highlight) -> dict:
    return {
        "id": str(row.id),
        "segment_id": str(row.segment_id),
        "quote": row.quote,
        "start_ms": row.start_ms,
        "end_ms": row.end_ms,
    }


def action_json(row: ActionItem) -> dict:
    return {
        "id": str(row.id),
        "segment_id": str(row.segment_id) if row.segment_id is not None else None,
        "start_ms": row.start_ms,
        "owner": row.owner,
        "task": row.task,
        "deadline": row.deadline,
        "source": row.source,
    }


@router.get("/jobs/{job_id}/highlights")
def list_highlights(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    rows = list(db.scalars(select(Highlight).where(Highlight.job_id == job.id)).all())
    rows.sort(key=lambda row: (as_utc(row.created_at), row.id.int))
    return {"items": [highlight_json(row) for row in rows]}


@router.post("/jobs/{job_id}/highlights", status_code=201)
async def create_highlight(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    pass_no = highest_pass(db, job)
    ensure_mutable(job, pass_no)
    data = await read_object(request)
    fields: dict[str, str] = {}
    quote = data.get("quote")
    quote_text = quote.strip() if isinstance(quote, str) else ""
    if not isinstance(quote, str) or not quote_text or len(quote_text) > 500:
        fields["quote"] = "Trích đoạn phải từ 1 đến 500 ký tự."
    start_ms = data.get("start_ms")
    end_ms = data.get("end_ms")
    times_ok = (
        isinstance(start_ms, int)
        and not isinstance(start_ms, bool)
        and isinstance(end_ms, int)
        and not isinstance(end_ms, bool)
        and start_ms < end_ms
    )
    segment_id = data.get("segment_id")
    segment: Segment | None = None
    if not isinstance(segment_id, str):
        raise not_found()
    if not fields:
        segment = segment_on_pass(db, job, segment_id, pass_no)
        if not times_ok or start_ms < segment.start_ms or end_ms > segment.end_ms:
            fields["start_ms"] = "Mốc thời gian không nằm trong câu."
    elif not times_ok:
        fields["start_ms"] = "Mốc thời gian không nằm trong câu."
    validation(fields)
    assert segment is not None
    row = Highlight(
        job_id=job.id,
        segment_id=segment.id,
        quote=quote_text,
        start_ms=start_ms,
        end_ms=end_ms,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return highlight_json(row)


@router.delete("/jobs/{job_id}/highlights/{highlight_id}", status_code=204)
def delete_highlight(job_id: str, highlight_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    try:
        parsed = uuid.UUID(highlight_id)
    except ValueError:
        raise not_found()
    row = db.get(Highlight, parsed)
    if row is None or row.job_id != job.id:
        raise not_found()
    db.delete(row)
    db.commit()
    return Response(status_code=204)


def bounded_note(data: dict, name: str, message: str, fields: dict[str, str]) -> str | None:
    if name not in data:
        return None
    value = data[name]
    if not isinstance(value, str) or len(value.strip()) > 200:
        fields[name] = message
        return None
    return value.strip()


@router.get("/jobs/{job_id}/actions")
def list_actions(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    rows = list(
        db.scalars(select(ActionItem).where(ActionItem.job_id == job.id, ActionItem.source == "manual")).all()
    )
    rows.sort(key=lambda row: (as_utc(row.created_at), row.id.int))
    return {"items": [action_json(row) for row in rows]}


@router.post("/jobs/{job_id}/actions", status_code=201)
async def create_action(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    pass_no = highest_pass(db, job)
    ensure_mutable(job, pass_no)
    data = await read_object(request)
    fields: dict[str, str] = {}
    task = data.get("task")
    task_text = task.strip() if isinstance(task, str) else ""
    if not isinstance(task, str) or not task_text or len(task_text) > 500:
        fields["task"] = "Việc cần làm phải từ 1 đến 500 ký tự."
    owner = bounded_note(data, "owner", "Tên người phụ trách tối đa 200 ký tự.", fields)
    deadline = bounded_note(data, "deadline", "Hạn chót tối đa 200 ký tự.", fields)
    validation(fields)
    segment_id = data.get("segment_id")
    if not isinstance(segment_id, str):
        raise not_found()
    segment = segment_on_pass(db, job, segment_id, pass_no)
    row = ActionItem(
        job_id=job.id,
        segment_id=segment.id,
        start_ms=segment.start_ms,
        owner=owner or "",
        task=task_text,
        deadline=deadline or "",
        source="manual",
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return action_json(row)


@router.patch("/jobs/{job_id}/actions/{action_id}")
async def patch_action(job_id: str, action_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    pass_no = highest_pass(db, job)
    ensure_mutable(job, pass_no)
    try:
        parsed = uuid.UUID(action_id)
    except ValueError:
        raise not_found()
    row = db.get(ActionItem, parsed)
    if row is None or row.job_id != job.id or row.source != "manual":
        raise not_found()
    data = await read_object(request)
    if not any(name in data for name in ("task", "owner", "deadline")):
        raise ApiError(422, "validation", "Dữ liệu không hợp lệ.")
    fields: dict[str, str] = {}
    if "task" in data:
        task = data["task"]
        task_text = task.strip() if isinstance(task, str) else ""
        if not isinstance(task, str) or not task_text or len(task_text) > 500:
            fields["task"] = "Việc cần làm phải từ 1 đến 500 ký tự."
        else:
            row.task = task_text
    owner = bounded_note(data, "owner", "Tên người phụ trách tối đa 200 ký tự.", fields)
    deadline = bounded_note(data, "deadline", "Hạn chót tối đa 200 ký tự.", fields)
    validation(fields)
    if owner is not None:
        row.owner = owner
    if deadline is not None:
        row.deadline = deadline
    db.commit()
    return action_json(row)


@router.delete("/jobs/{job_id}/actions/{action_id}", status_code=204)
def delete_action(job_id: str, action_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    try:
        parsed = uuid.UUID(action_id)
    except ValueError:
        raise not_found()
    row = db.get(ActionItem, parsed)
    if row is None or row.job_id != job.id:
        raise not_found()
    db.delete(row)
    db.commit()
    return Response(status_code=204)


def media_path(job: Job) -> Path | None:
    if not job.audio_path:
        return None
    root = data_root()
    candidate = Path(job.audio_path).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def parse_range(header: str, length: int) -> tuple[int, int]:
    if not header.startswith("bytes=") or "," in header:
        raise ValueError(header)
    spec = header.removeprefix("bytes=").strip()
    if spec.startswith("-"):
        suffix = int(spec[1:])
        if suffix <= 0:
            raise ValueError(header)
        if length == 0:
            raise ValueError(header)
        return max(length - suffix, 0), length - 1
    start_text, separator, end_text = spec.partition("-")
    if not separator or start_text == "":
        raise ValueError(header)
    start = int(start_text)
    end = length - 1 if end_text == "" else int(end_text)
    if length == 0 or start < 0 or start >= length or end < start:
        raise ValueError(header)
    return start, min(end, length - 1)


@router.post("/jobs/{job_id}/media-token")
def create_media_token(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    purge_expired_secrets(db)
    raw = secrets.token_urlsafe(32)
    db.add(
        MediaToken(
            token_hash=hash_refresh_token(raw),
            job_id=job.id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    db.commit()
    return {"token": raw, "expires_in": 300, "url": f"/api/media/{raw}"}


@media_router.get("/media/{token}")
def get_media(token: str, request: Request, db: Session = Depends(get_db)) -> Response:
    purge_expired_secrets(db)
    row = db.get(MediaToken, hash_refresh_token(token))
    if row is None or as_utc(row.expires_at) <= datetime.now(timezone.utc):
        raise not_found()
    job = db.get(Job, row.job_id)
    path = media_path(job) if job is not None else None
    if path is None:
        raise not_found()
    length = path.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        try:
            parse_range(range_header, length)
        except ValueError:
            return Response(status_code=416, headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{length}"})
    return FileResponse(path, media_type="audio/ogg")
