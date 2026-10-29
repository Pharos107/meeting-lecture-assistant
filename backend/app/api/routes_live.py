"""Phiên nghe trực tiếp."""

import asyncio
import json
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_auth import current_user, read_object, validation
from app.api.routes_jobs import data_root, not_found
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import hash_refresh_token
from app.core.timeutil import as_utc
from app.db import get_db, get_engine
from app.models import Job, LiveSession, User, WsTicket
from app.schemas.http import LiveSessionBody, request_body
from app.services.dispatch import enqueue
from app.services.gpu_lock import get_gpu_lock, keeper
from app.services.housekeeping import delete_expired_secrets, purge_expired_secrets
from app.services.live_channel import (
    LiveFeed,
    capture_closed,
    claim_writer,
    pcm_lock,
    read_open_draft,
    unlink_pcm,
    writer_current,
)
from app.services.live_heartbeat import touch

router = APIRouter(prefix="/api", tags=["live"])

_GPU_BUSY = "GPU đang bận với một phiên khác."


def session_json(session: LiveSession) -> dict:
    return {
        "id": str(session.id),
        "status": session.status,
        "job_id": str(session.job_id) if session.job_id is not None else None,
        "title": session.title,
    }


def issue_ticket(db: Session, session: LiveSession) -> dict:
    delete_expired_secrets(db)
    raw = secrets.token_urlsafe(32)
    db.add(
        WsTicket(
            token_hash=hash_refresh_token(raw),
            session_id=session.id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
    )
    return {
        "ticket": raw,
        "expires_in": 60,
        "ws_path": f"/api/live/sessions/{session.id}/stream",
    }


def owned_session(db: Session, user: User, session_id: str) -> LiveSession:
    try:
        parsed = uuid.UUID(session_id)
    except ValueError:
        raise not_found()
    session = db.get(LiveSession, parsed)
    if session is None or session.user_id != user.id:
        raise not_found()
    return session


def parse_live_body(data: dict) -> tuple[str, str | None, int | None]:
    fields: dict[str, str] = {}
    title = data.get("title")
    title_text = title.strip() if isinstance(title, str) else ""
    if not isinstance(title, str) or not title_text or len(title_text) > 200:
        fields["title"] = "Tiêu đề phải từ 1 đến 200 ký tự."
    vocabulary = data.get("vocabulary")
    vocabulary_text: str | None = None
    if vocabulary is not None:
        if not isinstance(vocabulary, str) or len(vocabulary.strip()) > 800:
            fields["vocabulary"] = "Danh sách thuật ngữ tối đa 800 ký tự."
        elif vocabulary.strip():
            vocabulary_text = vocabulary.strip()
    speakers = data.get("num_speakers")
    num_speakers: int | None = None
    if speakers is not None:
        if isinstance(speakers, bool) or not isinstance(speakers, int) or not 1 <= speakers <= 20:
            fields["num_speakers"] = "Số người nói phải từ 1 đến 20."
        else:
            num_speakers = speakers
    validation(fields)
    return title_text, vocabulary_text, num_speakers


@router.post(
    "/live/sessions",
    status_code=201,
    dependencies=[Depends(current_user)],
    openapi_extra=request_body(LiveSessionBody),
)
async def create_session(request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    data = await read_object(request)
    title, vocabulary, num_speakers = parse_live_body(data)
    session_id = uuid.uuid4()
    job_id = uuid.uuid4()
    if not get_gpu_lock().acquire(str(session_id)):
        raise ApiError(409, "gpu_busy", _GPU_BUSY)
    keeper.start(str(session_id), until_quiet=True)
    now = datetime.now(timezone.utc)
    try:
        job = Job(
            id=job_id,
            user_id=user.id,
            title=title,
            source="live",
            status="capturing",
            warnings=[],
            vocabulary=vocabulary,
            num_speakers=num_speakers,
            created_at=now,
        )
        session = LiveSession(
            id=session_id,
            user_id=user.id,
            job_id=job_id,
            title=title,
            status="capturing",
            vocabulary=vocabulary,
            num_speakers=num_speakers,
            pcm_path=str(data_root() / "tmp" / f"{session_id}.pcm"),
            created_at=now,
        )
        db.add(job)
        db.add(session)
        ticket = issue_ticket(db, session)
        db.commit()
    except Exception:
        keeper.stop(str(session_id))
        get_gpu_lock().release(str(session_id))
        raise
    enqueue("app.tasks.run_live_session", str(session_id))
    return {
        "session_id": str(session_id),
        "job_id": str(job_id),
        "ticket": ticket["ticket"],
        "expires_in": 60,
        "ws_path": ticket["ws_path"],
    }


@router.post("/live/sessions/{session_id}/ticket", dependencies=[Depends(current_user)])
async def refresh_ticket(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    session = owned_session(db, user, session_id)
    if session.status != "capturing":
        raise ApiError(409, "invalid_state", "Trạng thái hiện tại không cho phép thao tác này.")
    ticket = issue_ticket(db, session)
    db.commit()
    return ticket


@router.get("/live/sessions/{session_id}", dependencies=[Depends(current_user)])
def get_session(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    return session_json(owned_session(db, user, session_id))


@router.post("/live/sessions/{session_id}/stop", status_code=202, dependencies=[Depends(current_user)])
async def stop_session(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    session = owned_session(db, user, session_id)
    if session.status == "capturing":
        session.status = "stopping"
        db.commit()
    return session_json(session)


async def _take_live_messages(websocket: WebSocket, feed: LiveFeed, owner: str, token: int) -> bool:
    """Gửi bản nháp. Trả về True khi socket này phải dừng."""
    for payload in feed.drain():
        kind = payload.get("type")
        if kind == "session_closed" or not writer_current(owner, token):
            return True
        if kind == "writer_replaced":
            continue
        await websocket.send_json(payload)
    return False


def _write_frame(lock: threading.Lock, handle, frame: bytes, owner: str, token: int) -> bool:
    with lock:
        if not writer_current(owner, token):
            return False
        handle.write(frame)
        handle.flush()
        return True


def _job_cancelled(session_id) -> bool:
    parsed = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    with Session(get_engine()) as db:
        row = db.get(LiveSession, parsed)
        if row is None or row.status == "failed" or row.job_id is None:
            return True
        job = db.get(Job, row.job_id)
        return job is None or job.status == "cancelled"


def _valid_pcm(payload: bytes) -> bool:
    if len(payload) == 0 or len(payload) % 2 != 0:
        return False
    millis = (len(payload) // 2) * 1000 / 16000
    return 20 <= millis <= 200


def _load_ticket(token: str) -> tuple[LiveSession, Job] | None:
    with Session(get_engine()) as db:
        purge_expired_secrets(db)
        ticket = db.get(WsTicket, hash_refresh_token(token))
        if ticket is None or as_utc(ticket.expires_at) <= datetime.now(timezone.utc):
            return None
        session = db.get(LiveSession, ticket.session_id)
        if session is None or session.job_id is None:
            return None
        job = db.get(Job, session.job_id)
        if job is None:
            return None
        db.expunge(session)
        db.expunge(job)
        return session, job


@router.websocket("/live/sessions/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    token = websocket.query_params.get("ticket", "")
    loaded = _load_ticket(token)
    try:
        parsed = uuid.UUID(session_id)
    except ValueError:
        parsed = None
    if loaded is None or parsed is None or loaded[0].id != parsed or loaded[0].status != "capturing":
        await websocket.send_json({"type": "error", "code": "unauthorized", "message": "Ticket không hợp lệ hoặc đã hết hạn."})
        await websocket.close()
        return
    session, job = loaded
    owner = str(session.id)
    if not get_gpu_lock().refresh(owner) and not get_gpu_lock().acquire(owner):
        await websocket.send_json({"type": "error", "code": "gpu_busy", "message": _GPU_BUSY})
        await websocket.close()
        return
    keeper.start(owner, until_quiet=True)
    try:
        incoming = await asyncio.wait_for(websocket.receive(), timeout=5)
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "code": "hello_timeout", "message": "Không nhận được hello trong 5 giây."})
        await websocket.close()
        return
    hello = incoming.get("text")
    if not hello:
        await websocket.send_json({"type": "error", "code": "bad_request", "message": "Tin đầu tiên phải là hello."})
        await websocket.close()
        return
    try:
        import json

        payload = json.loads(hello)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or payload.get("type") != "hello" or payload.get("sample_rate") != 16000:
        await websocket.send_json({"type": "error", "code": "bad_request", "message": "hello cần sample_rate 16000."})
        await websocket.close()
        return
    await websocket.send_json({"type": "hello_ok", "session_id": str(session.id)})
    touch(owner)
    draft = read_open_draft(owner)
    if draft is not None:
        await websocket.send_json(draft)
    feed = LiveFeed()
    feed.start(owner)
    token = claim_writer(owner)
    if token is None:
        feed.close()
        await websocket.send_json({"type": "error", "code": "invalid_state", "message": "Phiên nghe đã dừng."})
        await websocket.close()
        return
    pcm_path = Path(session.pcm_path) if session.pcm_path else data_root() / "tmp" / f"{session.id}.pcm"
    pcm_path.parent.mkdir(parents=True, exist_ok=True)
    written = pcm_path.stat().st_size if pcm_path.is_file() else 0
    byte_limit = get_settings().max_duration_seconds * 16000 * 2
    file_lock = pcm_lock(owner)
    handle = None
    recv_task: asyncio.Task | None = None
    quiet_since = time.monotonic()
    try:
        handle = pcm_path.open("ab")
        recv_task = asyncio.create_task(websocket.receive())
        while writer_current(owner, token):
            done, _pending = await asyncio.wait({recv_task}, timeout=0.2)
            if await _take_live_messages(websocket, feed, owner, token):
                break
            if not writer_current(owner, token) or capture_closed(owner):
                break
            if recv_task not in done:
                if time.monotonic() - quiet_since >= 10:
                    touch(owner)
                    quiet_since = time.monotonic()
                    if _job_cancelled(session.id):
                        break
                continue
            try:
                message = recv_task.result()
            except WebSocketDisconnect:
                break
            recv_task = asyncio.create_task(websocket.receive())
            quiet_since = time.monotonic()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                frame = message["bytes"]
                if not _valid_pcm(frame):
                    await websocket.send_json({"type": "error", "code": "bad_request", "message": "Khung PCM không hợp lệ."})
                    await websocket.close()
                    return
                if written + len(frame) > byte_limit:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "payload_too_large",
                            "message": "Phiên nghe vượt quá thời lượng cho phép.",
                        }
                    )
                    await websocket.close()
                    return
                if not writer_current(owner, token):
                    break
                accepted = await anyio.to_thread.run_sync(_write_frame, file_lock, handle, frame, owner, token)
                if not accepted:
                    break
                written += len(frame)
                touch(owner)
                continue
            text = message.get("text")
            try:
                body = json.loads(text or "")
            except json.JSONDecodeError:
                body = None
            if isinstance(body, dict) and body.get("type") == "stop":
                with Session(get_engine()) as db:
                    current = db.get(LiveSession, session.id)
                    if current is not None and current.status == "capturing":
                        current.status = "stopping"
                        db.commit()
                await websocket.send_json({"type": "stopped", "job_id": str(job.id)})
                await websocket.close()
                return
            await websocket.send_json({"type": "error", "code": "bad_request", "message": "Tin không đọc được."})
            await websocket.close()
            return
    finally:
        if handle is not None:
            handle.close()
        feed.close()
        if capture_closed(owner):
            unlink_pcm(str(pcm_path))
        try:
            await websocket.close()
        except RuntimeError:
            pass
        if recv_task is not None and not recv_task.done():
            recv_task.cancel()
