"""Pipeline bản chuẩn: chunk, nhận dạng, khử chồng, gán người nói."""

import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import ActionItem, Highlight, Job, JobEvent, Segment, SpeakerAlias, VoiceProfile, Word
from app.services.diarization import PIPELINE_MODEL
from app.services.job_notify import install_job_notify, remember_job_event
from app.services.sentence_merge import should_merge
from app.services.speaker_align import (
    SpeakerTurn,
    VoiceProfileVector,
    WordSpan,
    label_for_segment,
    label_for_word,
    match_speakers,
    split_by_speaker,
    unpack_embedding,
)
from app.services.vad_chunker import SpeechChunk, SpeechSlice, TimedWord, build_chunks, fill_empty_spans, keep_word

logger = logging.getLogger(__name__)


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
) -> tuple[list[tuple[Segment, list[Word]]], dict[uuid.UUID, str | None]]:
    """Ghi nhãn từ, tách câu tại chỗ đổi người nói, rồi ghi nhãn câu.

    Từ và câu ghi bằng lệnh cập nhật hàng loạt theo khóa chính. Trả danh sách câu sau khi tách
    và nhãn của từng câu. Câu tách ra có id mới, nên bước này phải xong trước sự kiện `speakers`.
    """
    word_rows: list[dict] = []
    pieces: list[tuple[Segment, list[Word], int, int, str | None]] = []
    for segment, words in written_segments:
        spans = []
        for word in words:
            label = label_for_word(word.start_ms, word.end_ms, turns)
            word_rows.append({"id": word.id, "speaker_label": label})
            spans.append(WordSpan(word.start_ms, word.end_ms, label))
        runs = split_by_speaker(spans) or [(0, len(words), label_for_segment(spans))]
        for start, end, label in runs:
            pieces.append((segment, words, start, end, label))
    db.flush()
    if word_rows:
        db.execute(update(Word), word_rows)

    split = len(pieces) != len(written_segments)
    if split:
        # Dời vị trí cũ sang số âm trước, để chèn câu mới không chạm ràng buộc (job, pass, position).
        for index, (segment, _words) in enumerate(written_segments):
            segment.position = -(index + 1)
        db.flush()

    result: list[tuple[Segment, list[Word]]] = []
    labels: dict[uuid.UUID, str | None] = {}
    moved: list[dict] = []
    for segment, words, start, end, label in pieces:
        part = words[start:end]
        if start == 0:
            target = segment
            if end < len(words):
                segment.text_raw = " ".join(word.text for word in part)
                segment.end_ms = part[-1].end_ms
        else:
            target = Segment(
                job_id=segment.job_id,
                pass_index=segment.pass_index,
                position=-(len(written_segments) + len(result) + 1),
                start_ms=part[0].start_ms,
                end_ms=part[-1].end_ms,
                text_raw=" ".join(word.text for word in part),
            )
            db.add(target)
            db.flush()
            moved.extend(
                {"id": word.id, "segment_id": target.id, "position": index} for index, word in enumerate(part)
            )
        target.speaker_label = label
        labels[target.id] = label
        result.append((target, list(part)))
    if moved:
        db.execute(update(Word), moved)
    if split:
        for index, (segment, _words) in enumerate(result):
            segment.position = index
    db.flush()
    return result, labels


def _merge_sentences(
    db: Session,
    written_segments: list[tuple[Segment, list[Word]]],
    labels: dict[uuid.UUID, str | None],
) -> None:
    """Gom các đoạn Whisper cắt giữa câu. Chạy sau khi có nhãn để không gộp qua hai người nói."""
    if not written_segments:
        return
    merged = [written_segments[0]]
    dropped: list[uuid.UUID] = []
    moved: list[dict] = []
    for segment, words in written_segments[1:]:
        head, head_words = merged[-1]
        if not should_merge(
            head.text_raw,
            head.start_ms,
            head.end_ms,
            labels.get(head.id),
            segment.text_raw,
            segment.start_ms,
            segment.end_ms,
            labels.get(segment.id),
        ):
            merged.append((segment, words))
            continue
        head.text_raw = f"{head.text_raw} {segment.text_raw}"
        head.end_ms = segment.end_ms
        for word in words:
            moved.append({"id": word.id, "segment_id": head.id, "position": len(head_words)})
            head_words.append(word)
        dropped.append(segment.id)
    if not dropped:
        return
    db.flush()
    if moved:
        db.execute(update(Word), moved)
    # Khóa ngoại của words có cascade, nên phải dời từ xong rồi mới xóa câu.
    db.execute(delete(Segment).where(Segment.id.in_(dropped)))


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


