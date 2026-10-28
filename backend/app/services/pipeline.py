"""Pipeline bản chuẩn: chunk, nhận dạng, khử chồng, gán người nói."""

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import Job, JobEvent, Segment, SpeakerAlias, VoiceProfile, Word
from app.services.job_notify import install_job_notify, remember_job_event
from app.services.speaker_align import (
    SpeakerTurn,
    VoiceProfileVector,
    WordSpan,
    label_for_segment,
    label_for_word,
    match_speakers,
    unpack_embedding,
)
from app.services.vad_chunker import TimedWord, build_chunks, keep_word


def _diarize_payload(result):
    turns = result
    vectors: dict = {}
    device = None
    if isinstance(result, tuple):
        turns = result[0] if result else []
        if len(result) > 1 and isinstance(result[1], dict):
            vectors = result[1]
        if len(result) > 2 and result[2] in {"cuda", "cpu"}:
            device = result[2]
    return list(turns or []), vectors, device


def _write_chunk(db: Session, job: Job, chunk, produced, chunks, position: int):
    written: list[tuple[Segment, list[Word]]] = []
    event_segments: list[dict] = []
    chunk_index = chunks.index(chunk)
    for raw in produced:
        timed = [
            TimedWord(
                text=word["text"],
                start=chunk.start + float(word["start"]),
                end=chunk.start + float(word["end"]),
                chunk_index=chunk_index,
            )
            for word in raw.get("words") or []
        ]
        kept = [word for word in timed if keep_word(word, chunks)]
        text = " ".join(word.text for word in kept).strip()
        if not text and not timed:
            text = str(raw.get("text") or "").strip()
        if timed and not kept:
            continue
        if not text:
            continue
        start_s = kept[0].start if kept else chunk.start + float(raw.get("start", 0))
        end_s = kept[-1].end if kept else chunk.start + float(raw.get("end", 0))
        segment = Segment(
            job_id=job.id,
            pass_index=2,
            position=position,
            start_ms=int(round(start_s * 1000)),
            end_ms=int(round(end_s * 1000)),
            text_raw=text,
        )
        db.add(segment)
        db.flush()
        word_rows: list[Word] = []
        event_words = []
        for word_index, word in enumerate(kept):
            row = Word(
                segment_id=segment.id,
                position=word_index,
                text=word.text,
                start_ms=int(round(word.start * 1000)),
                end_ms=int(round(word.end * 1000)),
            )
            db.add(row)
            word_rows.append(row)
            event_words.append({"text": word.text, "start_ms": row.start_ms, "end_ms": row.end_ms})
        written.append((segment, word_rows))
        event_segments.append(
            {
                "id": str(segment.id),
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text_raw": text,
                "words": event_words,
            }
        )
        position += 1
    return position, written, event_segments


def _apply_voice_aliases(db: Session, job: Job, vectors: dict) -> None:
    from app.api.routes_voice import PIPELINE_MODEL

    settings = get_settings()
    rows = db.query(VoiceProfile).filter(VoiceProfile.user_id == job.user_id, VoiceProfile.status == "ready").all()
    profiles: list[VoiceProfileVector] = []
    names: dict[str, str] = {}
    for row in rows:
        if not row.embedding or not row.embedding_model:
            continue
        profiles.append(
            VoiceProfileVector(str(row.id), unpack_embedding(bytes(row.embedding)), row.embedding_model)
        )
        names[str(row.id)] = row.display_name
    mapping = match_speakers(
        {str(label): list(vector) for label, vector in vectors.items()},
        profiles,
        current_model=PIPELINE_MODEL,
        threshold=settings.voice_match_threshold,
        margin=settings.voice_match_margin,
    )
    aliases = db.query(SpeakerAlias).filter(SpeakerAlias.job_id == job.id).all()
    by_label = {row.speaker_label: row for row in aliases}
    for row in list(aliases):
        if row.source == "voice_profile" and mapping.get(row.speaker_label) is None:
            db.delete(row)
            by_label.pop(row.speaker_label, None)
    for label, profile_id in mapping.items():
        current = by_label.get(label)
        display = names.get(profile_id)
        if current is not None and current.source == "manual":
            continue
        if not display:
            continue
        if current is None:
            db.add(
                SpeakerAlias(
                    job_id=job.id,
                    speaker_label=label,
                    display_name=display,
                    source="voice_profile",
                )
            )
        else:
            current.display_name = display
            current.source = "voice_profile"


