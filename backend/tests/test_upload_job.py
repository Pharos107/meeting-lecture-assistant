"""run_upload_job với FFmpeg thật, Whisper và pyannote giả."""

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "t" * 32)
os.environ["REDIS_URL"] = ""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import Base, Job, JobEvent, Segment, User, Word
from app.services import audio_processor
from app.services.pipeline import clear_pass, run_upload_job
from app.services.speaker_align import SpeakerTurn
from app.services.stt_engine import GpuOutOfMemory, is_hallucination, prompt_or_none

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
DATA_DIR = tempfile.mkdtemp(prefix="stt-upload-")


class FakeEngine:
    instances: list["FakeEngine"] = []

    def __init__(self) -> None:
        self.released = False
        self.calls = 0
        FakeEngine.instances.append(self)

    def transcribe(self, audio, vocabulary):
        self.calls += 1
        assert len(audio) > 0
        return [
            {
                "start": 0.1,
                "end": 1.0,
                "text": "xin chào",
                "words": [{"text": "xin", "start": 0.1, "end": 0.5}, {"text": "chào", "start": 0.5, "end": 1.0}],
            }
        ]

    def release(self) -> None:
        self.released = True


def fake_diarize(pcm, num_speakers):
    assert FakeEngine.instances and FakeEngine.instances[-1].released, "Whisper phải được nhả trước pyannote."
    return [SpeakerTurn(0, 5000, "SPEAKER_00")], {}, "cpu"