def _enter_preprocessing(db: Session, job: Job) -> None:
    job.status = "preprocessing"
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    _append_event(db, job, "stage", {"stage": "preprocessing", "detail": "Chuẩn hóa âm thanh"})
    db.commit()


@dataclass(frozen=True)
class ChunkPlan:
    """Chunk của job và chỗ chạy tiếp. Lưu ra đĩa khi job nhường GPU giữa chừng."""

    chunks: list[SpeechChunk]
    next_index: int
    position: int
    yields: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "chunks": [
                    {
                        "start": chunk.start,
                        "end": chunk.end,
                        "slices": [[piece.start, piece.end, piece.forced] for piece in chunk.slices],
                    }
                    for chunk in self.chunks
                ],
                "next_index": self.next_index,
                "position": self.position,
                "yields": self.yields,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> "ChunkPlan":
        data = json.loads(text)
        chunks = [
            SpeechChunk(
                float(item["start"]),
                float(item["end"]),
                tuple(SpeechSlice(float(start), float(end), bool(forced)) for start, end, forced in item["slices"]),
            )
            for item in data["chunks"]
        ]
        return cls(chunks, int(data["next_index"]), int(data["position"]), int(data.get("yields", 0)))


def _plan_path(root: Path, job_id) -> Path:
    return root / "tmp" / f"{job_id}.plan.json"


def _load_written(db: Session, job: Job) -> list[tuple[Segment, list[Word]]]:
    """Câu và từ của pass 2 đã ghi trước lúc nhường GPU, theo đúng thứ tự."""
    segments = (
        db.query(Segment).filter(Segment.job_id == job.id, Segment.pass_index == 2).order_by(Segment.position).all()
    )
    words: dict[uuid.UUID, list[Word]] = {segment.id: [] for segment in segments}
    if segments:
        rows = db.query(Word).filter(Word.segment_id.in_(list(words))).order_by(Word.segment_id, Word.position)
        for word in rows:
            words[word.segment_id].append(word)
    return [(segment, words[segment.id]) for segment in segments]


def run_standard_pass(
    db: Session,
    job: Job,
    *,
    regions: list[tuple[float, float]],
    transcribe,
    diarize=None,
    plan: ChunkPlan | None = None,
    should_yield=None,
) -> ChunkPlan | None:
    """transcribe(chunk) trả các câu có start/end và words, tính bằng giây tương đối trong chunk.

    Có `plan` thì chạy tiếp từ chunk chưa ghi. `should_yield()` trả True thì dừng trước chunk kế,
    sau ít nhất một chunk của lượt này, và trả ChunkPlan để lượt sau chạy tiếp.
    """
    if job.status == "cancelled":
        return None
    if plan is None:
        if job.status != "preprocessing":
            _enter_preprocessing(db, job)
        chunks = build_chunks(regions)
        start_index, position = 0, 0
        written_segments: list[tuple[Segment, list[Word]]] = []
    else:
        chunks, start_index, position = plan.chunks, plan.next_index, plan.position
        written_segments = _load_written(db, job)

    if not chunks:
        job.status = "ready"
        job.finished_at = datetime.now(timezone.utc)
        _append_event(db, job, "done", {})
        db.commit()
        return None

    job.status = "transcribing"
    detail = "Nhận dạng tiếp" if plan is not None else "Nhận dạng"
    _append_event(db, job, "stage", {"stage": "transcribing", "detail": detail})
    db.commit()

    recent: list[int] = []
    for index in range(start_index, len(chunks)):
        chunk = chunks[index]
        fresh = db.get(Job, job.id)
        if fresh is None or fresh.status == "cancelled":
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return None
        if index > start_index and should_yield is not None and should_yield():
            _append_event(
                db, job, "stage", {"stage": "transcribing", "detail": "Tạm nhường GPU cho phiên ghi trực tiếp"}
            )
            db.commit()
            return ChunkPlan(chunks, index, position, plan.yields if plan is not None else 0)
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
    labels: dict[uuid.UUID, str | None] = {}
    if turns:
        written_segments, labels = _write_speaker_labels(db, written_segments, turns)
    _merge_sentences(db, written_segments, labels)
    if turns:
        _apply_voice_aliases(db, job, vectors)
        _append_event(db, job, "speakers", {})
    job.status = "ready"
    job.finished_at = datetime.now(timezone.utc)
    _append_event(db, job, "done", {})
    db.commit()


