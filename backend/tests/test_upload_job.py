"""run_upload_job với FFmpeg thật, Whisper và pyannote giả."""

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from types import SimpleNamespace
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
from app.services.stt_engine import (
    GpuOutOfMemory,
    collect_words,
    is_hallucination,
    prompt_or_none,
    too_fast,
    trim_call_to_action,
    trim_call_to_action_text,
)

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
        # Chữ phủ hết audio, để pipeline không nhận dạng lại khoảng trống.
        end = len(audio) / 16000
        return [
            {
                "start": 0.1,
                "end": end,
                "text": "xin chào",
                "words": [{"text": "xin", "start": 0.1, "end": 0.5}, {"text": "chào", "start": 0.5, "end": end}],
            }
        ]

    def release(self) -> None:
        self.released = True


class GapEngine(FakeEngine):
    """Bỏ trống phần sau giây đầu của chunk, nhưng nhận ra chữ khi được gọi riêng khoảng trống."""

    def transcribe(self, audio, vocabulary):
        self.calls += 1
        seconds = len(audio) / 16000
        if self.calls == 1:
            return [{"start": 0.1, "end": 1.0, "text": "xin chào", "words": [
                {"text": "xin", "start": 0.1, "end": 0.5}, {"text": "chào", "start": 0.5, "end": 1.0}]}]
        return [{"start": 0.2, "end": seconds, "text": "lấy lại", "words": [
            {"text": "lấy", "start": 0.2, "end": 0.6}, {"text": "lại", "start": 0.6, "end": seconds}]}]


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

    def test_job_yields_gpu_between_chunks_and_resumes(self) -> None:
        from app.services.gpu_lock import _memory, clear_gpu_wanted, want_gpu

        clear_gpu_wanted()
        job_id = self._job()
        self._source(job_id, seconds=40.0)
        regions = lambda pcm: [(0.0, 2.0), (35.0, 37.0)]  # noqa: E731, hai chunk xa nhau

        class AskingEngine(FakeEngine):
            def transcribe(self, audio, vocabulary):
                # Phiên nghe xin GPU khi job đang nhận dạng chunk đầu.
                want_gpu("nguoi-xin")
                return super().transcribe(audio, vocabulary)

        def diarize(pcm, num_speakers):
            return [SpeakerTurn(0, 40000, "SPEAKER_00")], {}, "cpu"

        plan = self.root / "tmp" / f"{job_id}.plan.json"
        pcm = self.root / "tmp" / f"{job_id}.f32"
        try:
            self.assertEqual(self._run(job_id, engine_factory=AskingEngine, diarize_fn=diarize, regions_fn=regions), "retry")
            self.assertTrue(plan.is_file())
            self.assertTrue(pcm.is_file())
            self.assertTrue(FakeEngine.instances[-1].released)
            # Khóa được giữ chỗ cho người xin, không bỏ trống cho job khác chen vào.
            self.assertEqual(_memory.owner, "reserved:nguoi-xin")
            with Session(get_engine()) as db:
                job = db.get(Job, job_id)
                self.assertEqual(job.status, "transcribing")
                self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id).count(), 1)
                last = db.query(JobEvent).filter(JobEvent.job_id == job_id).order_by(JobEvent.seq.desc()).first()
                self.assertIn("nhường GPU", last.payload["detail"])

            # Còn giữ chỗ thì job chưa lấy lại được khóa.
            self.assertEqual(self._run(job_id, diarize_fn=diarize, regions_fn=regions), "retry")
            self.assertTrue(plan.is_file())

            # Phiên nghe dùng xong, khóa trống lại.
            clear_gpu_wanted()
            _memory.owner = None
            self.assertEqual(self._run(job_id, diarize_fn=diarize, regions_fn=regions), "done")
            with Session(get_engine()) as db:
                job = db.get(Job, job_id)
                self.assertEqual(job.status, "ready")
                rows = db.query(Segment).filter(Segment.job_id == job_id).order_by(Segment.position).all()
                self.assertEqual([row.position for row in rows], [0, 1])
                self.assertEqual([row.start_ms // 1000 for row in rows], [0, 35])
                self.assertEqual({row.speaker_label for row in rows}, {"SPEAKER_00"})
                chunks = [
                    row.payload["chunk_index"]
                    for row in db.query(JobEvent).filter(JobEvent.job_id == job_id, JobEvent.event_type == "chunk")
                ]
                self.assertEqual(sorted(chunks), [0, 1])
            self.assertFalse(plan.exists())
            self.assertFalse(pcm.exists())
        finally:
            clear_gpu_wanted()
            _memory.owner = None

    def test_job_yields_at_most_three_times(self) -> None:
        from app.services.gpu_lock import _memory, clear_gpu_wanted, want_gpu

        # Ai đó mở phiên liên tục mà không bao giờ dùng GPU: job vẫn chạy xong.
        job_id = self._job()
        self._source(job_id, seconds=180.0)
        regions = lambda pcm: [(start, start + 2.0) for start in (0.0, 35.0, 70.0, 105.0, 140.0)]  # noqa: E731
        outcomes = []
        try:
            for _ in range(6):
                want_gpu("nguoi-xin")
                _memory.owner = None
                outcomes.append(self._run(job_id, regions_fn=regions))
                if outcomes[-1] == "done":
                    break
            self.assertEqual(outcomes, ["retry", "retry", "retry", "done"])
            with Session(get_engine()) as db:
                self.assertEqual(db.get(Job, job_id).status, "ready")
                self.assertEqual(db.query(Segment).filter(Segment.job_id == job_id).count(), 5)
        finally:
            clear_gpu_wanted()
            _memory.owner = None

    def test_cancel_while_yielded_drops_saved_audio(self) -> None:
        job_id = self._job(status="cancelled")
        plan = self.root / "tmp" / f"{job_id}.plan.json"
        pcm = self.root / "tmp" / f"{job_id}.f32"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("{}", encoding="utf-8")
        pcm.write_bytes(b"\x00" * 8)
        self.assertEqual(self._run(job_id), "done")
        self.assertFalse(plan.exists())
        self.assertFalse(pcm.exists())

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

    def test_empty_part_of_a_region_is_transcribed_again(self) -> None:
        job_id = self._job()
        self._source(job_id, seconds=6.0)
        self._run(job_id, engine_factory=GapEngine)
        self.assertEqual(FakeEngine.instances[-1].calls, 2)
        with Session(get_engine()) as db:
            words = [
                (row.text, row.start_ms)
                for row in db.query(Word).join(Segment).filter(Segment.job_id == job_id).order_by(Word.start_ms)
            ]
            self.assertEqual(words, [("xin", 100), ("chào", 500), ("lấy", 1200), ("lại", 1600)])

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

    def test_call_to_action_with_long_tail_is_dropped(self) -> None:
        # Hai câu bịa đo được trên bản tin VTV24, đuôi dài hơn 25 ký tự.
        self.assertTrue(is_hallucination("Hãy subscribe cho kênh La La School Để không bỏ lỡ những video hấp dẫn"))
        self.assertTrue(is_hallucination("Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"))
        self.assertTrue(is_hallucination("Các bạn hãy đăng ký kênh để ủng hộ kênh của chúng mình nhé."))
        self.assertTrue(is_hallucination("Đăng ký kênh để nhận thông tin."))

    def test_call_to_action_inside_sentence_is_dropped(self) -> None:
        # Câu bịa lọt bộ lọc khi đo trên bài giảng và cuộc họp thật (2026-11-03).
        self.assertTrue(is_hallucination("Các bạn hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"))
        self.assertTrue(is_hallucination("Các bạn hãy đăng kí cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn"))
        self.assertTrue(is_hallucination("Để không bỏ lỡ những video hấp dẫn"))
        self.assertTrue(is_hallucination("cảm ơn bạn đã cùng theo dõi và đăng ký kênh của chương trình."))
        # acid giây 870, vòng 2026-11-09.
        self.assertTrue(is_hallucination("Các bạn có thể nhớ like, share và đăng ký kênh để ủng hộ kênh của chúng mình nhé."))

    def test_long_call_to_action_made_of_known_phrases_is_dropped(self) -> None:
        # #25: câu 21 từ lọt trần 20 từ ở `acid` giây 791 (2026-11-05).
        text = "Cảm ơn các bạn đã theo dõi và hãy subscribe cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn"
        self.assertEqual(len(text.split()), 21)
        self.assertTrue(is_hallucination(text))
        self.assertTrue(is_hallucination(text + " Hẹn gặp lại các bạn trong những video tiếp theo."))

    def test_call_to_action_glued_to_real_speech_is_kept(self) -> None:
        # Lời thật dính sau lời mời, như `hop1` giây 1573 vòng 11-03: bỏ cả câu thì mất lời thật.
        text = (
            "Các bạn hãy đăng kí cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn "
            "nó tiếp tục thể hiện năng lực sẽ trở thành công thức và sau đó chúng ta sẽ bàn tiếp"
        )
        self.assertFalse(is_hallucination(text))

    def test_call_to_action_inside_long_sentence_is_cut_out(self) -> None:
        # #25: `hop1` giây 894 (2026-11-05 và 11-09), lời mời ở đuôi câu 21 từ.
        tail = "Mày đi ra đi, hãy nhớ lại đi, hãy subscribe cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn"
        self.assertFalse(is_hallucination(tail))
        self.assertEqual(trim_call_to_action_text(tail), "Mày đi ra đi, hãy nhớ lại đi,")
        # `hop1` giây 1573 vòng 11-03, lời mời ở đầu câu dài.
        head = "Các bạn hãy đăng kí cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn nó tiếp tục thể hiện năng lực"
        self.assertEqual(trim_call_to_action_text(head), "nó tiếp tục thể hiện năng lực")

    def test_trimming_keeps_word_timings_of_the_rest(self) -> None:
        words = [{"text": text, "start": index, "end": index + 1} for index, text in enumerate(
            "Chốt lại như vậy. Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn".split())]
        kept = trim_call_to_action(words)
        self.assertEqual([word["text"] for word in kept], ["Chốt", "lại", "như", "vậy."])
        self.assertEqual(kept[-1]["end"], 4)

    def test_sentences_without_call_to_action_are_not_trimmed(self) -> None:
        text = "Khách hàng subscribe gói năm tăng 20% và mình không muốn bỏ lỡ những khách hàng quay lại trong quý sau nữa"
        self.assertEqual(trim_call_to_action_text(text), text)

    def test_real_sentences_are_kept(self) -> None:
        self.assertFalse(is_hallucination("Hôm nay chúng ta bàn về việc đăng ký kênh phân phối mới cho quý sau."))
        self.assertFalse(is_hallucination("Khách hàng subscribe gói năm tăng 20% so với cùng kỳ."))
        self.assertFalse(is_hallucination("Các bạn đăng kí cho kênh bán hàng mới trước thứ sáu nhé."))
        self.assertFalse(is_hallucination("Mình không muốn bỏ lỡ những khách hàng quay lại."))
        self.assertFalse(is_hallucination(""))

    def test_impossible_speech_rate_is_dropped(self) -> None:
        # Câu bịa của PhoWhisper ở cuối chunk: 21 từ trong 0,24 giây.
        text = "những bức ảnh chụp từ đầu năm một nghìn chín trăm bảy chín trăm năm một nghìn chín năm bảy chín."
        self.assertTrue(too_fast(text, 22.78, 23.02))
        self.assertFalse(too_fast("Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận", 0.4, 4.0))
        self.assertFalse(too_fast("Chào các bạn.", 35.5, 35.6))

    def test_word_pieces_without_space_join_previous_word(self) -> None:
        def piece(text: str, start: float, end: float) -> SimpleNamespace:
            return SimpleNamespace(word=text, start=start, end=end)

        words = collect_words([piece(" có", 0.0, 0.2), piece(" 150", 0.2, 0.6), piece(".000", 0.6, 0.9),
                               piece(" lượt", 0.9, 1.1), piece(" 0", 1.1, 1.3), piece("%", 1.3, 1.4), piece(" ", 1.4, 1.4)])
        self.assertEqual([w["text"] for w in words], ["có", "150.000", "lượt", "0%"])
        self.assertEqual((words[1]["start"], words[1]["end"]), (0.2, 0.9))

    def test_prompt_is_trimmed(self) -> None:
        self.assertIsNone(prompt_or_none("   "))
        self.assertEqual(len(prompt_or_none("a" * 900)), 800)


if __name__ == "__main__":
    unittest.main()
