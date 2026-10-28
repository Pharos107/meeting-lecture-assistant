"""Chuẩn hóa câu và lập biên bản. Lát map chạy tuần tự."""

import json
import re
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_jobs import current_segments
from app.core.config import get_settings
from app.db import get_engine
from app.models import LlmMapShard, LlmRun, Segment

CLEAN_SYSTEM = """Bạn chuẩn hóa transcript tiếng Việt.
Giữ nguyên ý, tên riêng, số liệu và thuật ngữ.
Xóa từ đệm như "à", "ừ", "ừm", "kiểu như" khi chúng không mang nghĩa.
Sửa chính tả và dấu câu.
Không gộp câu và không tách câu.
Mỗi câu đầu vào có id. Trả về đúng các id đó, cùng thứ tự.
Chỉ trả JSON theo dạng {"segments":[{"id":"...","text":"..."}]}"""

MEETING_MAP = """Bạn trích xuất một phần cuộc họp tiếng Việt.
Mỗi dòng đầu vào có mốc [MM:SS].
Chỉ trả JSON:
{"bullets":[{"timestamp":"MM:SS","text":"..."}],"actions":[{"timestamp":"MM:SS","owner":"...","task":"...","deadline":"..."}]}
Mỗi bullet là một ý, một vấn đề, hoặc một quyết định. Không có việc cần làm thì actions là mảng rỗng.
Thiếu tên người phụ trách hoặc hạn chót thì để chuỗi rỗng. Không bịa."""

MEETING_REDUCE = """Bạn lập biên bản cuộc họp từ các phần đã trích.
Chỉ dùng thông tin có trong đầu vào.
Chỉ trả JSON:
{"objective":"...","open_issues":[{"timestamp":"MM:SS","text":"..."}],"decisions":[{"timestamp":"MM:SS","text":"..."}],"actions":[{"timestamp":"MM:SS","owner":"...","task":"...","deadline":"..."}]}
objective là mục tiêu của buổi. Thiếu thông tin thì để chuỗi rỗng hoặc mảng rỗng. Không bịa.
Gộp việc trùng nhau và giữ mốc thời gian sớm hơn."""

LECTURE_MAP = """Bạn trích xuất một phần bài giảng tiếng Việt.
Mỗi dòng đầu vào có mốc [MM:SS].
Chỉ trả JSON:
{"concepts":[{"timestamp":"MM:SS","term":"...","explanation":"..."}],"examples":[{"timestamp":"MM:SS","text":"..."}],"exam_notes":[{"timestamp":"MM:SS","text":"..."}]}
exam_notes chỉ gồm lời dặn ôn, phạm vi thi, hoặc bài tập. Không có thì để mảng rỗng. Không bịa."""

LECTURE_REDUCE = """Bạn lập ghi chú bài giảng từ các phần đã trích.
Chỉ dùng thông tin có trong đầu vào.
Chỉ trả JSON:
{"overview":"...","concepts":[{"timestamp":"MM:SS","term":"...","explanation":"..."}],"examples":[{"timestamp":"MM:SS","text":"..."}],"exam_notes":[{"timestamp":"MM:SS","text":"..."}]}
Gộp khái niệm trùng tên và giữ mốc thời gian sớm hơn. Thiếu thông tin thì để chuỗi rỗng hoặc mảng rỗng."""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class SchemaError(Exception):
    pass


class LlmTimeout(Exception):
    pass


class LlmUpstream(Exception):
    pass


def clock(ms: int) -> str:
    total = max(ms, 0) // 1000
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


def word_count(text: str) -> int:
    return len(text.split())


def shard_segments(
    segments: list[Segment],
    *,
    max_sentences: int | None = None,
    max_words: int | None = None,
    max_span_ms: int | None = None,
) -> list[list[Segment]]:
    shards: list[list[Segment]] = []
    current: list[Segment] = []
    words = 0
    for segment in segments:
        count = word_count(segment.text_raw)
        overflow = False
        if current:
            if max_sentences is not None and len(current) >= max_sentences:
                overflow = True
            if max_words is not None and words + count > max_words:
                overflow = True
            if max_span_ms is not None and segment.end_ms - current[0].start_ms > max_span_ms:
                overflow = True
        if overflow:
            shards.append(current)
            current = []
            words = 0
        current.append(segment)
        words += count
    if current:
        shards.append(current)
    return shards


