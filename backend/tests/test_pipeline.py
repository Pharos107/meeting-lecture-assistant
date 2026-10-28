"""Pipeline bản chuẩn với hàm nhận dạng giả."""

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "t" * 32
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="stt-pipe-")
os.environ["REDIS_URL"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["VOICE_MATCH_THRESHOLD"] = "0.75"
os.environ["VOICE_MATCH_MARGIN"] = "0.05"

from sqlalchemy.orm import Session

from app.api.routes_voice import PIPELINE_MODEL
from app.core.config import get_settings
from app.db import get_engine
from app.models import (
    ActionItem,
    Base,
    Highlight,
    Job,
    JobEvent,
    LiveSession,
    LlmMapShard,
    LlmRun,
    MediaToken,
    RefreshToken,
    Segment,
    SpeakerAlias,
    User,
    VoiceProfile,
    Word,
    WsTicket,
)
from app.services.pipeline import run_standard_pass
from app.services.speaker_align import SpeakerTurn, pack_embedding

get_settings.cache_clear()
Base.metadata.create_all(get_engine())


def clear_rows() -> None:
    with Session(get_engine()) as db:
        for model in (
            Word,
            Highlight,
            ActionItem,
            Segment,
            SpeakerAlias,
            JobEvent,
            LlmMapShard,
            LlmRun,
            MediaToken,
            WsTicket,
            LiveSession,
            VoiceProfile,
            Job,
            RefreshToken,
            User,
        ):
            db.query(model).delete()
        db.commit()


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["REDIS_URL"] = ""
        os.environ["VOICE_MATCH_THRESHOLD"] = "0.75"
        os.environ["VOICE_MATCH_MARGIN"] = "0.05"
        get_settings.cache_clear()
        clear_rows()

    def _job(self) -> tuple[Session, Job]:
        db = Session(get_engine())
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash="x",
            display_name="An",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        job = Job(
            user_id=user.id,
            title="hop",
            source="upload",
            status="queued",
            warnings=[],
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()
        return db, job

    def test_empty_regions_finish_ready(self) -> None:
        db, job = self._job()
        try:
            run_standard_pass(db, job, regions=[], transcribe=lambda _chunk: [])
            self.assertEqual(job.status, "ready")
            self.assertEqual(db.query(Segment).count(), 0)
            types = [row.event_type for row in db.query(JobEvent).filter(JobEvent.job_id == job.id)]
            self.assertIn("done", types)
        finally:
            db.close()

    def test_cancel_keeps_the_chunk_already_written(self) -> None:
        db, job = self._job()
        calls: list[float] = []

        def transcribe(chunk):
            calls.append(chunk.start)
            if len(calls) == 1:
                job.status = "cancelled"
                db.commit()
            return [{"text": "xin chào", "start": 0, "end": 1, "words": [{"text": "xin", "start": 0.0, "end": 0.4}, {"text": "chào", "start": 0.4, "end": 1.0}]}]

        try:
            run_standard_pass(db, job, regions=[(0, 5), (20, 25)], transcribe=transcribe)
            self.assertEqual(calls, [0])
            self.assertEqual(job.status, "cancelled")
            rows = db.query(Segment).filter(Segment.job_id == job.id).all()
            self.assertEqual([row.text_raw for row in rows], ["xin chào"])
        finally:
            db.close()

    def test_overlap_and_diarization_failure(self) -> None:
        db, job = self._job()

        def transcribe(chunk):
            if chunk.start == 0:
                return [{
                    "text": "bỏ",
                    "words": [
                        {"text": "giữ-trước", "start": 29.2, "end": 29.4},
                        {"text": "bỏ-trước", "start": 29.4, "end": 29.8},
                    ],
                }]
            if chunk.start == 29:
                return [{
                    "text": "bỏ",
                    "words": [
                        {"text": "bỏ-sau", "start": 0.2, "end": 0.4},
                        {"text": "giữ-sau", "start": 0.4, "end": 0.8},
                    ],
                }]
            return [{"text": "đuôi", "words": [{"text": "đuôi", "start": 0.2, "end": 1.0}]}]

        def diarize():
            raise RuntimeError("cuda")

        try:
            run_standard_pass(db, job, regions=[(0, 60)], transcribe=transcribe, diarize=diarize)
            self.assertEqual(job.status, "ready")
            self.assertIsNone(job.diarization_device)
            self.assertEqual(job.warnings[0]["code"], "diarization_failed")
            words = [row.text for row in db.query(Word).join(Segment).filter(Segment.job_id == job.id).order_by(Word.start_ms)]
            self.assertEqual(words, ["giữ-trước", "giữ-sau", "đuôi"])
            self.assertTrue(all(row.speaker_label is None for row in db.query(Segment).filter(Segment.job_id == job.id)))
        finally:
            db.close()

    def test_voice_alias_skips_manual_names(self) -> None:
        db, job = self._job()
        lan = VoiceProfile(
            user_id=job.user_id,
            display_name="Lan",
            status="ready",
            embedding=pack_embedding([1.0, 0.0]),
            embedding_dim=2,
            embedding_model=PIPELINE_MODEL,
            created_at=datetime.now(timezone.utc),
        )
        binh = VoiceProfile(
            user_id=job.user_id,
            display_name="Bình",
            status="ready",
            embedding=pack_embedding([0.0, 1.0]),
            embedding_dim=2,
            embedding_model=PIPELINE_MODEL,
            created_at=datetime.now(timezone.utc),
        )
        db.add(lan)
        db.add(binh)
        db.add(SpeakerAlias(job_id=job.id, speaker_label="SPEAKER_00", display_name="Giữ", source="manual"))
        db.add(SpeakerAlias(job_id=job.id, speaker_label="SPEAKER_02", display_name="Cũ", source="voice_profile"))
        db.commit()

        def transcribe(_chunk):
            return [{
                "text": "hai người",
                "words": [
                    {"text": "một", "start": 0.0, "end": 1.0},
                    {"text": "hai", "start": 5.0, "end": 6.0},
                ],
            }]

        def diarize():
            return (
                [SpeakerTurn(0, 4000, "SPEAKER_00"), SpeakerTurn(4000, 8000, "SPEAKER_01")],
                {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [0.0, 1.0]},
                "cpu",
            )

        try:
            run_standard_pass(db, job, regions=[(0, 10)], transcribe=transcribe, diarize=diarize)
            self.assertEqual(job.status, "ready")
            self.assertEqual(job.diarization_device, "cpu")
            aliases = {
                row.speaker_label: (row.display_name, row.source)
                for row in db.query(SpeakerAlias).filter(SpeakerAlias.job_id == job.id)
            }
            self.assertEqual(aliases["SPEAKER_00"], ("Giữ", "manual"))
            self.assertEqual(aliases["SPEAKER_01"], ("Bình", "voice_profile"))
            self.assertNotIn("SPEAKER_02", aliases)
        finally:
            db.close()
