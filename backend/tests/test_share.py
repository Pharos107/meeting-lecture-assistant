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
from app.db import get_engine
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
        self.token = register("a@example.com")
        self.job_id = upload(self.token)
        self.url = f"/api/jobs/{self.job_id}/share"

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
        self.assertEqual(sorted(body), ["created_at", "duration_ms", "segments", "title"])
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