def _write_speaker_labels(
    db: Session,
    written_segments: list[tuple[Segment, list[Word]]],
    turns: list[SpeakerTurn],
) -> None:
    """Ghi nhãn từ và câu bằng hai lệnh cập nhật hàng loạt theo khóa chính."""
    word_rows: list[dict] = []
    segment_rows: list[dict] = []
    for segment, words in written_segments:
        spans = []
        for word in words:
            label = label_for_word(word.start_ms, word.end_ms, turns)
            word_rows.append({"id": word.id, "speaker_label": label})
            spans.append(WordSpan(word.start_ms, word.end_ms, label))
        segment_rows.append({"id": segment.id, "speaker_label": label_for_segment(spans)})
    db.flush()
    if word_rows:
        db.execute(update(Word), word_rows)
    if segment_rows:
        db.execute(update(Segment), segment_rows)


def _append_event(db: Session, job: Job, event_type: str, payload: dict) -> None:
    db.flush()
    seq = (db.scalar(select(func.max(JobEvent.seq)).where(JobEvent.job_id == job.id)) or 0) + 1
    payload = dict(payload)
    payload["seq"] = seq
    db.add(
        JobEvent(
            job_id=job.id,
            seq=seq,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
    )
    remember_job_event(db, str(job.id), seq)


install_job_notify()


def run_standard_pass(
    db: Session,
    job: Job,
    *,
    regions: list[tuple[float, float]],
    transcribe,
    diarize=None,
) -> None:
    """transcribe(chunk) trả các câu có start/end và words, tính bằng giây tương đối trong chunk."""
    if job.status == "cancelled":
        return
    job.status = "preprocessing"
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    _append_event(db, job, "stage", {"stage": "preprocessing", "detail": "Chuẩn hóa âm thanh"})
    db.commit()

    chunks = build_chunks(regions)
    if not chunks:
        job.status = "ready"
        job.finished_at = datetime.now(timezone.utc)
        _append_event(db, job, "done", {})
        db.commit()
        return

    job.status = "transcribing"
    _append_event(db, job, "stage", {"stage": "transcribing", "detail": "Nhận dạng"})
    db.commit()

    position = 0
    written_segments: list[tuple[Segment, list[Word]]] = []
    recent: list[int] = []
    for index, chunk in enumerate(chunks):
        fresh = db.get(Job, job.id)
        if fresh is None or fresh.status == "cancelled":
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        started = time.perf_counter()
        produced = transcribe(chunk)
        elapsed = max(int((time.perf_counter() - started) * 1000), 1)
        recent.append(elapsed)
        recent = recent[-3:]
        expected = int(round(sum(recent) / len(recent)))
        position, written, event_segments = _write_chunk(db, job, chunk, produced, chunks, position)
        written_segments.extend(written)
        _append_event(
            db,
            job,
            "chunk",
            {
                "chunk_index": index,
                "chunk_count": len(chunks),
                "processing_time_ms": elapsed,
                "expected_next_chunk_ms": expected,
                "segments": event_segments,
            },
        )
        db.commit()

    job.status = "diarizing"
    _append_event(db, job, "stage", {"stage": "diarizing", "detail": "Gán người nói"})
    db.commit()
    turns: list[SpeakerTurn] = []
    vectors: dict = {}
    if diarize is not None:
        try:
            turns, vectors, device = _diarize_payload(diarize())
            if device is not None:
                job.diarization_device = device
        except Exception:
            warnings = list(job.warnings or [])
            warnings.append({"code": "diarization_failed", "message": "Không gán được người nói."})
            job.warnings = warnings
            _append_event(db, job, "warning", {"code": "diarization_failed", "message": "Không gán được người nói."})
            turns = []
            vectors = {}
    if turns:
        _write_speaker_labels(db, written_segments, turns)
        _apply_voice_aliases(db, job, vectors)
        _append_event(db, job, "speakers", {})
    job.status = "ready"
    job.finished_at = datetime.now(timezone.utc)
    _append_event(db, job, "done", {})
    db.commit()


def run_upload_job(job_id: str) -> str:
    """Điểm vào của worker. Trả retry khi chưa giữ được gpu:lock."""
    from app.services.gpu_lock import get_gpu_lock

    from app.services.gpu_lock import keeper

    lock = get_gpu_lock()
    if not lock.acquire(str(job_id)):
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(str(job_id)))
            if job is None or job.status == "cancelled":
                return "done"
        return "retry"
    keeper.start(str(job_id))
    try:
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(str(job_id)))
            if job is None or job.status == "cancelled":
                return "done"
            job.status = "failed"
            job.error_code = "worker_failed"
            job.error_message = "Worker nhận dạng chưa được nối với model trên máy này."
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        return "done"
    finally:
        keeper.stop(str(job_id))
        lock.release(str(job_id))