def parse_json_content(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE.sub("", stripped).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SchemaError("JSON không đọc được.") from exc
    if not isinstance(data, dict):
        raise SchemaError("JSON phải là object.")
    return data


def _require_str(item: dict, key: str) -> None:
    if not isinstance(item.get(key), str):
        raise SchemaError(f"Thiếu hoặc sai field {key}.")


def _require_objects(data: dict, key: str, fields: tuple[str, ...]) -> None:
    rows = data.get(key)
    if not isinstance(rows, list):
        raise SchemaError(f"Thiếu field {key}.")
    for item in rows:
        if not isinstance(item, dict):
            raise SchemaError(f"Field {key} phải là danh sách object.")
        for field in fields:
            _require_str(item, field)


def validate_clean(data: dict, expected_ids: list[str]) -> list[str]:
    rows = data.get("segments")
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise SchemaError("Danh sách segments không khớp các câu đã gửi.")
    texts: list[str] = []
    for item, expected in zip(rows, expected_ids):
        if not isinstance(item, dict) or item.get("id") != expected:
            raise SchemaError("Id câu không đúng thứ tự.")
        _require_str(item, "text")
        texts.append(item["text"])
    return texts


def validate_meeting_map(data: dict) -> dict:
    _require_objects(data, "bullets", ("timestamp", "text"))
    _require_objects(data, "actions", ("timestamp", "owner", "task", "deadline"))
    return data


def validate_meeting_reduce(data: dict) -> dict:
    _require_str(data, "objective")
    _require_objects(data, "open_issues", ("timestamp", "text"))
    _require_objects(data, "decisions", ("timestamp", "text"))
    _require_objects(data, "actions", ("timestamp", "owner", "task", "deadline"))
    return data


def validate_lecture_map(data: dict) -> dict:
    _require_objects(data, "concepts", ("timestamp", "term", "explanation"))
    _require_objects(data, "examples", ("timestamp", "text"))
    _require_objects(data, "exam_notes", ("timestamp", "text"))
    return data


def validate_lecture_reduce(data: dict) -> dict:
    _require_str(data, "overview")
    _require_objects(data, "concepts", ("timestamp", "term", "explanation"))
    _require_objects(data, "examples", ("timestamp", "text"))
    _require_objects(data, "exam_notes", ("timestamp", "text"))
    return data


def http_chat(messages: list[dict]) -> str:
    settings = get_settings()
    if not settings.llm_model:
        raise SchemaError("Chưa cấu hình model LLM.")
    url = f"{settings.llm_base_url}/chat/completions"
    payload: dict = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "messages": messages,
    }
    if settings.llm_json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=settings.llm_timeout_seconds)
        if response.status_code == 400 and "response_format" in payload:
            payload.pop("response_format")
            response = httpx.post(url, json=payload, headers=headers, timeout=settings.llm_timeout_seconds)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException as exc:
        raise LlmTimeout("LLM hết hạn.") from exc
    except httpx.HTTPError as exc:
        raise LlmUpstream("Không gọi được LLM.") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmUpstream("Không gọi được LLM.") from exc
    if not isinstance(content, str):
        raise LlmUpstream("Không gọi được LLM.")
    return content


def _ask(transport, messages: list[dict], validate) -> dict:
    last_error = "JSON không đúng schema."
    for attempt in range(2):
        prompt = [dict(message) for message in messages]
        if attempt == 1:
            prompt[-1]["content"] = f"{prompt[-1]['content']}\n\nLỗi kiểm tra schema:\n{last_error}"
        try:
            data = parse_json_content(transport(prompt))
            return validate(data)
        except SchemaError as exc:
            last_error = str(exc)
        except (LlmTimeout, LlmUpstream):
            raise
    raise SchemaError(last_error)


def _user_preamble(vocabulary: str | None) -> str:
    if vocabulary:
        return f"Thuật ngữ:\n{vocabulary}\n\n"
    return ""


def _fail(db: Session, run: LlmRun, code: str, message: str) -> None:
    run.status = "failed"
    run.error_code = code
    run.error_message = message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def _fail_if_running(run_id: str) -> None:
    try:
        with Session(get_engine()) as db:
            run = db.get(LlmRun, uuid.UUID(str(run_id)))
            if run is None or run.status != "running":
                return
            _fail(db, run, "llm_upstream", "Không gọi được LLM.")
    except Exception:
        return


def execute_llm_run(run_id: str, transport=None) -> None:
    try:
        _execute_llm_run(run_id, transport)
    except Exception:
        _fail_if_running(run_id)


def _execute_llm_run(run_id: str, transport=None) -> None:
    caller = transport or http_chat
    with Session(get_engine()) as db:
        run = db.get(LlmRun, uuid.UUID(str(run_id)))
        if run is None or run.status != "running":
            return
        from app.models import Job

        job = db.get(Job, run.job_id)
        if job is None:
            _fail(db, run, "not_found", "Không tìm thấy job.")
            return
        settings = get_settings()
        if not settings.llm_model and transport is None:
            _fail(db, run, "llm_not_configured", "Chưa cấu hình model LLM.")
            return
        run.model_name = settings.llm_model or run.model_name
        _pass_no, segments = current_segments(db, job)
        if run.task == "clean":
            if run_id and _previous_clean_failed(db, job.id, run) and not _restart_requested(run):
                segments = [segment for segment in segments if segment.text_cleaned is None]
            _execute_clean(db, run, job, segments, caller)
            return
        _execute_summary(db, run, job, segments, caller)


