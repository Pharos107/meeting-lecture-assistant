"""Vòng nháp PT2 và bàn giao sang pass 2, với VAD, Whisper và pyannote giả."""

import os
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "t" * 32)
os.environ["REDIS_URL"] = ""

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import Base, Job, LiveSession, Segment, User
from app.services.gpu_lock import _memory, keeper
from app.services.live_channel import LiveFeed, reset_live_channel
from app.services.live_heartbeat import clear_heartbeats, mark_worker, worker_alive
from app.services.live_worker import DraftTracker, run_live_session
from app.services.speaker_align import SpeakerTurn

SR = 16000
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
DATA_DIR = tempfile.mkdtemp(prefix="stt-live-")


def pattern(*parts: tuple[float, bool]) -> np.ndarray:
    """Audio giả: đoạn `True` là tiếng (biên độ 0,5), `False` là lặng."""
    return np.concatenate([np.full(int(round(seconds * SR)), 0.5 if loud else 0.0, dtype=np.float32) for seconds, loud in parts])


def fake_speech(audio: np.ndarray) -> list[tuple[float, float]]:
    """Vùng có tiếng là các mẫu khác 0, tách ở khoảng lặng từ 200 ms."""
    loud = np.abs(audio) > 0.1
    regions: list[list[int]] = []
    index = 0
    while index < len(loud):
        if not loud[index]:
            index += 1
            continue
        start = index
        while index < len(loud) and loud[index]:
            index += 1
        if regions and start - regions[-1][1] < 0.2 * SR:
            regions[-1][1] = index
        else:
            regions.append([start, index])
    return [(start / SR, end / SR) for start, end in regions]


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, float, float, str, bool]] = []

    def __call__(self, segment_id: str, start: int, end: int, text: str, stable: bool) -> None:
        self.events.append((segment_id, round(start / SR, 2), round(end / SR, 2), text, stable))

    def stable(self) -> list[tuple[float, float]]:
        return [(start, end) for _, start, end, text, stable in self.events if stable and text]


def tracker(recorder: Recorder) -> DraftTracker:
    return DraftTracker(speech=fake_speech, transcribe=lambda audio: f"{len(audio) / SR:.1f}s", emit=recorder)


def stream(draft: DraftTracker, audio: np.ndarray, frame_s: float = 0.2) -> None:
    step = int(frame_s * SR)
    for offset in range(0, len(audio), step):
        draft.feed(audio[offset : offset + step])
        draft.step()


class DraftTrackerTests(unittest.TestCase):
    def test_partial_every_two_seconds_then_close_on_silence(self) -> None:
        recorder = Recorder()
        draft = tracker(recorder)
        stream(draft, pattern((1, False), (3, True), (1, False)))
        partial = [event for event in recorder.events if not event[4]]
        self.assertEqual(len(partial), 1)
        self.assertEqual(recorder.stable(), [(1.0, 4.0)])
        self.assertEqual(recorder.events[-1][3], "3.0s")
        self.assertEqual(partial[0][0], recorder.events[-1][0])

    def test_continuous_speech_is_cut_at_eight_seconds(self) -> None:
        recorder = Recorder()
        draft = tracker(recorder)
        stream(draft, pattern((10, True), (1, False)))
        self.assertEqual(recorder.stable(), [(0.0, 8.0), (8.0, 10.0)])

    def test_cut_at_the_longest_pause_between_six_and_eight_seconds(self) -> None:
        recorder = Recorder()
        draft = tracker(recorder)
        stream(draft, pattern((6.4, True), (0.2, False), (0.4, True), (0.4, False), (2.6, True), (1, False)), frame_s=0.1)
        self.assertEqual(recorder.stable()[0], (0.0, 7.2))

    def test_stop_closes_the_open_sentence(self) -> None:
        recorder = Recorder()
        draft = tracker(recorder)
        stream(draft, pattern((0.5, False), (1.5, True)))
        self.assertEqual(recorder.stable(), [])
        draft.step(final=True)
        self.assertEqual(recorder.stable(), [(0.5, 2.0)])

    def test_degraded_skips_partials(self) -> None:
        recorder = Recorder()
        draft = tracker(recorder)
        draft.degraded = True
        stream(draft, pattern((5, True), (1, False)))
        self.assertTrue(all(event[4] for event in recorder.events))
        self.assertEqual(recorder.stable(), [(0.0, 5.0)])

    def test_buffer_stays_short(self) -> None:
        draft = tracker(Recorder())
        stream(draft, pattern(*[(3, True), (1, False)] * 20), frame_s=0.5)
        self.assertLessEqual(len(draft.audio), 10 * SR)
        self.assertEqual(draft.total, 80 * SR)