def run_upload_job(job_id: str, *, engine_factory=None, diarize_fn=None, regions_fn=None) -> str:
    """Điểm vào của worker. Trả retry khi chưa giữ được gpu:lock."""
    from app.services.gpu_lock import get_gpu_lock

    from app.services.gpu_lock import keeper

    from app.services.gpu_lock import gpu_wanted, hand_over

    lock = get_gpu_lock()
    if not lock.acquire(str(job_id)):
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(str(job_id)))
            if job is None or job.status == "cancelled":
                _drop_yield_files(str(job_id))
                return "done"
        return "retry"
    keeper.start(str(job_id))
    try:
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(str(job_id)))
            if job is None or job.status not in _RUNNABLE:
                _drop_yield_files(str(job_id))
                return "done"
            outcome = _process_upload(
                db,
                job,
                engine_factory or _whisper_engine,
                diarize_fn or _real_diarize,
                regions_fn,
                should_yield=lambda: gpu_wanted() is not None,
            )
        if outcome == "yielded":
            keeper.stop(str(job_id))
            requester = gpu_wanted()
            # Trao khóa thẳng cho người xin, để job khác trên hàng không chen vào giữa.
            if requester is not None:
                hand_over(str(job_id), requester)
            return "retry"
        return "done"
    finally:
        keeper.stop(str(job_id))
        lock.release(str(job_id))


def _drop_yield_files(job_id: str) -> None:
    root = Path(get_settings().data_dir).resolve()
    _plan_path(root, job_id).unlink(missing_ok=True)
    (root / "tmp" / f"{job_id}.f32").unlink(missing_ok=True)


_RUNNABLE = {"queued", "preprocessing", "transcribing", "diarizing"}


def clear_pass(db: Session, job_id: uuid.UUID, pass_index: int) -> None:
    """Xóa câu, từ, và đánh dấu của một pass. Việc manual giữ lại với segment_id null."""
    segment_ids = list(
        db.scalars(select(Segment.id).where(Segment.job_id == job_id, Segment.pass_index == pass_index)).all()
    )
    if not segment_ids:
        return
    db.query(Highlight).filter(Highlight.segment_id.in_(segment_ids)).delete(synchronize_session=False)
    db.query(Word).filter(Word.segment_id.in_(segment_ids)).delete(synchronize_session=False)
    db.query(ActionItem).filter(ActionItem.segment_id.in_(segment_ids)).update(
        {ActionItem.segment_id: None},
        synchronize_session=False,
    )
    db.query(Segment).filter(Segment.id.in_(segment_ids)).delete(synchronize_session=False)


def _whisper_engine():
    from app.services.stt_engine import WhisperEngine

    return WhisperEngine()


def _real_diarize(pcm, num_speakers):
    from app.services.diarization import diarize

    return diarize(pcm, num_speakers)


def _real_regions(pcm):
    from app.services.stt_engine import add_loud_gaps, speech_regions

    return add_loud_gaps(pcm, speech_regions(pcm))


def _upload_source(root: Path, job: Job) -> Path | None:
    """File gốc trong /data/tmp/{job_id}/. Không còn thì dùng Opus canonical, ví dụ khi chạy lại."""
    folder = root / "tmp" / str(job.id)
    if folder.is_dir():
        sources = sorted(path for path in folder.glob("source.*") if path.is_file())
        if sources:
            return sources[0]
    opus = root / "audio" / f"{job.id}.opus"
    return opus if opus.is_file() else None


def _fail(db: Session, job: Job, code: str, message: str) -> None:
    db.rollback()
    db.refresh(job)
    if job.status == "cancelled":
        return
    job.status = "failed"
    job.error_code = code
    job.error_message = message
    job.finished_at = datetime.now(timezone.utc)
    _append_event(db, job, "error", {"code": code, "message": message})
    db.commit()


def transcribe_stored_audio(db: Session, job: Job, *, engine_factory=None, diarize_fn=None, regions_fn=None) -> None:
    """Pass 2 trên Opus canonical của job. Phiên nghe gọi hàm này khi đang giữ gpu:lock."""
    _process_upload(db, job, engine_factory or _whisper_engine, diarize_fn or _real_diarize, regions_fn)


