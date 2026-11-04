"""Ghi danh hồ sơ giọng với FFmpeg thật, VAD và pyannote giả."""

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "t" * 32)
os.environ["REDIS_URL"] = ""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import Base, User, VoiceProfile
from app.services.diarization import PIPELINE_MODEL
from app.services.gpu_lock import _memory
from app.services.speaker_align import VoiceProfileVector, match_speakers, unpack_embedding
from app.services.voice_profile import pick_vector, run_enroll, speech_ms

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
DATA_DIR = tempfile.mkdtemp(prefix="stt-voice-")
VECTOR = [0.6, 0.8, 0.0]


def whole(pcm):
    return [(0.0, len(pcm) / 16000)]


def one_speaker(pcm, num_speakers):
    assert num_speakers == 1
    assert len(pcm) > 16000
    return [], {"SPEAKER_00": VECTOR}, "cpu"


class HelperTests(unittest.TestCase):
    def test_speech_ms_sums_regions(self) -> None:
        self.assertEqual(speech_ms([(0.0, 10.0), (12.0, 17.5)]), 15_500)
        self.assertEqual(speech_ms([]), 0)

    def test_pick_vector_skips_empty_labels(self) -> None:
        self.assertIsNone(pick_vector({}))
        self.assertEqual(pick_vector({"SPEAKER_00": [], "SPEAKER_01": [1.0]}), [1.0])