@unittest.skipUnless(HAS_FFMPEG, "Cần ffmpeg và ffprobe trên PATH.")
class UploadJobTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["REDIS_URL"] = ""
        os.environ["DATA_DIR"] = DATA_DIR
        os.environ["MAX_DURATION_SECONDS"] = "10800"
        get_settings.cache_clear()
        Base.metadata.create_all(get_engine())
        FakeEngine.instances.clear()
        self.root = Path(DATA_DIR)

    def tearDown(self) -> None:
        os.environ["MAX_DURATION_SECONDS"] = "10800"
        get_settings.cache_clear()

    def _job(self, status: str = "queued") -> uuid.UUID:
        with Session(get_engine()) as db:
            user = User(
                id=uuid.uuid4(),
                email=f"{uuid.uuid4()}@example.com",
                password_hash="x",
                display_name="An",
                created_at=datetime.now(timezone.utc),
            )
            job = Job(
                id=uuid.uuid4(),
                user_id=user.id,
                title="t",
                source="upload",
                status=status,
                warnings=[],
                created_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.flush()
            db.add(job)
            db.commit()
            return job.id

    def _source(self, job_id: uuid.UUID, seconds: float = 3.0) -> Path:
        folder = self.root / "tmp" / str(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "source.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"sine=frequency=440:duration={seconds}", "-ac", "2", "-ar", "44100", str(path)],
            check=True,
        )
        return path

    def _run(self, job_id, **overrides):
        options = {
            "engine_factory": FakeEngine,
            "diarize_fn": fake_diarize,
            "regions_fn": lambda pcm: [(0.0, len(pcm) / 16000)],
        }
        options.update(overrides)
        return run_upload_job(str(job_id), **options)

    def _events(self, db: Session, job_id) -> list[str]:
        rows = db.query(JobEvent).filter(JobEvent.job_id == job_id).order_by(JobEvent.seq).all()
        return [row.event_type for row in rows]

    def test_ready_with_opus_labels_and_cleanup(self) -> None:
        job_id = self._job()
        self._source(job_id)
        self.assertEqual(self._run(job_id), "done")
        with Session(get_engine()) as db:
            job = db.get(Job, job_id)
            self.assertEqual(job.status, "ready")
            self.assertTrue(Path(job.audio_path).is_file())
            self.assertAlmostEqual(job.duration_ms, 3000, delta=100)
            self.assertEqual(job.diarization_device, "cpu")
            self.assertEqual(
                self._events(db, job_id),
                ["stage", "stage", "chunk", "stage", "speakers", "done"],
            )
            segment = db.query(Segment).filter(Segment.job_id == job_id).one()
            self.assertEqual(segment.speaker_label, "SPEAKER_00")
            words = db.query(Word).filter(Word.segment_id == segment.id).all()
            self.assertEqual({word.speaker_label for word in words}, {"SPEAKER_00"})
        self.assertFalse((self.root / "tmp" / str(job_id)).exists())
        self.assertFalse((self.root / "tmp" / f"{job_id}.f32").exists())

    def test_retry_uses_canonical_opus(self) -> None:
        job_id = self._job()
        self._source(job_id)
        self._run(job_id)
        with Session(get_engine()) as db:
            job = db.get(Job, job_id)
            clear_pass(db, job_id, 2)
            job.status = "queued"
            db.commit()
        self._run(job_id)
        with Session(get_engine()) as db:
            self.assertEqual(db.get(Job, job_id).status, "ready")

    def test_redelivery_clears_partial_pass_two(self) -> None:
        job_id = self._job(status="transcribing")
        self._source(job_id)
        with Session(get_engine()) as db:
            db.add(Segment(job_id=job_id, pass_index=2, position=0, start_ms=0, end_ms=10, text_raw="dở"))
            db.commit()
        self._run(job_id)
        with Session(get_engine()) as db:
            texts = [row.text_raw for row in db.query(Segment).filter(Segment.job_id == job_id)]
            self.assertEqual(texts, ["xin chào"])
            self.assertEqual(db.get(Job, job_id).status, "ready")

    def test_file_without_audio_fails(self) -> None:
        job_id = self._job()
        folder = self.root / "tmp" / str(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "source.mp3").write_bytes(b"not audio at all")
        self._run(job_id)
        with Session(get_engine()) as db:
            job = db.get(Job, job_id)
            self.assertEqual((job.status, job.error_code), ("failed", "unsupported_media"))
            self.assertEqual(self._events(db, job_id)[-1], "error")
        self.assertFalse((self.root / "tmp" / f"{job_id}.f32").exists())

    def test_too_long_fails_without_pcm(self) -> None:
        os.environ["MAX_DURATION_SECONDS"] = "1"
        get_settings.cache_clear()
        job_id = self._job()
        self._source(job_id, seconds=3)
        self._run(job_id)
        with Session(get_engine()) as db:
            job = db.get(Job, job_id)
            self.assertEqual((job.status, job.error_code), ("failed", "duration_exceeded"))
        self.assertFalse((self.root / "tmp" / f"{job_id}.f32").exists())

    def test_unknown_duration_is_capped(self) -> None:
        job_id = self._job()
        source = self._source(job_id, seconds=4)
        opus = self.root / "audio" / f"{job_id}-cap.opus"
        pcm = self.root / "tmp" / f"{job_id}-cap.f32"
        with mock.patch.object(audio_processor, "probe", return_value=audio_processor.Probe(True, None)):
            with self.assertRaises(audio_processor.MediaError) as caught:
                audio_processor.normalize(source, opus, pcm, max_duration_s=1)
        self.assertEqual(caught.exception.code, "duration_exceeded")
        self.assertFalse(pcm.exists())
        self.assertLessEqual(audio_processor.probe(opus).duration_s, 2.1)

    def test_whisper_oom_fails(self) -> None:
        def broken():
            raise GpuOutOfMemory("CUDA out of memory")

        job_id = self._job()
        self._source(job_id)
        self._run(job_id, engine_factory=broken)
        with Session(get_engine()) as db:
            job = db.get(Job, job_id)
            self.assertEqual((job.status, job.error_code), ("failed", "gpu_oom"))

    def test_silence_is_ready_without_loading_whisper(self) -> None:
        job_id = self._job()
        self._source(job_id)
        self._run(job_id, regions_fn=lambda pcm: [])
        with Session(get_engine()) as db:
            self.assertEqual(db.get(Job, job_id).status, "ready")
        self.assertEqual(FakeEngine.instances, [])

    def test_cancelled_job_is_skipped(self) -> None:
        job_id = self._job(status="cancelled")
        self._source(job_id)
        self.assertEqual(self._run(job_id), "done")
        self.assertTrue((self.root / "tmp" / str(job_id) / "source.wav").exists())


class HallucinationFilterTests(unittest.TestCase):
    def test_known_phrases_are_dropped(self) -> None:
        self.assertTrue(is_hallucination("Hãy đăng ký kênh để không bỏ lỡ video mới!"))
        self.assertTrue(is_hallucination("Cảm ơn các bạn đã theo dõi."))

    def test_real_sentences_are_kept(self) -> None:
        self.assertFalse(is_hallucination("Hôm nay chúng ta bàn về việc đăng ký kênh phân phối mới cho quý sau."))
        self.assertFalse(is_hallucination(""))

    def test_prompt_is_trimmed(self) -> None:
        self.assertIsNone(prompt_or_none("   "))
        self.assertEqual(len(prompt_or_none("a" * 900)), 800)


if __name__ == "__main__":
    unittest.main()
