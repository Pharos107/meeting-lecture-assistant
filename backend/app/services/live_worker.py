"""Tác vụ của phiên nghe: vòng nháp pass 1, rồi pass 2 trên Opus đã thu. Kiến trúc mục 3.2 và 3.3."""

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import Job, LiveSession, Segment
from app.services.audio_processor import SAMPLE_RATE, MediaError, encode_live_pcm
from app.services.gpu_lock import get_gpu_lock, keeper
from app.services.live_channel import (
    clear_open_draft,
    close_session,
    publish_live,
    put_open_draft,
    unlink_pcm,
)
from app.services.live_heartbeat import age, clear_worker, mark_worker

logger = logging.getLogger(__name__)

POLL_S = 0.2
STATUS_EVERY_S = 1.0
WINDOW_S = 10.0
PARTIAL_EVERY_S = 2.0
CLOSE_SILENCE_S = 0.6
SOFT_CUT_S = 6.0
HARD_CUT_S = 8.0
MIN_CUT_GAP_S = 0.2
# Audio chờ nhận dạng quá mức này thì bỏ bản giữa chừng, chỉ nhận dạng lúc câu đóng.
DEGRADE_BACKLOG_S = 5.0
RECOVER_BACKLOG_S = 1.0
HEARTBEAT_LOST_S = 30.0
FIRST_HEARTBEAT_S = 60.0
# Mỗi lần đọc tối đa chừng này audio, để lần giao lại đọc phần PCM dài mà bộ nhớ không phình.
MAX_READ_S = 30.0
BYTES_PER_SAMPLE = 2

_RUNNABLE = {"preprocessing", "transcribing", "diarizing"}


def _seconds(samples: int) -> float:
    return samples / SAMPLE_RATE


def _samples(seconds: float) -> int:
    return int(round(seconds * SAMPLE_RATE))


class DraftTracker:
    """Luật câu nháp trên audio tới dần. Mốc tính bằng chỉ số mẫu từ đầu file PCM.

    `speech(audio)` trả vùng có tiếng tính bằng giây trong `audio`. `transcribe(audio)` trả chữ.
    `emit(segment_id, start, end, text, stable)` nhận mốc bằng chỉ số mẫu.
    """

    def __init__(self, *, speech, transcribe, emit, start_sample: int = 0) -> None:
        self.speech = speech
        self.transcribe = transcribe
        self.emit = emit
        self.audio = np.zeros(0, dtype=np.float32)
        self.base = start_sample
        self.scan_from = start_sample
        self.open_start: int | None = None
        self.open_id = ""
        self.partial_speech = 0.0
        self.degraded = False

    @property
    def total(self) -> int:
        return self.base + len(self.audio)

    def feed(self, samples: np.ndarray) -> None:
        if len(samples):
            self.audio = np.concatenate([self.audio, np.asarray(samples, dtype=np.float32)])

    def _cut(self, start: int, end: int) -> np.ndarray:
        return self.audio[start - self.base : end - self.base]

    def _stamps(self, start: int, end: int) -> list[tuple[int, int]]:
        if end <= start:
            return []
        return [(start + _samples(a), start + _samples(b)) for a, b in self.speech(self._cut(start, end))]

    def _decide(self, start: int, stamps: list[tuple[int, int]]) -> int | None:
        """Điểm đóng câu đang mở, hoặc None khi câu còn tiếp."""
        horizon = min(self.total, start + _samples(HARD_CUT_S))
        gaps = [(a[1], b[0]) for a, b in zip(stamps, stamps[1:])]
        gaps.append((stamps[-1][1], self.total))
        for gap_start, gap_end in gaps:
            if gap_start < horizon and _seconds(gap_end - gap_start) >= CLOSE_SILENCE_S:
                return gap_start
        if self.total - start < _samples(HARD_CUT_S):
            return None
        soft, hard = start + _samples(SOFT_CUT_S), start + _samples(HARD_CUT_S)
        best: tuple[int, int] | None = None
        for gap_start, gap_end in gaps:
            low, high = max(gap_start, soft), min(gap_end, hard)
            if _seconds(high - low) >= MIN_CUT_GAP_S and (best is None or high - low > best[1] - best[0]):
                best = (low, high)
        return (best[0] + best[1]) // 2 if best is not None else hard

    def _close(self, start: int, end: int) -> None:
        text = self.transcribe(self._cut(start, end)).strip() if end > start else ""
        self.emit(self.open_id, start, end, text, True)
        self.open_start = None
        self.scan_from = end
        self.partial_speech = 0.0

    def _drop(self) -> None:
        """Câu mở không còn tiếng. Đã phát bản giữa chừng thì phát bản chốt rỗng để client gỡ bong bóng."""
        if self.partial_speech > 0 and self.open_start is not None:
            self.emit(self.open_id, self.open_start, self.open_start, "", True)
        self.open_start = None
        self.scan_from = self.total
        self.partial_speech = 0.0

    def step(self, final: bool = False) -> None:
        while True:
            if self.open_start is None:
                start = max(self.scan_from, self.total - _samples(WINDOW_S))
                found = self._stamps(start, self.total)
                if not found:
                    break
                self.open_start = found[0][0]
                self.open_id = str(uuid.uuid4())
            start = self.open_start
            stamps = self._stamps(start, self.total)
            if not stamps:
                if final or self.total - start >= _samples(CLOSE_SILENCE_S):
                    self._drop()
                    continue
                break
            cut = self._decide(start, stamps)
            if cut is None and final:
                cut = stamps[-1][1]
            if cut is None:
                speech_s = sum(_seconds(b - a) for a, b in stamps)
                if not self.degraded and speech_s - self.partial_speech >= PARTIAL_EVERY_S:
                    text = self.transcribe(self._cut(start, self.total)).strip()
                    self.emit(self.open_id, start, self.total, text, False)
                    self.partial_speech = speech_s
                break
            self._close(start, cut)
        self._trim()

    def _trim(self) -> None:
        keep = self.open_start if self.open_start is not None else max(self.scan_from, self.total - _samples(WINDOW_S))
        drop = keep - self.base
        if drop > 0:
            self.audio = self.audio[drop:]
            self.base = keep


