"""SSE, xuất file, LLM, nghe trực tiếp, và hồ sơ giọng."""

import json
import os
import shutil
import tempfile
import threading
import unittest
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "t" * 32
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="stt-rest-")
os.environ["REDIS_URL"] = ""
os.environ["LLM_MODEL"] = ""

import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session

import app.api.routes_voice as voice_routes
from app.api.routes_voice import PIPELINE_MODEL
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.rate_limit import SlidingWindow
from app.db import get_engine
from app.main import app
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
from app.services.gpu_lock import _memory, keeper
from app.services.job_notify import reset_job_watches
from app.services.live_channel import (
    claim_writer,
    close_session,
    publish_live,
    put_open_draft,
    reset_live_channel,
    writer_current,
)
from app.services.live_heartbeat import clear_heartbeats
from app.services.llm_runner import LlmTimeout, LlmUpstream, execute_llm_run, http_chat, shard_segments

get_settings.cache_clear()
Base.metadata.create_all(get_engine())
client = TestClient(app)
DATA = Path(os.environ["DATA_DIR"])
ORIGINAL_PROBE = voice_routes.probe_sample


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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(email: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "mot-mat-khau", "display_name": "An"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def upload(token: str) -> str:
    response = client.post(
        "/api/jobs",
        headers=auth(token),
        files={"file": ("hop.mp3", b"abc", "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def parse_sse(body: str) -> list[dict]:
    frames = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        item: dict = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                item["id"] = line[4:]
            elif line.startswith("event: "):
                item["event"] = line[7:]
            elif line.startswith("data: "):
                item["data"] = json.loads(line[6:])
        frames.append(item)
    return frames


class ShardTests(unittest.TestCase):
    def test_clean_and_summary_boundaries(self) -> None:
        sentences = [SimpleNamespace(text_raw="một", start_ms=index, end_ms=index + 1) for index in range(31)]
        shards = shard_segments(sentences, max_sentences=30, max_words=600)
        self.assertEqual([len(shard) for shard in shards], [30, 1])
        long = SimpleNamespace(text_raw=" ".join(["từ"] * 601), start_ms=0, end_ms=1000)
        follow = SimpleNamespace(text_raw="sau", start_ms=1000, end_ms=2000)
        parts = shard_segments([long, follow], max_words=600)
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[0]), 1)


class ApiRestTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DATA_DIR"] = str(DATA)
        os.environ["REDIS_URL"] = ""
        os.environ["LLM_MODEL"] = ""
        os.environ.pop("STT_SSE_ONCE", None)
        get_settings.cache_clear()
        keeper.stop_all()
        clear_heartbeats()
        reset_live_channel()
        reset_job_watches()
        _memory.owner = None
        _memory.deadline = 0.0
        voice_routes.probe_sample = ORIGINAL_PROBE
        clear_rows()
        self.token = register("a@example.com")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(DATA, ignore_errors=True)

    def test_sse_replays_after_seq(self) -> None:
        job_id = upload(self.token)
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            now = datetime.now(timezone.utc)
            db.add(JobEvent(job_id=job.id, seq=1, event_type="stage", payload={"stage": "preprocessing", "detail": "x"}, created_at=now))
            db.add(JobEvent(job_id=job.id, seq=2, event_type="chunk", payload={"chunk_index": 0, "segments": []}, created_at=now))
            db.commit()
        os.environ["STT_SSE_ONCE"] = "1"
        try:
            response = client.get(f"/api/jobs/{job_id}/events?after_seq=1", headers=auth(self.token))
        finally:
            os.environ.pop("STT_SSE_ONCE", None)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        frames = parse_sse(response.text)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["id"], "2")
        self.assertEqual(frames[0]["event"], "chunk")
        self.assertEqual(frames[0]["data"]["seq"], 2)
        other = register("b@example.com")
        missing = client.get(f"/api/jobs/{job_id}/events", headers=auth(other))
        self.assertEqual(missing.status_code, 404)
        bad = client.get(f"/api/jobs/{job_id}/events?after_seq=-1", headers=auth(self.token))
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["fields"]["after_seq"], "after_seq phải là số nguyên không âm.")
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "ready"
            db.add(
                JobEvent(
                    job_id=job.id,
                    seq=3,
                    event_type="done",
                    payload={},
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        finished = client.get(f"/api/jobs/{job_id}/events?after_seq=2", headers=auth(self.token))
        self.assertEqual(finished.status_code, 200)
        frames = parse_sse(finished.text)
        self.assertEqual(frames[0]["event"], "done")

    def _ready_segment(self) -> tuple[str, str]:
        job_id = upload(self.token)
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "ready"
            segment = Segment(
                job_id=job.id,
                pass_index=2,
                position=0,
                start_ms=1500,
                end_ms=2500,
                text_raw="gốc",
                text_cleaned="sạch",
                text_edited="đã sửa",
                speaker_label="SPEAKER_00",
            )
            db.add(segment)
            db.flush()
            db.add(SpeakerAlias(job_id=job.id, speaker_label="SPEAKER_00", display_name="Diễn giả", source="manual"))
            now = datetime.now(timezone.utc)
            db.add(
                LlmRun(
                    job_id=job.id,
                    task="summarize",
                    template="meeting",
                    status="done",
                    model_name="test",
                    result={
                        "objective": "Chốt phạm vi",
                        "open_issues": [{"timestamp": "01:00", "text": "Còn API"}],
                        "decisions": [{"timestamp": "02:00", "text": "Dùng FastAPI"}],
                        "actions": [{"timestamp": "03:00", "owner": "An", "task": "Viết test", "deadline": "thứ sáu"}],
                    },
                    created_at=now,
                )
            )
            db.add(
                ActionItem(
                    job_id=job.id,
                    segment_id=segment.id,
                    start_ms=4000,
                    owner="Bình",
                    task="Gửi biên bản",
                    deadline="",
                    source="manual",
                    created_at=now,
                )
            )
            db.add(
                Highlight(
                    job_id=job.id,
                    segment_id=segment.id,
                    quote="câu này",
                    start_ms=1500,
                    end_ms=2500,
                    created_at=now,
                )
            )
            db.commit()
            return job_id, str(segment.id)

    def test_export_srt_vtt_markdown_and_pdf(self) -> None:
        job_id, _segment_id = self._ready_segment()
        srt = client.post(
            f"/api/jobs/{job_id}/exports",
            headers=auth(self.token),
            json={"format": "srt", "text": "auto", "include_speakers": True},
        )
        self.assertEqual(srt.status_code, 200, srt.text)
        self.assertIn("00:00:01,500 --> 00:00:02,500", srt.text)
        self.assertIn("Diễn giả: đã sửa", srt.text)
        self.assertIn("filename*=UTF-8''", srt.headers["content-disposition"])
        raw = client.post(
            f"/api/jobs/{job_id}/exports",
            headers=auth(self.token),
            json={"format": "srt", "text": "raw", "include_speakers": False},
        )
        self.assertIn("gốc", raw.text)
        self.assertNotIn("đã sửa", raw.text)
        self.assertNotIn("Diễn giả:", raw.text)
        vtt = client.post(f"/api/jobs/{job_id}/exports", headers=auth(self.token), json={"format": "vtt"})
        self.assertTrue(vtt.text.startswith("WEBVTT"))
        self.assertIn("00:00:01.500 --> 00:00:02.500", vtt.text)
        markdown = client.post(f"/api/jobs/{job_id}/exports", headers=auth(self.token), json={"format": "md"}).text
        self.assertIn("# Mục tiêu", markdown)
        self.assertIn("Chốt phạm vi", markdown)
        self.assertIn("# Việc cần làm", markdown)
        self.assertIn("Gửi biên bản", markdown)
        self.assertIn("# Đánh dấu", markdown)
        self.assertIn("câu này", markdown)
        self.assertIn("# Transcript", markdown)
        self.assertIn("đã sửa", markdown)
        pdf = client.post(f"/api/jobs/{job_id}/exports", headers=auth(self.token), json={"format": "pdf"})
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        docx = client.post(f"/api/jobs/{job_id}/exports", headers=auth(self.token), json={"format": "docx"})
        with zipfile.ZipFile(BytesIO(docx.content)) as package:
            document = package.read("word/document.xml").decode("utf-8")
        self.assertIn("Mục tiêu", document)
        self.assertIn("đã sửa", document)
        queued = upload(self.token)
        blocked = client.post(f"/api/jobs/{queued}/exports", headers=auth(self.token), json={"format": "md"})
        self.assertEqual(blocked.status_code, 409)

    def test_llm_rejects_missing_model_then_retries_schema(self) -> None:
        job_id, segment_id = self._ready_segment()
        missing = client.post(f"/api/jobs/{job_id}/llm", headers=auth(self.token), json={"task": "clean"})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["error"]["code"], "llm_not_configured")
        with Session(get_engine()) as db:
            self.assertEqual(db.query(LlmRun).count(), 1)

        os.environ["LLM_MODEL"] = "test-model"
        get_settings.cache_clear()
        try:
            started = client.post(f"/api/jobs/{job_id}/llm", headers=auth(self.token), json={"task": "clean"})
            self.assertEqual(started.status_code, 202, started.text)
            run_id = started.json()["run_id"]
            again = client.post(f"/api/jobs/{job_id}/llm", headers=auth(self.token), json={"task": "clean"})
            self.assertEqual(again.status_code, 409)
            seen: list[str] = []

            def transport(messages):
                seen.append(messages[-1]["content"])
                if len(seen) == 1:
                    return "{}"
                return json.dumps({"segments": [{"id": segment_id, "text": "câu sạch"}]}, ensure_ascii=False)

            execute_llm_run(run_id, transport=transport)
            self.assertEqual(len(seen), 2)
            self.assertIn("Lỗi kiểm tra schema", seen[1])
            latest = client.get(f"/api/jobs/{job_id}/llm/clean", headers=auth(self.token))
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(latest.json()["status"], "done")
            self.assertIsNone(latest.json()["result"])
            with Session(get_engine()) as db:
                segment = db.get(Segment, uuid.UUID(segment_id))
                assert segment is not None
                self.assertEqual(segment.text_cleaned, "câu sạch")

            timed = client.post(f"/api/jobs/{job_id}/llm", headers=auth(self.token), json={"task": "clean"})
            self.assertEqual(timed.status_code, 202, timed.text)

            def timeout(_messages):
                raise LlmTimeout("LLM hết hạn.")

            execute_llm_run(timed.json()["run_id"], transport=timeout)
            failed = client.get(f"/api/jobs/{job_id}/llm/clean", headers=auth(self.token))
            self.assertEqual(failed.json()["status"], "failed")
            self.assertEqual(failed.json()["error_code"], "llm_timeout")

            refused = client.post(
                f"/api/jobs/{job_id}/llm",
                headers=auth(self.token),
                json={"task": "clean", "restart": True},
            )
            self.assertEqual(refused.status_code, 202, refused.text)

            def connect_error(_messages):
                raise httpx.ConnectError("refused")

            execute_llm_run(refused.json()["run_id"], transport=connect_error)
            upstream = client.get(f"/api/jobs/{job_id}/llm/clean", headers=auth(self.token))
            self.assertEqual(upstream.json()["status"], "failed")
            self.assertEqual(upstream.json()["error_code"], "llm_upstream")
            retry = client.post(f"/api/jobs/{job_id}/llm", headers=auth(self.token), json={"task": "clean"})
            self.assertEqual(retry.status_code, 202, retry.text)

            def status_error(*_args, **_kwargs):
                sent = httpx.Request("POST", "http://llm.test/chat/completions")
                response = httpx.Response(500, request=sent)
                raise httpx.HTTPStatusError("loi", request=sent, response=response)

            original = httpx.post
            httpx.post = status_error
            try:
                with self.assertRaises(LlmUpstream):
                    http_chat([{"role": "user", "content": "xin chào"}])
            finally:
                httpx.post = original
        finally:
            os.environ["LLM_MODEL"] = ""
            get_settings.cache_clear()

    def test_live_lock_stop_and_websocket(self) -> None:
        created = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Buổi học"})
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["expires_in"], 60)
        self.assertTrue(body["ws_path"].endswith("/stream"))
        busy = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Buổi khác"})
        self.assertEqual(busy.status_code, 409)
        self.assertEqual(busy.json()["error"]["code"], "gpu_busy")
        with Session(get_engine()) as db:
            self.assertEqual(db.query(LiveSession).count(), 1)
            self.assertEqual(db.query(Job).count(), 1)
        stopped = client.post(f"/api/live/sessions/{body['session_id']}/stop", headers=auth(self.token))
        self.assertEqual(stopped.status_code, 202)
        self.assertEqual(stopped.json()["status"], "stopping")
        with Session(get_engine()) as db:
            self.assertEqual(db.query(Job).count(), 1)
        again = client.post(f"/api/live/sessions/{body['session_id']}/stop", headers=auth(self.token))
        self.assertEqual(again.json()["status"], "stopping")

        _memory.owner = None
        _memory.deadline = 0.0
        opened = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Buổi hai"})
        self.assertEqual(opened.status_code, 201, opened.text)
        ticket = opened.json()["ticket"]
        session_id = opened.json()["session_id"]
        frame = b"\x00\x01" * 320
        with client.websocket_connect(f"/api/live/sessions/{session_id}/stream?ticket={ticket}") as socket:
            socket.send_json({"type": "hello", "sample_rate": 16000})
            self.assertEqual(socket.receive_json()["type"], "hello_ok")
            socket.send_bytes(frame)
            socket.send_json({"type": "stop"})
            self.assertEqual(socket.receive_json()["type"], "stopped")
        with Session(get_engine()) as db:
            session = db.get(LiveSession, uuid.UUID(session_id))
            assert session is not None
            self.assertEqual(session.status, "stopping")
            self.assertEqual(Path(session.pcm_path).read_bytes(), frame)
        with client.websocket_connect(f"/api/live/sessions/{session_id}/stream?ticket=khong-dung") as socket:
            denied = socket.receive_json()
        self.assertEqual(denied["code"], "unauthorized")
        removed = client.delete(f"/api/jobs/{opened.json()['job_id']}", headers=auth(self.token))
        self.assertEqual(removed.status_code, 204)
        freed = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Buổi ba"})
        self.assertEqual(freed.status_code, 201, freed.text)
        dropped = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Rớt mạng"})
        self.assertEqual(dropped.status_code, 409)
        keeper.stop_all()
        _memory.owner = None
        _memory.deadline = 0.0
        dropped = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Rớt mạng"})
        self.assertEqual(dropped.status_code, 201, dropped.text)
        with client.websocket_connect(
            f"/api/live/sessions/{dropped.json()['session_id']}/stream?ticket={dropped.json()['ticket']}"
        ) as socket:
            socket.send_json({"type": "hello", "sample_rate": 16000})
            self.assertEqual(socket.receive_json()["type"], "hello_ok")
            socket.send_bytes(b"\x00\x01" * 320)
        with Session(get_engine()) as db:
            session = db.get(LiveSession, uuid.UUID(dropped.json()["session_id"]))
            assert session is not None
            self.assertEqual(session.status, "capturing")

    def test_cancel_capturing_job_releases_lock_and_pcm(self) -> None:
        created = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Đang thu"})
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        session_id = uuid.UUID(body["session_id"])
        frame = b"\x00\x01" * 320
        ready = threading.Event()
        finished = threading.Event()

        def hold() -> None:
            try:
                with client.websocket_connect(
                    f"/api/live/sessions/{body['session_id']}/stream?ticket={body['ticket']}"
                ) as socket:
                    socket.send_json({"type": "hello", "sample_rate": 16000})
                    if socket.receive_json().get("type") != "hello_ok":
                        return
                    socket.send_bytes(frame)
                    ready.set()
                    socket.receive_json()
            except WebSocketDisconnect:
                return
            finally:
                finished.set()

        worker = threading.Thread(target=hold, daemon=True)
        worker.start()
        self.assertTrue(ready.wait(5))
        with Session(get_engine()) as db:
            session = db.get(LiveSession, session_id)
            assert session is not None
            db.add(
                Segment(
                    job_id=session.job_id,
                    pass_index=1,
                    position=0,
                    start_ms=0,
                    end_ms=1000,
                    text_raw="nháp",
                )
            )
            db.commit()
            pcm_path = Path(session.pcm_path)
        cancelled = client.post(f"/api/jobs/{body['job_id']}/cancel", headers=auth(self.token))
        self.assertEqual(cancelled.status_code, 202, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertTrue(finished.wait(5))
        worker.join(2)
        with Session(get_engine()) as db:
            session = db.get(LiveSession, session_id)
            assert session is not None
            self.assertEqual(session.status, "failed")
            job = db.get(Job, uuid.UUID(body["job_id"]))
            assert job is not None
            self.assertEqual(job.status, "cancelled")
            self.assertEqual(db.query(Segment).count(), 1)
        self.assertFalse(pcm_path.exists())
        opened = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Sau hủy"})
        self.assertEqual(opened.status_code, 201, opened.text)

    def test_live_drafts_and_single_writer(self) -> None:
        left = claim_writer("phien-a")
        right = claim_writer("phien-a")
        assert left is not None and right is not None
        self.assertFalse(writer_current("phien-a", left))
        self.assertTrue(writer_current("phien-a", right))
        close_session("phien-a")
        self.assertFalse(writer_current("phien-a", right))
        reset_live_channel()

        created = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Nháp"})
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        session_id = body["session_id"]
        put_open_draft(session_id, {"type": "draft", "text": "đang mở", "stable": False})
        first_frame = b"\x00\x01" * 320
        second_frame = b"\x02\x03" * 320
        first_ready = threading.Event()
        first_done = threading.Event()

        def hold_first() -> None:
            try:
                with client.websocket_connect(
                    f"/api/live/sessions/{session_id}/stream?ticket={body['ticket']}"
                ) as socket:
                    socket.send_json({"type": "hello", "sample_rate": 16000})
                    if socket.receive_json().get("type") != "hello_ok":
                        return
                    opened = socket.receive_json()
                    if opened.get("text") != "đang mở":
                        return
                    socket.send_bytes(first_frame)
                    first_ready.set()
                    socket.receive_json()
            except WebSocketDisconnect:
                return
            finally:
                first_done.set()

        worker = threading.Thread(target=hold_first, daemon=True)
        worker.start()
        self.assertTrue(first_ready.wait(5))
        with client.websocket_connect(
            f"/api/live/sessions/{session_id}/stream?ticket={body['ticket']}"
        ) as socket:
            socket.send_json({"type": "hello", "sample_rate": 16000})
            self.assertEqual(socket.receive_json()["type"], "hello_ok")
            self.assertEqual(socket.receive_json()["text"], "đang mở")
            socket.send_bytes(second_frame)
            publish_live(session_id, {"type": "draft", "text": "câu mới", "stable": False})
            self.assertEqual(socket.receive_json()["text"], "câu mới")
            socket.send_json({"type": "stop"})
            self.assertEqual(socket.receive_json()["type"], "stopped")
        self.assertTrue(first_done.wait(5))
        worker.join(2)
        with Session(get_engine()) as db:
            session = db.get(LiveSession, uuid.UUID(session_id))
            assert session is not None
            pcm = Path(session.pcm_path).read_bytes()
        self.assertIn(second_frame, pcm)
        self.assertEqual(pcm.replace(first_frame, b"").replace(second_frame, b""), b"")

    def test_voice_profile_limits_stale_and_delete(self) -> None:
        voice_routes.probe_sample = lambda _path: (30_000, 20_000)
        created = client.post(
            "/api/voice-profiles",
            headers=auth(self.token),
            files={"file": ("mau.wav", b"RIFF", "application/octet-stream")},
            data={"display_name": " Lan "},
        )
        self.assertEqual(created.status_code, 202, created.text)
        profile_id = created.json()["profile_id"]
        with Session(get_engine()) as db:
            row = db.get(VoiceProfile, uuid.UUID(profile_id))
            assert row is not None
            sample = Path(row.sample_path)
            self.assertTrue(sample.is_file())
            user_id = row.user_id
            now = datetime.now(timezone.utc)
            db.add(
                VoiceProfile(
                    user_id=user_id,
                    display_name="Cũ",
                    status="ready",
                    embedding_model="pipeline-cũ",
                    created_at=now,
                )
            )
            db.commit()
        listed = client.get("/api/voice-profiles", headers=auth(self.token)).json()["items"]
        stale = {item["display_name"]: item["stale"] for item in listed}
        self.assertFalse(stale["Lan"])
        self.assertTrue(stale["Cũ"])
        other = register("b@example.com")
        hidden = client.get(f"/api/voice-profiles/{profile_id}", headers=auth(other))
        self.assertEqual(hidden.status_code, 404)
        voice_routes.probe_sample = lambda _path: (10_000, 10_000)
        short = client.post(
            "/api/voice-profiles",
            headers=auth(self.token),
            files={"file": ("ngan.wav", b"RIFF", "application/octet-stream")},
            data={"display_name": "Ngắn"},
        )
        self.assertEqual(short.status_code, 422)
        self.assertEqual(short.json()["error"]["fields"]["file"], "Mẫu giọng phải dài từ 20 đến 40 giây.")
        with Session(get_engine()) as db:
            user_id = db.query(VoiceProfile).first().user_id
            now = datetime.now(timezone.utc)
            for index in range(18):
                db.add(
                    VoiceProfile(
                        user_id=user_id,
                        display_name=f"mẫu {index}",
                        status="ready",
                        created_at=now,
                    )
                )
            db.commit()
            self.assertEqual(db.query(VoiceProfile).count(), 20)
        voice_routes.probe_sample = lambda _path: (30_000, 20_000)
        full = client.post(
            "/api/voice-profiles",
            headers=auth(self.token),
            files={"file": ("them.wav", b"RIFF", "application/octet-stream")},
            data={"display_name": "Thêm"},
        )
        self.assertEqual(full.status_code, 422)
        self.assertEqual(full.json()["error"]["message"], "Mỗi tài khoản chỉ có tối đa 20 hồ sơ giọng.")
        deleted = client.delete(f"/api/voice-profiles/{profile_id}", headers=auth(self.token))
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(sample.exists())
        self.assertEqual(client.get(f"/api/voice-profiles/{profile_id}", headers=auth(self.token)).status_code, 404)

    def test_voice_upload_stops_past_the_byte_cap(self) -> None:
        os.environ["MAX_VOICE_BYTES"] = "4"
        get_settings.cache_clear()
        try:
            voice_routes.probe_sample = lambda _path: (_ for _ in ()).throw(AssertionError("không được đo file quá lớn"))
            huge = client.post(
                "/api/voice-profiles",
                headers=auth(self.token),
                files={"file": ("to.wav", b"0123456789", "application/octet-stream")},
                data={"display_name": "To"},
            )
        finally:
            os.environ["MAX_VOICE_BYTES"] = "33554432"
            get_settings.cache_clear()
            voice_routes.probe_sample = ORIGINAL_PROBE
        self.assertEqual(huge.status_code, 413)
        self.assertEqual(huge.json()["error"]["code"], "file_too_large")

    def test_rate_limit_window(self) -> None:
        window = SlidingWindow(2)
        window.hit("rieng")
        window.hit("rieng")
        with self.assertRaises(ApiError) as caught:
            window.hit("rieng")
        self.assertEqual(caught.exception.status_code, 429)
        window._hits["khach"] = [0.0]
        window.hit("khac")
        self.assertNotIn("khach", window._hits)