def _restart_requested(run: LlmRun) -> bool:
    return bool(isinstance(run.result, dict) and run.result.get("restart") is True)


def _previous_clean_failed(db: Session, job_id, run: LlmRun) -> bool:
    previous = db.scalar(
        select(LlmRun)
        .where(LlmRun.job_id == job_id, LlmRun.task == "clean", LlmRun.id != run.id)
        .order_by(LlmRun.created_at.desc())
    )
    return previous is not None and previous.status == "failed"


def _execute_clean(db: Session, run: LlmRun, job, segments: list[Segment], caller) -> None:
    if _restart_requested(run):
        for segment in segments:
            segment.text_cleaned = None
        db.commit()
        _pass_no, segments = current_segments(db, job)
    shards = shard_segments(segments, max_sentences=30, max_words=600)
    for index, shard in enumerate(shards):
        existing = db.get(LlmMapShard, (run.id, index))
        if existing is not None and existing.status == "done":
            continue
        row = existing or LlmMapShard(
            run_id=run.id,
            shard_index=index,
            input_start_ms=shard[0].start_ms,
            input_end_ms=shard[-1].end_ms,
            status="running",
        )
        if existing is None:
            db.add(row)
        ids = [str(segment.id) for segment in shard]
        body = _user_preamble(job.vocabulary) + "\n".join(
            f'{segment.id} {segment.text_raw}' for segment in shard
        )
        messages = [
            {"role": "system", "content": CLEAN_SYSTEM},
            {"role": "user", "content": body},
        ]
        try:
            data = _ask(caller, messages, lambda payload: validate_clean(payload, ids))
        except LlmTimeout:
            row.status = "failed"
            _fail(db, run, "llm_timeout", "LLM hết hạn.")
            return
        except LlmUpstream:
            row.status = "failed"
            _fail(db, run, "llm_upstream", "Không gọi được LLM.")
            return
        except SchemaError as exc:
            row.status = "failed"
            _fail(db, run, "llm_invalid_json", str(exc))
            return
        for segment, text in zip(shard, data):
            segment.text_cleaned = text
        row.status = "done"
        row.result = {"segments": [{"id": segment_id, "text": text} for segment_id, text in zip(ids, data)]}
        db.commit()
    run.status = "done"
    run.result = None
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def _execute_summary(db: Session, run: LlmRun, job, segments: list[Segment], caller) -> None:
    shards = shard_segments(segments, max_words=3500, max_span_ms=20 * 60 * 1000)
    map_system = MEETING_MAP if run.template == "meeting" else LECTURE_MAP
    reduce_system = MEETING_REDUCE if run.template == "meeting" else LECTURE_REDUCE
    validate_map = validate_meeting_map if run.template == "meeting" else validate_lecture_map
    validate_reduce = validate_meeting_reduce if run.template == "meeting" else validate_lecture_reduce
    maps: list[dict] = []
    for index, shard in enumerate(shards):
        existing = db.get(LlmMapShard, (run.id, index))
        if existing is not None and existing.status == "done" and isinstance(existing.result, dict):
            maps.append(existing.result)
            continue
        row = existing or LlmMapShard(
            run_id=run.id,
            shard_index=index,
            input_start_ms=shard[0].start_ms,
            input_end_ms=shard[-1].end_ms,
            status="running",
        )
        if existing is None:
            db.add(row)
        visible = []
        for segment in shard:
            text = segment.text_edited if segment.text_edited is not None else segment.text_cleaned
            if text is None:
                text = segment.text_raw
            visible.append(f"[{clock(segment.start_ms)}] {text}")
        messages = [
            {"role": "system", "content": map_system},
            {"role": "user", "content": _user_preamble(job.vocabulary) + "\n".join(visible)},
        ]
        try:
            data = _ask(caller, messages, validate_map)
        except LlmTimeout:
            row.status = "failed"
            _fail(db, run, "llm_timeout", "LLM hết hạn.")
            return
        except LlmUpstream:
            row.status = "failed"
            _fail(db, run, "llm_upstream", "Không gọi được LLM.")
            return
        except SchemaError as exc:
            row.status = "failed"
            _fail(db, run, "llm_invalid_json", str(exc))
            return
        row.status = "done"
        row.result = data
        db.commit()
        maps.append(data)
    messages = [
        {"role": "system", "content": reduce_system},
        {"role": "user", "content": _user_preamble(job.vocabulary) + json.dumps(maps, ensure_ascii=False)},
    ]
    try:
        reduced = _ask(caller, messages, validate_reduce)
    except LlmTimeout:
        _fail(db, run, "llm_timeout", "LLM hết hạn.")
        return
    except LlmUpstream:
        _fail(db, run, "llm_upstream", "Không gọi được LLM.")
        return
    except SchemaError as exc:
        _fail(db, run, "llm_invalid_json", str(exc))
        return
    run.status = "done"
    run.result = reduced
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