@unittest.skipUnless(HAS_FFMPEG, "Cần ffmpeg và ffprobe trên PATH.")
class EnrollTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["REDIS_URL"] = ""
        os.environ["DATA_DIR"] = DATA_DIR
        get_settings.cache_clear()
        Base.metadata.create_all(get_engine())
        _memory.owner = None
        _memory.deadline = 0.0
        self.root = Path(DATA_DIR)

    def _profile(self, seconds: float = 25.0, suffix: str = "wav") -> uuid.UUID:
        user_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        folder = self.root / "voice" / str(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        sample = folder / f"{profile_id}.{suffix}"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"sine=frequency=220:duration={seconds}", "-ac", "2", "-ar", "48000" if suffix == "opus" else "44100", str(sample)],
            check=True,
        )
        with Session(get_engine()) as db:
            db.add(
                User(
                    id=user_id,
                    email=f"{uuid.uuid4()}@example.com",
                    password_hash="x",
                    display_name="An",
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.flush()
            db.add(
                VoiceProfile(
                    id=profile_id,
                    user_id=user_id,
                    display_name="Lan",
                    status="processing",
                    sample_path=str(sample),
                    duration_ms=int(seconds * 1000),
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        return profile_id

    def _row(self, profile_id) -> VoiceProfile | None:
        with Session(get_engine()) as db:
            row = db.get(VoiceProfile, profile_id)
            if row is not None:
                db.expunge(row)
            return row

    def test_ready_profile_has_vector_and_opus_sample(self) -> None:
        profile_id = self._profile()
        original = Path(self._row(profile_id).sample_path)
        self.assertEqual(run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole), "done")
        row = self._row(profile_id)
        self.assertEqual(row.status, "ready")
        self.assertIsNone(row.error_message)
        self.assertEqual(row.embedding_model, PIPELINE_MODEL)
        self.assertEqual(row.embedding_dim, 3)
        self.assertEqual([round(value, 5) for value in unpack_embedding(row.embedding)], VECTOR)
        self.assertTrue(row.sample_path.endswith(f"{profile_id}.opus"))
        self.assertTrue(Path(row.sample_path).is_file())
        self.assertFalse(original.exists())
        self.assertAlmostEqual(row.duration_ms / 1000, 25, delta=0.2)
        self.assertEqual(list((self.root / "tmp").glob(f"voice-{profile_id}*")), [])
        self.assertIsNone(_memory.owner)

    def test_enrolled_vector_matches_the_same_voice_in_a_meeting(self) -> None:
        profile_id = self._profile()
        run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole)
        row = self._row(profile_id)
        profile = VoiceProfileVector(str(row.id), unpack_embedding(row.embedding), row.embedding_model)
        mapping = match_speakers(
            {"SPEAKER_00": [0.0, 0.0, 1.0], "SPEAKER_01": [3.0, 4.0, 0.1]},
            [profile],
            current_model=PIPELINE_MODEL,
        )
        self.assertEqual(mapping, {"SPEAKER_01": str(row.id)})

    def test_opus_sample_is_kept_in_place(self) -> None:
        profile_id = self._profile(suffix="opus")
        run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole)
        row = self._row(profile_id)
        self.assertEqual(row.status, "ready")
        self.assertTrue(Path(row.sample_path).is_file())

    def test_too_little_speech_fails_with_a_reason(self) -> None:
        profile_id = self._profile()
        called = []

        def diarize(pcm, num_speakers):
            called.append(True)
            return one_speaker(pcm, num_speakers)

        run_enroll(str(profile_id), diarize_fn=diarize, regions_fn=lambda _pcm: [(0.0, 9.0), (12.0, 17.0)])
        row = self._row(profile_id)
        self.assertEqual(row.status, "failed")
        self.assertIn("14,0 giây", row.error_message)
        self.assertEqual(called, [])
        self.assertIsNone(row.embedding)
        self.assertTrue(Path(row.sample_path).is_file())

    def test_no_vector_fails(self) -> None:
        profile_id = self._profile()
        run_enroll(str(profile_id), diarize_fn=lambda _pcm, _n: ([], {}, "cpu"), regions_fn=whole)
        row = self._row(profile_id)
        self.assertEqual(row.status, "failed")
        self.assertIn("vector", row.error_message)

    def test_crash_in_pyannote_fails_and_releases_lock(self) -> None:
        profile_id = self._profile()

        def broken(_pcm, _n):
            raise RuntimeError("hỏng")

        run_enroll(str(profile_id), diarize_fn=broken, regions_fn=whole)
        row = self._row(profile_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_message, "Worker gặp lỗi khi tính vector giọng.")
        self.assertIsNone(_memory.owner)

    def test_unreadable_sample_fails(self) -> None:
        profile_id = self._profile()
        Path(self._row(profile_id).sample_path).write_bytes(b"khong phai am thanh")
        run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole)
        row = self._row(profile_id)
        self.assertEqual(row.status, "failed")
        self.assertTrue(row.error_message)

    def test_missing_sample_fails(self) -> None:
        profile_id = self._profile()
        Path(self._row(profile_id).sample_path).unlink()
        run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole)
        self.assertEqual(self._row(profile_id).status, "failed")

    def test_profile_deleted_while_computing_leaves_no_file(self) -> None:
        profile_id = self._profile()
        folder = Path(self._row(profile_id).sample_path).parent

        def delete_then_embed(pcm, num_speakers):
            with Session(get_engine()) as db:
                db.delete(db.get(VoiceProfile, profile_id))
                db.commit()
            return one_speaker(pcm, num_speakers)

        self.assertEqual(run_enroll(str(profile_id), diarize_fn=delete_then_embed, regions_fn=whole), "done")
        self.assertIsNone(self._row(profile_id))
        self.assertEqual(list(folder.glob(f"{profile_id}.*")), [])

    def test_busy_gpu_retries_until_profile_is_gone(self) -> None:
        profile_id = self._profile()
        self.assertTrue(_memory.acquire("job-khac", ttl=60))
        try:
            self.assertEqual(run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole), "retry")
            self.assertEqual(self._row(profile_id).status, "processing")
            with Session(get_engine()) as db:
                db.delete(db.get(VoiceProfile, profile_id))
                db.commit()
            self.assertEqual(run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole), "done")
        finally:
            _memory.release("job-khac")

    def test_probe_reads_webm_without_duration_header(self) -> None:
        from app.api.routes_voice import probe_sample

        # Ghi ra pipe thì muxer không quay lại ghi thời lượng, giống file của MediaRecorder.
        sample = self.root / f"{uuid.uuid4()}.webm"
        encoded = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=220:duration=22", "-c:a", "libopus", "-f", "webm", "pipe:1"],
            check=True,
            capture_output=True,
        )
        sample.write_bytes(encoded.stdout)
        duration_ms, _speech_ms = probe_sample(sample)
        self.assertAlmostEqual(duration_ms / 1000, 22, delta=0.3)

    def test_ready_profile_is_not_enrolled_twice(self) -> None:
        profile_id = self._profile()
        run_enroll(str(profile_id), diarize_fn=one_speaker, regions_fn=whole)

        def must_not_run(_pcm, _n):
            raise AssertionError("không được tính lại")

        self.assertEqual(run_enroll(str(profile_id), diarize_fn=must_not_run, regions_fn=whole), "done")
        self.assertEqual(self._row(profile_id).status, "ready")


if __name__ == "__main__":
    unittest.main()
