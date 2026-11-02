"""Hỏi đáp về nội dung transcript của một bản ghi."""

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes_auth import current_user, read_object, validation
from app.api.routes_jobs import ensure_mutable, highest_pass, owned_job
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.rate_limit import chat_attempts, client_key
from app.db import get_db, get_engine
from app.models import ChatMessage
from app.schemas.http import ChatBody, request_body
from app.services.chat_service import (
    build_messages,
    create_turn,
    expire_stale,
    has_streaming,
    load_messages,
    save_answer,
)
from app.services.llm_client import LlmRateLimited, LlmTimeout, LlmUpstream, stream_chat

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"], dependencies=[Depends(current_user)])

MAX_QUESTION_CHARS = 2000
LIST_LIMIT = 200
SAVE_INTERVAL_S = 2.0
_ERROR_CODES = {LlmTimeout: "llm_timeout", LlmRateLimited: "llm_rate_limited", LlmUpstream: "llm_upstream"}
_ERROR_TEXT = {
    "llm_timeout": "Server LLM phản hồi quá lâu. Thử lại sau.",
    "llm_rate_limited": "Đã hết lượt hỏi của dịch vụ AI. Thử lại sau ít phút, hoặc sau khi hạn mức ngày được đặt lại.",
    "llm_upstream": "Không kết nối được server LLM. Thử lại sau.",
}


def chat_busy() -> ApiError:
    return ApiError(409, "chat_busy", "Bản ghi đang có một câu trả lời chạy.")


def message_json(row: ChatMessage) -> dict:
    body = {
        "id": str(row.id),
        "role": row.role,
        "content": row.content,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }
    if row.status == "failed":
        body["error_code"] = row.error_code
    return body


def frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def persist(answer_id, content: str, status: str, model: str | None = None, error_code: str | None = None) -> None:
    with Session(get_engine()) as db:
        save_answer(db, answer_id, content, status, model, error_code)


@router.get("/jobs/{job_id}/chat/messages")
def list_messages(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    expire_stale(db, job)
    return {"items": [message_json(row) for row in load_messages(db, job, LIST_LIMIT)]}


@router.delete("/jobs/{job_id}/chat/messages", status_code=204)
def clear_messages(job_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    expire_stale(db, job)
    if has_streaming(db, job):
        raise chat_busy()
    db.query(ChatMessage).filter(ChatMessage.job_id == job.id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=204)


@router.post("/jobs/{job_id}/chat/messages", openapi_extra=request_body(ChatBody))
async def ask(job_id: str, request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    ensure_mutable(job, highest_pass(db, job))
    settings = get_settings()
    model = settings.llm_model
    if not model or not settings.llm_api_key:
        raise ApiError(422, "llm_not_configured", "Chưa cấu hình model LLM.")
    chat_attempts.hit(client_key(request))

    data = await read_object(request)
    question = data.get("question")
    question = question.strip() if isinstance(question, str) else ""
    if not 1 <= len(question) <= MAX_QUESTION_CHARS:
        validation({"question": f"Câu hỏi phải từ 1 đến {MAX_QUESTION_CHARS} ký tự."})

    expire_stale(db, job)
    if has_streaming(db, job):
        raise chat_busy()
    messages = build_messages(db, job, question)

    asked, answer = create_turn(job, question)
    db.add_all([asked, answer])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise chat_busy() from exc
    question_id, answer_id = asked.id, answer.id

    async def frames():
        parts: list[str] = []
        saved_at = time.monotonic()
        finished = False

        def finish(status: str, error_code: str | None = None) -> None:
            nonlocal finished
            if not finished:
                finished = True
                persist(answer_id, "".join(parts), status, model if status == "done" else None, error_code)

        try:
            yield frame("start", {"question_id": str(question_id), "answer_id": str(answer_id)})
            async with contextlib.aclosing(stream_chat(messages)) as chunks:
                async for text in chunks:
                    if await request.is_disconnected():
                        finish("stopped")
                        return
                    parts.append(text)
                    yield frame("delta", {"text": text})
                    # Ghi dần để giữ được phần đã nhận, và để dòng không bị coi là treo.
                    if time.monotonic() - saved_at >= SAVE_INTERVAL_S:
                        saved_at = time.monotonic()
                        await asyncio.to_thread(persist, answer_id, "".join(parts), "streaming")
            finish("done")
            yield frame("done", {"answer_id": str(answer_id), "model": model})
        except (LlmTimeout, LlmRateLimited, LlmUpstream) as exc:
            code = _ERROR_CODES[type(exc)]
            log.warning("Hỏi đáp của job %s lỗi: %s", job_id, code)
            finish("failed", code)
            yield frame("error", {"code": code, "message": _ERROR_TEXT[code]})
        finally:
            # Client ngắt kết nối làm generator bị hủy tại một lần chờ bất kỳ.
            finish("stopped")

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