class FakeDraft:
    released = False

    def transcribe(self, audio, vocabulary):
        return f"nháp {len(audio) / SR:.1f}"

    def release(self) -> None:
        FakeDraft.released = True


class FakeEngine:
    released = 0

    def transcribe(self, audio, vocabulary):
        end = len(audio) / SR
        return [{"start": 0.0, "end": end, "text": "bản chuẩn", "words": [
            {"text": "bản", "start": 0.0, "end": end / 2}, {"text": "chuẩn", "start": end / 2, "end": end}]}]

    def release(self) -> None:
        FakeEngine.released += 1


class SharedDraft(FakeDraft):
    """Bản nháp cùng model với bản chuẩn: đưa model sang pass 2 thay vì nhả."""

    handed = 0

    def hand_over(self):
        SharedDraft.handed += 1
        return FakeEngine()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@unittest.skipUnless(HAS_FFMPEG, "Cần ffmpeg và ffprobe trên PATH.")
class LiveSessionTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["REDIS_URL"] = ""
        os.environ["DATA_DIR"] = DATA_DIR
        get_settings.cache_clear()
        Base.metadata.create_all(get_engine())
        reset_live_channel()
        clear_heartbeats()
        keeper.stop_all()
        _memory.owner = None
        _memory.deadline = 0.0
        FakeDraft.released = False

    def tearDown(self) -> None:
        keeper.stop_all()

    def _session(self, status: str = "capturing", audio: np.ndarray | None = None) -> tuple[uuid.UUID, uuid.UUID, Path]:
        session_id, job_id = uuid.uuid4(), uuid.uuid4()
        pcm = Path(DATA_DIR) / "tmp" / f"{session_id}.pcm"
        pcm.parent.mkdir(parents=True, exist_ok=True)
        if audio is not None:
            pcm.write_bytes((audio * 32767).astype("<i2").tobytes())
        now = datetime.now(timezone.utc)
        with Session(get_engine()) as db:
            user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x", display_name="An", created_at=now)
            db.add(user)
            db.flush()
            db.add(Job(id=job_id, user_id=user.id, title="buổi", source="live", status="capturing", warnings=[], created_at=now))
            db.add(LiveSession(id=session_id, user_id=user.id, job_id=job_id, title="buổi", status=status,
                               pcm_path=str(pcm), created_at=now))
            db.commit()
        _memory.acquire(str(session_id))
        return session_id, job_id, pcm

    def _run(self, session_id: uuid.UUID, clock: Clock | None = None, **overrides) -> None:
        clock = clock or Clock()
        options = {"draft_factory": FakeDraft, "engine_factory": FakeEngine}
        options.update(overrides)
        run_live_session(
            str(session_id),
            speech_fn=fake_speech,
            diarize_fn=lambda pcm, speakers: [SpeakerTurn(0, 60000, "SPEAKER_00")],
            regions_fn=lambda pcm: [(0.0, len(pcm) / SR)],
            clock=clock,
            sleep=clock.sleep,
            **options,
        )

    def test_stop_writes_pass_one_then_runs_pass_two(self) -> None:
        session_id, job_id, pcm = self._session("stopping", pattern((0.5, False), (2, True), (1, False), (1.5, True)))
        feed = LiveFeed()
        feed.start(str(session_id))
        try:
            self._run(session_id)
            drafts = [payload for payload in feed.drain() if payload["type"] == "draft"]
        finally:
            feed.close()
        with Session(get_engine()) as db:
            first = db.query(Segment).filter(Segment.job_id == job_id, Segment.pass_index == 1).order_by(Segment.position).all()
            self.assertEqual([(row.start_ms, row.end_ms) for row in first], [(500, 2500), (3500, 5000)])
            self.assertEqual([row.text_raw for row in first], ["nháp 2.0", "nháp 1.5"])
            self.assertEqual({str(row.id) for row in first}, {d["segment_id"] for d in drafts if d["stable"]})
            self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id, Segment.pass_index == 2).count(), 1)
            self.assertEqual(db.get(LiveSession, session_id).status, "finalized")
            job = db.get(Job, job_id)
            self.assertEqual(job.status, "ready")
            self.assertTrue(Path(job.audio_path).is_file())
        self.assertTrue(FakeDraft.released)
        self.assertFalse(pcm.exists())
        self.assertIsNone(_memory.owner)
        self.assertFalse(worker_alive(str(session_id)))

    def test_pass_two_reuses_the_draft_model(self) -> None:
        session_id, job_id, _pcm = self._session("stopping", pattern((2, True), (1, False)))
        SharedDraft.handed = 0
        FakeEngine.released = 0
        self._run(session_id, draft_factory=SharedDraft, engine_factory=None)
        self.assertEqual(SharedDraft.handed, 1)
        self.assertFalse(FakeDraft.released)
        self.assertEqual(FakeEngine.released, 1)
        with Session(get_engine()) as db:
            self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id, Segment.pass_index == 2).count(), 1)
            self.assertEqual(db.get(Job, job_id).status, "ready")

    def test_cancelled_session_releases_the_draft_model(self) -> None:
        session_id, job_id, _pcm = self._session("capturing", pattern((2, True), (1, False)))
        with Session(get_engine()) as db:
            db.get(Job, job_id).status = "cancelled"
            db.commit()
        SharedDraft.handed = 0
        self._run(session_id, draft_factory=SharedDraft, engine_factory=None)
        self.assertEqual(SharedDraft.handed, 0)
        self.assertTrue(FakeDraft.released)

    def test_no_socket_for_a_minute_stops_the_session(self) -> None:
        session_id, job_id, _pcm = self._session("capturing", pattern((1, True), (1, False)))
        clock = Clock()
        self._run(session_id, clock)
        self.assertGreaterEqual(clock.now, 60)
        with Session(get_engine()) as db:
            self.assertEqual(db.get(LiveSession, session_id).status, "finalized")
            self.assertEqual(db.get(Job, job_id).status, "ready")

    def test_cancel_skips_pass_two(self) -> None:
        session_id, job_id, pcm = self._session("capturing", pattern((2, True), (1, False)))
        with Session(get_engine()) as db:
            db.get(Job, job_id).status = "cancelled"
            db.commit()
        self._run(session_id)
        with Session(get_engine()) as db:
            self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id, Segment.pass_index == 2).count(), 0)
            self.assertEqual(db.get(Job, job_id).status, "cancelled")
        self.assertFalse(pcm.exists())
        self.assertIsNone(_memory.owner)

    def test_lock_of_another_owner_fails_the_session(self) -> None:
        session_id, job_id, _pcm = self._session("capturing", pattern((1, True)))
        _memory.owner = "job-khac"
        _memory.deadline = float("inf")
        self._run(session_id)
        with Session(get_engine()) as db:
            self.assertEqual(db.get(LiveSession, session_id).status, "failed")
            job = db.get(Job, job_id)
            self.assertEqual((job.status, job.error_code), ("failed", "gpu_busy"))
        self.assertEqual(_memory.owner, "job-khac")

    def test_empty_capture_fails_without_pass_two(self) -> None:
        session_id, job_id, _pcm = self._session("stopping")
        self._run(session_id)
        with Session(get_engine()) as db:
            self.assertEqual(db.get(LiveSession, session_id).status, "finalized")
            job = db.get(Job, job_id)
            self.assertEqual((job.status, job.error_code), ("failed", "unsupported_media"))

    def test_redelivery_after_finalize_reruns_pass_two_only(self) -> None:
        session_id, job_id, _pcm = self._session("stopping", pattern((2, True), (1, False)))
        self._run(session_id)
        with Session(get_engine()) as db:
            db.get(Job, job_id).status = "preprocessing"
            db.commit()
        FakeDraft.released = False
        _memory.acquire(str(session_id))
        self._run(session_id)
        self.assertFalse(FakeDraft.released)
        with Session(get_engine()) as db:
            self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id, Segment.pass_index == 1).count(), 1)
            self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id, Segment.pass_index == 2).count(), 1)
            self.assertEqual(db.get(Job, job_id).status, "ready")


class WorkerMarkTests(unittest.TestCase):
    def test_mark_expires_with_clear(self) -> None:
        os.environ["REDIS_URL"] = ""
        get_settings.cache_clear()
        clear_heartbeats()
        mark_worker("phien")
        self.assertTrue(worker_alive("phien"))
        clear_heartbeats()
        self.assertFalse(worker_alive("phien"))
