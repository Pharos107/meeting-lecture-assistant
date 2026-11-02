"""Hỏi đáp về transcript: ngữ cảnh, stream, lỗi, và lịch sử."""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "t" * 32
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="stt-chat-")
os.environ["REDIS_URL"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["LLM_API_KEY"] = "test-key"

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.routes_chat as chat_routes
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.db import get_engine
from app.main import app
from app.models import (
    ActionItem,
    Base,
    ChatMessage,
    Highlight,
    Job,
    JobEvent,
    LiveSession,
    MediaToken,
    RefreshToken,
    Segment,
    SpeakerAlias,
    User,
    VoiceProfile,
    Word,
    WsTicket,
)
from app.services.chat_service import build_messages, clock, history_messages
from app.services.llm_client import LlmRateLimited, LlmTimeout, LlmUpstream, stream_chat

get_settings.cache_clear()
Base.metadata.create_all(get_engine())
client = TestClient(app)
ORIGINAL_STREAM = chat_routes.stream_chat


def clear_rows() -> None:
    with Session(get_engine()) as db:
        for model in (
            Word,
            Highlight,
            ActionItem,
            Segment,
            SpeakerAlias,
            JobEvent,
            ChatMessage,
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
            if line.startswith("event: "):
                item["event"] = line[7:]
            elif line.startswith("data: "):
                item["data"] = json.loads(line[6:])
        frames.append(item)
    return frames


def fake_stream(*texts: str, error: Exception | None = None):
    """Thay stream_chat, ghi lại messages đã gửi."""
    seen: list[list[dict]] = []

    async def stream(messages):
        seen.append(messages)
        for text in texts:
            yield text
        if error is not None:
            raise error

    return stream, seen


class ChatTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["LLM_MODEL"] = "test-model"
        os.environ.pop("LLM_MAX_CONTEXT_TOKENS", None)
        get_settings.cache_clear()
        clear_rows()
        self.token = register("a@example.com")

    def tearDown(self) -> None:
        chat_routes.stream_chat = ORIGINAL_STREAM
        os.environ["LLM_MODEL"] = ""
        os.environ.pop("LLM_MAX_CONTEXT_TOKENS", None)
        get_settings.cache_clear()

    def _ready_job(self) -> str:
        job_id = upload(self.token)
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "ready"
            job.vocabulary = "pyannote"
            db.add_all(
                [
                    Segment(
                        job_id=job.id,
                        pass_index=2,
                        position=0,
                        start_ms=64_000,
                        end_ms=70_000,
                        text_raw="chữ gốc",
                        text_edited="Câu đã sửa.",
                        speaker_label="SPEAKER_00",
                    ),
                    Segment(
                        job_id=job.id,
                        pass_index=2,
                        position=1,
                        start_ms=71_000,
                        end_ms=75_000,
                        text_raw="Câu thứ hai.",
                        speaker_label=None,
                    ),
                    SpeakerAlias(job_id=job.id, speaker_label="SPEAKER_00", display_name="Chị Lan", source="manual"),
                ]
            )
            db.commit()
        return job_id

    def _ask(self, job_id: str, question: str = "Có những nhiệm vụ gì?"):
        return client.post(f"/api/jobs/{job_id}/chat/messages", headers=auth(self.token), json={"question": question})

    def _messages(self, job_id: str) -> list[dict]:
        response = client.get(f"/api/jobs/{job_id}/chat/messages", headers=auth(self.token))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def test_answer_streams_and_is_saved(self) -> None:
        job_id = self._ready_job()
        chat_routes.stream_chat, seen = fake_stream("Có ", "một việc [01:04].")
        response = self._ask(job_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        frames = parse_sse(response.text)
        self.assertEqual([frame["event"] for frame in frames], ["start", "delta", "delta", "done"])
        self.assertEqual(frames[-1]["data"]["model"], "test-model")

        sent = seen[0]
        self.assertEqual([message["role"] for message in sent], ["system", "user", "assistant", "user"])
        self.assertIn("Không bịa", sent[0]["content"])
        self.assertIn("Thuật ngữ của buổi này: pyannote", sent[1]["content"])
        self.assertIn("[01:04] Chị Lan: Câu đã sửa.", sent[1]["content"])
        self.assertIn("[01:11] Chưa rõ người nói: Câu thứ hai.", sent[1]["content"])
        self.assertNotIn("chữ gốc", sent[1]["content"])
        self.assertEqual(sent[-1]["content"], "Có những nhiệm vụ gì?")

        items = self._messages(job_id)
        self.assertEqual([item["role"] for item in items], ["user", "assistant"])
        self.assertEqual(items[1]["content"], "Có một việc [01:04].")
        self.assertEqual(items[1]["status"], "done")

    def test_only_done_turns_enter_history(self) -> None:
        job_id = self._ready_job()
        chat_routes.stream_chat, _ = fake_stream("Trả lời một.")
        self._ask(job_id, "Câu một?")
        chat_routes.stream_chat, _ = fake_stream("Dở", error=LlmUpstream("lỗi"))
        self._ask(job_id, "Câu hai?")
        chat_routes.stream_chat, seen = fake_stream("Trả lời ba.")
        self._ask(job_id, "Câu ba?")
        contents = [message["content"] for message in seen[0]]
        self.assertIn("Câu một?", contents)
        self.assertIn("Trả lời một.", contents)
        self.assertNotIn("Câu hai?", contents)
        self.assertNotIn("Dở", contents)

    def test_history_keeps_last_six_turns(self) -> None:
        rows = []
        for index in range(8):
            rows.append(ChatMessage(role="user", content=f"hỏi {index}", status="done"))
            rows.append(ChatMessage(role="assistant", content=f"đáp {index}", status="done"))
        history = history_messages(rows)
        self.assertEqual(len(history), 12)
        self.assertEqual(history[0]["content"], "hỏi 2")
        self.assertEqual(history[-1]["content"], "đáp 7")

    def test_clock_uses_hours_on_long_recordings(self) -> None:
        self.assertEqual(clock(64_000, False), "01:04")
        self.assertEqual(clock(3_725_000, True), "01:02:05")

    def test_errors_before_calling_llm(self) -> None:
        queued = upload(self.token)
        self.assertEqual(self._ask(queued).json()["error"]["code"], "invalid_state")

        job_id = self._ready_job()
        chat_routes.stream_chat, seen = fake_stream("không được gọi")
        empty = self._ask(job_id, "   ")
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(empty.json()["error"]["code"], "validation")
        self.assertEqual(self._ask(job_id, "x" * 2001).status_code, 422)

        os.environ["LLM_MODEL"] = ""
        get_settings.cache_clear()
        missing = self._ask(job_id)
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["error"]["code"], "llm_not_configured")

        os.environ["LLM_MODEL"] = "test-model"
        os.environ["LLM_API_KEY"] = ""
        get_settings.cache_clear()
        self.assertEqual(self._ask(job_id).json()["error"]["code"], "llm_not_configured")
        os.environ["LLM_API_KEY"] = "test-key"

        os.environ["LLM_MODEL"] = "test-model"
        os.environ["LLM_MAX_CONTEXT_TOKENS"] = "100"
        get_settings.cache_clear()
        exceeded = self._ask(job_id)
        self.assertEqual(exceeded.status_code, 422)
        self.assertEqual(exceeded.json()["error"]["code"], "llm_context_exceeded")

        self.assertEqual(seen, [])
        self.assertEqual(self._messages(job_id), [])

    def test_error_midway_keeps_partial_answer(self) -> None:
        job_id = self._ready_job()
        chat_routes.stream_chat, _ = fake_stream("Phần đầu", error=LlmTimeout("hết hạn"))
        frames = parse_sse(self._ask(job_id).text)
        self.assertEqual(frames[-1]["event"], "error")
        self.assertEqual(frames[-1]["data"]["code"], "llm_timeout")
        answer = self._messages(job_id)[-1]
        self.assertEqual(answer["status"], "failed")
        self.assertEqual(answer["error_code"], "llm_timeout")
        self.assertEqual(answer["content"], "Phần đầu")

    def test_quota_error_has_its_own_message(self) -> None:
        job_id = self._ready_job()
        chat_routes.stream_chat, _ = fake_stream(error=LlmRateLimited("hết lượt"))
        frames = parse_sse(self._ask(job_id).text)
        self.assertEqual(frames[-1]["data"]["code"], "llm_rate_limited")
        self.assertIn("hết lượt", frames[-1]["data"]["message"])
        self.assertEqual(self._messages(job_id)[-1]["error_code"], "llm_rate_limited")

    def _add_streaming(self, job_id: str, age_seconds: int) -> None:
        moment = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        with Session(get_engine()) as db:
            db.add(
                ChatMessage(
                    job_id=uuid.UUID(job_id),
                    role="assistant",
                    content="dở",
                    status="streaming",
                    created_at=moment,
                    updated_at=moment,
                )
            )
            db.commit()

    def test_one_answer_at_a_time(self) -> None:
        job_id = self._ready_job()
        self._add_streaming(job_id, 0)
        chat_routes.stream_chat, seen = fake_stream("không được gọi")
        busy = self._ask(job_id)
        self.assertEqual(busy.status_code, 409)
        self.assertEqual(busy.json()["error"]["code"], "chat_busy")
        cleared = client.delete(f"/api/jobs/{job_id}/chat/messages", headers=auth(self.token))
        self.assertEqual(cleared.json()["error"]["code"], "chat_busy")
        self.assertEqual(seen, [])

    def test_stale_streaming_row_counts_as_failed(self) -> None:
        job_id = self._ready_job()
        self._add_streaming(job_id, 500)
        self.assertEqual(self._messages(job_id)[0]["status"], "failed")
        chat_routes.stream_chat, _ = fake_stream("Được.")
        self.assertEqual(self._ask(job_id).status_code, 200)

    def test_clear_retry_and_isolation(self) -> None:
        job_id = self._ready_job()
        chat_routes.stream_chat, _ = fake_stream("Trả lời.")
        self._ask(job_id)

        other = register("b@example.com")
        self.assertEqual(client.get(f"/api/jobs/{job_id}/chat/messages", headers=auth(other)).status_code, 404)
        foreign = client.post(f"/api/jobs/{job_id}/chat/messages", headers=auth(other), json={"question": "Xem trộm?"})
        self.assertEqual(foreign.status_code, 404)

        cleared = client.delete(f"/api/jobs/{job_id}/chat/messages", headers=auth(self.token))
        self.assertEqual(cleared.status_code, 204)
        self.assertEqual(self._messages(job_id), [])

        self._ask(job_id)
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "failed"
            db.commit()
        retried = client.post(f"/api/jobs/{job_id}/retry", headers=auth(self.token))
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(self._messages(job_id), [])

    def test_context_has_no_turns_when_transcript_is_empty(self) -> None:
        job_id = upload(self.token)
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            with self.assertRaises(ApiError) as caught:
                build_messages(db, job, "Hỏi gì?")
        self.assertEqual(caught.exception.code, "invalid_state")


def collect(transport: httpx.AsyncBaseTransport) -> list[str]:
    async def run() -> list[str]:
        return [text async for text in stream_chat([{"role": "user", "content": "xin chào"}], transport=transport)]

    return asyncio.run(run())


class LlmClientTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["LLM_MODEL"] = "test-model"
        os.environ["LLM_BASE_URL"] = "http://llm.test/v1"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ["LLM_MODEL"] = ""
        os.environ.pop("LLM_BASE_URL", None)
        get_settings.cache_clear()

    def test_reads_delta_chunks(self) -> None:
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            self.assertEqual(str(request.url), "http://llm.test/v1/chat/completions")
            lines = [
                'data: {"choices":[{"delta":{"role":"assistant"}}]}',
                ": ping",
                'data: {"choices":[{"delta":{"content":"Xin "}}]}',
                'data: {"choices":[{"delta":{"content":"chào"}}]}',
                "data: không phải json",
                "data: [DONE]",
            ]
            return httpx.Response(200, text="\n\n".join(lines))

        self.assertEqual(collect(httpx.MockTransport(handler)), ["Xin ", "chào"])
        self.assertTrue(bodies[0]["stream"])
        self.assertEqual(bodies[0]["model"], "test-model")

    def test_maps_errors(self) -> None:
        def refused(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        def timed_out(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("chậm")

        with self.assertRaises(LlmUpstream):
            collect(httpx.MockTransport(refused))
        with self.assertRaises(LlmTimeout):
            collect(httpx.MockTransport(timed_out))
        with self.assertRaises(LlmUpstream):
            collect(httpx.MockTransport(lambda _request: httpx.Response(500)))
        with self.assertRaises(LlmRateLimited):
            collect(httpx.MockTransport(lambda _request: httpx.Response(429)))
