"""Liên kết chia sẻ transcript: bật, tắt, quyền, và phần người xem nhận được."""

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "t" * 32
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="stt-share-")
os.environ["REDIS_URL"] = ""
os.environ["LLM_MODEL"] = ""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import share_views
from app.services.gpu_lock import _memory, keeper
from app.services.live_channel import put_open_draft, reset_live_channel
from app.db import get_engine
from app.api import routes_share as share_routes
from app.main import app
from app.models import (
    ActionItem,
    Base,
    ChatMessage,
    Highlight,
    Job,
    JobEvent,
    JobShare,
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

get_settings.cache_clear()
Base.metadata.create_all(get_engine())
client = TestClient(app)


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
            JobShare,
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


def set_status(job_id: str, status: str) -> None:
    with Session(get_engine()) as db:
        db.get(Job, uuid.UUID(job_id)).status = status
        db.commit()


def add_transcript(job_id: str) -> None:
    job = uuid.UUID(job_id)
    with Session(get_engine()) as db:
        db.add(SpeakerAlias(job_id=job, speaker_label="SPEAKER_00", display_name="Cô Lan", source="manual"))
        first = Segment(job_id=job, pass_index=2, position=0, start_ms=0, end_ms=1000, text_raw="xin chào", speaker_label="SPEAKER_00")
        second = Segment(
            job_id=job,
            pass_index=2,
            position=1,
            start_ms=1000,
            end_ms=2000,
            text_raw="bản gốc",
            text_edited="bản đã sửa",
            speaker_label="SPEAKER_01",
        )
        draft = Segment(job_id=job, pass_index=1, position=0, start_ms=0, end_ms=2000, text_raw="bản nháp")
        db.add_all([first, second, draft])
        db.flush()
        db.add(Word(segment_id=first.id, position=0, text="xin", start_ms=0, end_ms=500))
        db.add(
            Highlight(
                job_id=job,
                segment_id=first.id,
                quote="xin",
                start_ms=0,
                end_ms=500,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()


class ShareTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_rows()
        reset_live_channel()
        self.token = register("a@example.com")
        self.job_id = upload(self.token)
        self.url = f"/api/jobs/{self.job_id}/share"

    def tearDown(self) -> None:
        # Phiên nghe thử giữ khóa GPU trong bộ nhớ. Nhả để test sau còn lấy được khóa.
        keeper.stop_all()
        _memory.owner = None
        _memory.deadline = 0.0

    def enable(self) -> str:
        set_status(self.job_id, "ready")
        response = client.put(self.url, headers=auth(self.token))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def test_starts_disabled(self) -> None:
        response = client.get(self.url, headers=auth(self.token))
        self.assertEqual(response.json(), {"enabled": False, "token": None, "url": None})

    def test_needs_ready_job(self) -> None:
        response = client.put(self.url, headers=auth(self.token))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "invalid_state")

    def test_enable_is_idempotent(self) -> None:
        token = self.enable()
        again = client.put(self.url, headers=auth(self.token)).json()
        shown = client.get(self.url, headers=auth(self.token)).json()
        self.assertEqual(again["token"], token)
        self.assertEqual(shown, {"enabled": True, "token": token, "url": f"/shared/{token}"})

    def test_disable_kills_the_link_and_reenable_issues_a_new_one(self) -> None:
        old = self.enable()
        self.assertEqual(client.get(f"/api/shared/{old}").status_code, 200)
        self.assertEqual(client.delete(self.url, headers=auth(self.token)).status_code, 204)
        self.assertEqual(client.get(f"/api/shared/{old}").status_code, 404)
        self.assertEqual(client.delete(self.url, headers=auth(self.token)).status_code, 204)
        fresh = self.enable()
        self.assertNotEqual(fresh, old)
        self.assertEqual(client.get(f"/api/shared/{old}").status_code, 404)
        self.assertEqual(client.get(f"/api/shared/{fresh}").status_code, 200)

    def test_owner_endpoints_need_login(self) -> None:
        self.assertEqual(client.get(self.url).status_code, 401)
        self.assertEqual(client.put(self.url).status_code, 401)
        self.assertEqual(client.delete(self.url).status_code, 401)

    def test_other_user_gets_404(self) -> None:
        token = self.enable()
        other = auth(register("b@example.com"))
        self.assertEqual(client.get(self.url, headers=other).status_code, 404)
        self.assertEqual(client.put(self.url, headers=other).status_code, 404)
        self.assertEqual(client.delete(self.url, headers=other).status_code, 404)
        self.assertEqual(client.get(f"/api/shared/{token}").status_code, 200)

    def test_public_view_has_only_the_transcript(self) -> None:
        add_transcript(self.job_id)
        token = self.enable()
        response = client.get(f"/api/shared/{token}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(sorted(body), ["created_at", "duration_ms", "segments", "state", "title"])
        self.assertEqual(body["state"], "ready")
        self.assertEqual(
            body["segments"],
            [
                {"start_ms": 0, "end_ms": 1000, "text": "xin chào", "speaker": "Cô Lan"},
                {"start_ms": 1000, "end_ms": 2000, "text": "bản đã sửa", "speaker": "SPEAKER_01"},
            ],
        )
        self.assertNotIn(self.job_id, response.text)
        self.assertNotIn("a@example.com", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-robots-tag"], "noindex")

    def test_link_pauses_while_job_is_not_ready(self) -> None:
        token = self.enable()
        set_status(self.job_id, "failed")
        self.assertEqual(client.get(f"/api/shared/{token}").status_code, 404)
        set_status(self.job_id, "ready")
        self.assertEqual(client.get(f"/api/shared/{token}").status_code, 200)

    def test_deleted_job_ends_the_link(self) -> None:
        token = self.enable()
        self.assertEqual(client.delete(f"/api/jobs/{self.job_id}", headers=auth(self.token)).status_code, 204)
        self.assertEqual(client.get(f"/api/shared/{token}").status_code, 404)

    def _live_job(self) -> tuple[str, str]:
        _memory.owner = None
        _memory.deadline = 0.0
        created = client.post("/api/live/sessions", headers=auth(self.token), json={"title": "Buổi học"})
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        keeper.stop_all()
        with Session(get_engine()) as db:
            db.add(Segment(id=uuid.UUID(int=7), job_id=uuid.UUID(body["job_id"]), pass_index=1, position=0,
                           start_ms=500, end_ms=2500, text_raw="câu nháp đã chốt"))
            db.commit()
        return body["job_id"], body["session_id"]

    def test_live_job_is_shared_while_capturing(self) -> None:
        job_id, _session_id = self._live_job()
        token = client.put(f"/api/jobs/{job_id}/share", headers=auth(self.token)).json()["token"]
        body = client.get(f"/api/shared/{token}").json()
        self.assertEqual(body["state"], "live")
        self.assertEqual([segment["text"] for segment in body["segments"]], ["câu nháp đã chốt"])
        set_status(job_id, "transcribing")
        self.assertEqual(client.get(f"/api/shared/{token}").json()["state"], "processing")
        set_status(job_id, "cancelled")
        self.assertEqual(client.get(f"/api/shared/{token}").status_code, 404)

    def test_live_stream_sends_closed_and_open_drafts(self) -> None:
        job_id, session_id = self._live_job()
        token = client.put(f"/api/jobs/{job_id}/share", headers=auth(self.token)).json()["token"]
        put_open_draft(session_id, {"type": "draft", "segment_id": "mo", "start_ms": 3000, "end_ms": 4000,
                                    "text": "đang nói", "stable": False, "seq": 9})
        os.environ["STT_SSE_ONCE"] = "1"
        try:
            response = client.get(f"/api/shared/{token}/live")
        finally:
            os.environ.pop("STT_SSE_ONCE", None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-robots-tag"], "noindex")
        frames = [block for block in response.text.split("\n\n") if block.startswith("event:")]
        self.assertEqual([block.split("\n")[0] for block in frames], ["event: snapshot", "event: draft"])
        self.assertIn("câu nháp đã chốt", frames[0])
        self.assertIn('"text":"đang nói"', frames[1])
        self.assertNotIn("seq", frames[1])
        self.assertNotIn(job_id, response.text)
        self.assertNotIn(session_id, response.text)

    def test_live_stream_closes_when_share_is_turned_off(self) -> None:
        job_id, _session_id = self._live_job()
        token = client.put(f"/api/jobs/{job_id}/share", headers=auth(self.token)).json()["token"]
        self.assertTrue(share_routes._still_shared_and_capturing(token, uuid.UUID(job_id)))
        self.assertEqual(client.delete(f"/api/jobs/{job_id}/share", headers=auth(self.token)).status_code, 204)
        self.assertFalse(share_routes._still_shared_and_capturing(token, uuid.UUID(job_id)))
        fresh = client.put(f"/api/jobs/{job_id}/share", headers=auth(self.token)).json()["token"]
        self.assertFalse(share_routes._still_shared_and_capturing(token, uuid.UUID(job_id)))
        self.assertTrue(share_routes._still_shared_and_capturing(fresh, uuid.UUID(job_id)))

    def test_live_stream_needs_a_capturing_job(self) -> None:
        token = self.enable()
        self.assertEqual(client.get(f"/api/shared/{token}/live").status_code, 404)
        self.assertEqual(client.get("/api/shared/khong-co/live").status_code, 404)

    def test_unknown_token_is_404(self) -> None:
        self.assertEqual(client.get("/api/shared/khong-co").status_code, 404)

    def test_public_view_is_rate_limited(self) -> None:
        token = self.enable()
        limit = share_views.limit
        share_views.limit = 1
        try:
            share_views._hits.clear()
            self.assertEqual(client.get(f"/api/shared/{token}").status_code, 200)
            response = client.get(f"/api/shared/{token}")
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()["error"]["code"], "rate_limited")
        finally:
            share_views.limit = limit
            share_views._hits.clear()


if __name__ == "__main__":
    unittest.main()