class _WorkerMark:
    """Ghi dấu worker còn sống mỗi 10 giây, kể cả trong lúc pass 2 chạy lâu."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"live-mark-{session_id[:8]}", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(10):
            try:
                mark_worker(self.session_id)
            except Exception:
                logger.warning("Không ghi được dấu worker của phiên %s", self.session_id)

    def __enter__(self) -> "_WorkerMark":
        mark_worker(self.session_id)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        try:
            clear_worker(self.session_id)
        except Exception:
            logger.warning("Không xóa được dấu worker của phiên %s", self.session_id)


class _PcmReader:
    """Đọc phần byte mới của file PCM s16le. Byte lẻ để lại tới lần đọc sau."""

    def __init__(self, path: Path, offset: int) -> None:
        self.path = path
        self.offset = offset

    def pending(self) -> int:
        try:
            size = self.path.stat().st_size
        except OSError:
            return 0
        return max(0, size - self.offset)

    def read(self, limit_bytes: int) -> np.ndarray:
        count = min(self.pending(), limit_bytes)
        count -= count % BYTES_PER_SAMPLE
        if count <= 0:
            return np.zeros(0, dtype=np.float32)
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            raw = handle.read(count)
        count = len(raw) - len(raw) % BYTES_PER_SAMPLE
        self.offset += count
        return np.frombuffer(raw[:count], dtype="<i2").astype(np.float32) / 32768.0


def _draft_engine():
    from app.services.stt_engine import DraftEngine

    return DraftEngine()


def _live_speech(audio: np.ndarray) -> list[tuple[float, float]]:
    from app.services.stt_engine import LIVE_VAD_PARAMETERS, speech_regions

    return speech_regions(audio, LIVE_VAD_PARAMETERS)


def _fail_session(db: Session, session: LiveSession, job: Job | None, code: str, message: str) -> None:
    from app.services.pipeline import _append_event

    session.status = "failed"
    session.ended_at = datetime.now(timezone.utc)
    if job is not None and job.status not in {"cancelled", "ready", "failed"}:
        job.status = "failed"
        job.error_code = code
        job.error_message = message
        job.finished_at = datetime.now(timezone.utc)
        _append_event(db, job, "error", {"code": code, "message": message})
    db.commit()
    close_session(str(session.id))
    publish_live(str(session.id), {"type": "error", "code": code, "message": message})


def _capture(
    session_id: uuid.UUID,
    job_id: uuid.UUID,
    pcm_path: Path,
    vocabulary: str | None,
    draft_factory,
    speech_fn,
    clock,
    sleep,
    handed: list,
) -> str:
    """Vòng nháp tới khi phiên dừng. Trả `stopped` hoặc `cancelled`.

    Phiên dừng bình thường mà bản nháp cùng model với bản chuẩn thì model được đưa vào `handed` cho pass 2.
    """
    sid = str(session_id)
    with Session(get_engine()) as db:
        position = int(
            db.scalar(select(func.count()).select_from(Segment).where(Segment.job_id == job_id, Segment.pass_index == 1))
            or 0
        )
        last_end = db.scalar(select(func.max(Segment.end_ms)).where(Segment.job_id == job_id, Segment.pass_index == 1))
    # Lần giao lại bắt đầu từ cuối câu pass 1 đã chốt, không nhận dạng lại phần trước đó.
    start_sample = _samples((last_end or 0) / 1000)
    reader = _PcmReader(pcm_path, start_sample * BYTES_PER_SAMPLE)
    draft = draft_factory()
    seq = 0

    def emit(segment_id: str, start: int, end: int, text: str, stable: bool) -> None:
        nonlocal seq, position
        seq += 1
        payload = {
            "type": "draft",
            "segment_id": segment_id,
            "start_ms": int(round(start * 1000 / SAMPLE_RATE)),
            "end_ms": int(round(end * 1000 / SAMPLE_RATE)),
            "text": text,
            "stable": stable,
            "seq": seq,
        }
        if stable:
            clear_open_draft(sid)
            if text:
                with Session(get_engine()) as db:
                    db.add(
                        Segment(
                            id=uuid.UUID(segment_id),
                            job_id=job_id,
                            pass_index=1,
                            position=position,
                            start_ms=payload["start_ms"],
                            end_ms=max(payload["end_ms"], payload["start_ms"]),
                            text_raw=text,
                        )
                    )
                    db.commit()
                position += 1
        else:
            put_open_draft(sid, payload)
        publish_live(sid, payload)

    tracker = DraftTracker(
        speech=speech_fn,
        transcribe=lambda audio: draft.transcribe(audio, vocabulary),
        emit=emit,
        start_sample=start_sample,
    )
    limit = _samples(MAX_READ_S) * BYTES_PER_SAMPLE

    def pump(final: bool) -> None:
        while True:
            backlog_s = reader.pending() / BYTES_PER_SAMPLE / SAMPLE_RATE
            if not tracker.degraded and backlog_s > DEGRADE_BACKLOG_S:
                tracker.degraded = True
                publish_live(
                    sid,
                    {"type": "warning", "code": "draft_degraded", "message": "Bản nháp chậm, chỉ hiện câu khi câu kết thúc."},
                )
            elif tracker.degraded and backlog_s < RECOVER_BACKLOG_S:
                tracker.degraded = False
            fresh = reader.read(limit)
            tracker.feed(fresh)
            more = reader.pending() >= BYTES_PER_SAMPLE
            tracker.step(final=final and not more)
            if not more or not len(fresh):
                return

    started = clock()
    checked = -STATUS_EVERY_S
    outcome = "stopped"
    finished = False
    try:
        while True:
            pump(final=False)
            now = clock()
            if now - checked >= STATUS_EVERY_S:
                checked = now
                with Session(get_engine()) as db:
                    session = db.get(LiveSession, session_id)
                    job = db.get(Job, job_id)
                    if session is None or job is None or session.status == "failed" or job.status == "cancelled":
                        outcome = "cancelled"
                        break
                    if session.status != "capturing":
                        break
                    quiet = age(sid)
                    if (quiet is None and now - started >= FIRST_HEARTBEAT_S) or (quiet is not None and quiet > HEARTBEAT_LOST_S):
                        # Hết 30 giây không có socket nối lại: dừng như khi bấm dừng.
                        session.status = "stopping"
                        db.commit()
                        break
            sleep(POLL_S)
        # Chặn mọi socket còn ghi, rồi đọc nốt phần PCM đã có.
        close_session(sid)
        if outcome == "stopped":
            pump(final=True)
        finished = True
        return outcome
    finally:
        hand_over = getattr(draft, "hand_over", None)
        engine = hand_over() if finished and outcome == "stopped" and hand_over is not None else None
        if engine is not None:
            handed.append(engine)
        else:
            draft.release()


def run_live_session(
    session_id: str,
    *,
    draft_factory=None,
    speech_fn=None,
    engine_factory=None,
    diarize_fn=None,
    regions_fn=None,
    clock=time.monotonic,
    sleep=time.sleep,
) -> None:
    from app.services.pipeline import _append_event, transcribe_stored_audio
    from app.services.stt_engine import GpuOutOfMemory

    sid = str(session_id)
    parsed = uuid.UUID(sid)
    with Session(get_engine()) as db:
        session = db.get(LiveSession, parsed)
        if session is None or session.job_id is None:
            return
        job = db.get(Job, session.job_id)
        if job is None or session.status == "failed":
            return
        if session.status == "finalized" and job.status not in _RUNNABLE:
            return
        lock = get_gpu_lock()
        if not lock.refresh(sid) and not lock.acquire(sid):
            _fail_session(db, session, job, "gpu_busy", "GPU đang bận với một phiên khác.")
            return
        job_id = job.id
        status = session.status
        vocabulary = session.vocabulary
        pcm_path = Path(session.pcm_path) if session.pcm_path else Path(get_settings().data_dir) / "tmp" / f"{sid}.pcm"

    keeper.start(sid)
    handed: list = []
    try:
        with _WorkerMark(sid):
            if status in {"capturing", "stopping"}:
                try:
                    outcome = _capture(
                        parsed,
                        job_id,
                        pcm_path,
                        vocabulary,
                        draft_factory or _draft_engine,
                        speech_fn or _live_speech,
                        clock,
                        sleep,
                        handed,
                    )
                except GpuOutOfMemory:
                    with Session(get_engine()) as db:
                        _fail_session(db, db.get(LiveSession, parsed), db.get(Job, job_id), "gpu_oom", "Không đủ VRAM để nạp model nháp.")
                    unlink_pcm(str(pcm_path))
                    return
                if outcome == "cancelled":
                    unlink_pcm(str(pcm_path))
                    return
                opus = Path(get_settings().data_dir).resolve() / "audio" / f"{job_id}.opus"
                with Session(get_engine()) as db:
                    session = db.get(LiveSession, parsed)
                    job = db.get(Job, job_id)
                    if session is None or job is None or job.status == "cancelled":
                        unlink_pcm(str(pcm_path))
                        return
                    has_audio = pcm_path.is_file() and pcm_path.stat().st_size >= BYTES_PER_SAMPLE
                    try:
                        if has_audio:
                            encode_live_pcm(pcm_path, opus)
                    except MediaError as error:
                        _fail_session(db, session, job, error.code, error.message)
                        return
                    session.status = "finalized"
                    session.ended_at = datetime.now(timezone.utc)
                    if not has_audio:
                        job.status = "failed"
                        job.error_code = "unsupported_media"
                        job.error_message = "Phiên nghe không có âm thanh."
                        job.finished_at = datetime.now(timezone.utc)
                        _append_event(db, job, "error", {"code": job.error_code, "message": job.error_message})
                        db.commit()
                        return
                    job.status = "preprocessing"
                    db.commit()
                unlink_pcm(str(pcm_path))
            with Session(get_engine()) as db:
                job = db.get(Job, job_id)
                if job is None or job.status not in _RUNNABLE:
                    return
                factory = engine_factory
                if factory is None and handed:
                    # Pass 2 dùng lại model của bản nháp, không phải nhả rồi nạp lại turbo.
                    factory = handed.pop
                transcribe_stored_audio(db, job, engine_factory=factory, diarize_fn=diarize_fn, regions_fn=regions_fn)
    finally:
        for engine in handed:
            engine.release()
        keeper.stop(sid)
        get_gpu_lock().release(sid)