def _take_plan(root: Path, job: Job, pcm_path: Path) -> ChunkPlan | None:
    """Kế hoạch chunk job để lại khi nhường GPU. Đọc xong thì xóa file, nên nếu lượt chạy tiếp
    chết giữa chừng thì lần giao lại chạy từ đầu như cũ, không ghi lặp chunk."""
    path = _plan_path(root, job.id)
    if not path.is_file():
        return None
    try:
        plan = ChunkPlan.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Job %s: không đọc được kế hoạch chunk, chạy lại từ đầu.", job.id, exc_info=True)
        plan = None
    path.unlink(missing_ok=True)
    if plan is None or job.status != "transcribing" or not pcm_path.is_file():
        return None
    return plan


# Mỗi job nhường GPU tối đa chừng này lần, để việc mở phiên liên tục không làm job đứng mãi.
MAX_YIELDS = 3


def _process_upload(db: Session, job: Job, engine_factory, diarize_fn, regions_fn, should_yield=None) -> str:
    """Trả "yielded" khi job nhường GPU giữa chừng, "done" trong mọi trường hợp còn lại."""
    from app.services.audio_processor import MediaError, close_pcm, load_pcm, normalize, slice_pcm
    from app.services.stt_engine import GpuOutOfMemory

    settings = get_settings()
    root = Path(settings.data_dir).resolve()
    job_id = job.id
    pcm_path = root / "tmp" / f"{job_id}.f32"
    engine = None
    pcm = None
    yielded = False
    try:
        plan = _take_plan(root, job, pcm_path) if should_yield is not None else None
        yields_so_far = plan.yields if plan is not None else 0
        if should_yield is not None and yields_so_far >= MAX_YIELDS:
            should_yield = None
        if plan is None:
            if job.status != "queued":
                # Celery giao lại sau khi worker chết giữa job: xóa pass 2 dở rồi chạy lại.
                clear_pass(db, job.id, 2)
                db.commit()
            _enter_preprocessing(db, job)
            source = _upload_source(root, job)
            if source is None:
                raise MediaError("unsupported_media", "Không còn file âm thanh của job.")
            audio = normalize(source, root / "audio" / f"{job.id}.opus", pcm_path, settings.max_duration_seconds)
            job.audio_path = str(audio.opus_path)
            job.duration_ms = audio.duration_ms
            db.commit()
            if source.parent.name == str(job.id):
                shutil.rmtree(source.parent, ignore_errors=True)

        pcm = load_pcm(pcm_path)
        regions = (regions_fn or _real_regions)(pcm) if plan is None else []

        def transcribe_span(chunk):
            nonlocal engine
            if engine is None:
                engine = engine_factory()
            return engine.transcribe(slice_pcm(pcm, chunk.start, chunk.end), job.vocabulary)

        def transcribe_greedy(chunk):
            return engine.transcribe(slice_pcm(pcm, chunk.start, chunk.end), job.vocabulary, greedy=True)

        def transcribe(chunk):
            return fill_empty_spans(chunk, transcribe_span(chunk), transcribe_span, transcribe_greedy)

        def diarize():
            nonlocal engine
            if engine is not None:
                engine.release()
                engine = None
            return diarize_fn(pcm, job.num_speakers)

        left = run_standard_pass(
            db, job, regions=regions, transcribe=transcribe, diarize=diarize, plan=plan, should_yield=should_yield
        )
        if left is not None:
            # Giữ PCM và kế hoạch chunk để lượt sau chạy tiếp mà không chuẩn hóa lại.
            left = replace(left, yields=yields_so_far + 1)
            _plan_path(root, job_id).write_text(left.to_json(), encoding="utf-8")
            yielded = True
            logger.info("Job %s nhường GPU ở chunk %s/%s.", job_id, left.next_index, len(left.chunks))
    except MediaError as error:
        _fail(db, job, error.code, error.message)
    except GpuOutOfMemory:
        _fail(db, job, "gpu_oom", "Không đủ VRAM để nạp model nhận dạng.")
    except Exception:
        logger.exception("Job %s lỗi khi nhận dạng.", job_id)
        _fail(db, job, "worker_failed", "Worker gặp lỗi khi nhận dạng.")
    finally:
        if engine is not None:
            engine.release()
        close_pcm(pcm)
        if not yielded:
            pcm_path.unlink(missing_ok=True)
    return "yielded" if yielded else "done"
