"""Hợp đồng job, transcript, đánh dấu, và nghe lại."""

import os
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "t" * 32
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="stt-jobs-")

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.gpu_lock import keeper
from app.services.live_channel import reset_live_channel
from app.services.live_heartbeat import clear_heartbeats
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

get_settings.cache_clear()
Base.metadata.create_all(get_engine())
client = TestClient(app)
DATA = Path(os.environ["DATA_DIR"])


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


def upload(token: str, content: bytes, name: str, **fields: str):
    return client.post(
        "/api/jobs",
        headers=auth(token),
        files={"file": (name, content, "application/octet-stream")},
        data=fields,
    )


class JobTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DATA_DIR"] = str(DATA)
        os.environ["REDIS_URL"] = ""
        os.environ["LLM_MODEL"] = ""
        get_settings.cache_clear()
        keeper.stop_all()
        clear_heartbeats()
        reset_live_channel()
        clear_rows()
        self.token = register("a@example.com")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(DATA, ignore_errors=True)

    def test_upload_list_and_owner(self) -> None:
        created = upload(self.token, b"abc", "hop sprint.mp3", vocabulary="FastAPI", num_speakers="2")
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["status"], "queued")
        job_id = body["job_id"]

        listed = client.get("/api/jobs", headers=auth(self.token))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["title"], "hop sprint")
        self.assertIsNone(listed.json()["next_cursor"])

        detail = client.get(f"/api/jobs/{job_id}", headers=auth(self.token))
        self.assertEqual(detail.json()["vocabulary"], "FastAPI")
        self.assertEqual(detail.json()["num_speakers"], 2)
        self.assertEqual(detail.json()["source"], "upload")

        other = register("b@example.com")
        hidden = client.get(f"/api/jobs/{job_id}", headers=auth(other))
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(client.get("/api/jobs", headers=auth(other)).json()["items"], [])

        second = upload(self.token, b"abc", "hai.mp3")
        third = upload(self.token, b"abc", "ba.mp3")
        self.assertEqual(second.status_code, 201)
        self.assertEqual(third.status_code, 201)
        page = client.get("/api/jobs?limit=2", headers=auth(self.token))
        self.assertEqual(len(page.json()["items"]), 2)
        cursor = page.json()["next_cursor"]
        rest = client.get(f"/api/jobs?limit=2&cursor={cursor}", headers=auth(self.token))
        self.assertEqual(len(rest.json()["items"]), 1)
        self.assertIsNone(rest.json()["next_cursor"])
        seen = {item["id"] for item in page.json()["items"] + rest.json()["items"]}
        self.assertEqual(len(seen), 3)

        with Session(get_engine()) as db:
            rows = list(db.query(Job).all())
            stamp = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
            for row in rows:
                row.created_at = stamp
            db.commit()
            ordered = [str(row.id) for row in sorted(rows, key=lambda row: row.id, reverse=True)]
        tied = client.get("/api/jobs?limit=1", headers=auth(self.token))
        self.assertEqual(tied.json()["items"][0]["id"], ordered[0])
        tied_rest = client.get(
            f"/api/jobs?limit=10&cursor={tied.json()['next_cursor']}",
            headers=auth(self.token),
        )
        self.assertEqual([item["id"] for item in tied_rest.json()["items"]], ordered[1:])

    def test_upload_validation_and_size(self) -> None:
        long_title = upload(self.token, b"abc", "a.mp3", title="x" * 201)
        self.assertEqual(long_title.status_code, 422)
        self.assertIn("title", long_title.json()["error"]["fields"])

        bad = upload(self.token, b"abc", "ghi-chu.txt")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["fields"]["file"], "Định dạng file không được hỗ trợ.")

        os.environ["MAX_OPUS_BYTES"] = "4"
        get_settings.cache_clear()
        try:
            huge = upload(self.token, b"12345", "a.opus")
        finally:
            os.environ["MAX_OPUS_BYTES"] = "67108864"
            get_settings.cache_clear()
        self.assertEqual(huge.status_code, 413)
        self.assertEqual(huge.json()["error"]["code"], "file_too_large")

    def test_cancel_retry_and_delete(self) -> None:
        job_id = upload(self.token, b"abc", "hop.mp3").json()["job_id"]
        cancelled = client.post(f"/api/jobs/{job_id}/cancel", headers=auth(self.token))
        self.assertEqual(cancelled.status_code, 202)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        again = client.post(f"/api/jobs/{job_id}/retry", headers=auth(self.token))
        self.assertEqual(again.status_code, 409)

        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "failed"
            job.error_code = "gpu_oom"
            kept = Segment(
                job_id=job.id,
                pass_index=1,
                position=0,
                start_ms=0,
                end_ms=1000,
                text_raw="nháp",
            )
            dropped = Segment(
                job_id=job.id,
                pass_index=2,
                position=0,
                start_ms=0,
                end_ms=1000,
                text_raw="chuẩn",
            )
            db.add(kept)
            db.add(dropped)
            db.flush()
            db.add(Word(segment_id=dropped.id, position=0, text="chuẩn", start_ms=0, end_ms=1000))
            db.add(
                VoiceProfile(
                    user_id=job.user_id,
                    display_name="An",
                    status="ready",
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            kept_id = kept.id

        queued: list[tuple[str, str]] = []

        def capture(name: str, argument: str) -> None:
            queued.append((name, argument))

        import app.api.routes_jobs as jobs_api

        original = jobs_api.enqueue
        jobs_api.enqueue = capture
        try:
            retried = client.post(f"/api/jobs/{job_id}/retry", headers=auth(self.token))
        finally:
            jobs_api.enqueue = original
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(queued, [("app.tasks.transcribe_upload", job_id)])
        self.assertEqual(retried.json()["status"], "queued")
        self.assertIsNone(retried.json()["error_code"])
        transcript = client.get(f"/api/jobs/{job_id}/transcript", headers=auth(self.token))
        self.assertEqual(transcript.json()["pass"], 1)
        self.assertEqual(transcript.json()["segments"][0]["text_raw"], "nháp")

        blocked = client.post(f"/api/jobs/{job_id}/cancel", headers=auth(self.token))
        self.assertEqual(blocked.status_code, 202)
        ready_retry = client.post(f"/api/jobs/{job_id}/retry", headers=auth(self.token))
        self.assertEqual(ready_retry.status_code, 409)

        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "ready"
            db.commit()
        self.assertEqual(client.post(f"/api/jobs/{job_id}/cancel", headers=auth(self.token)).status_code, 409)

        self.assertTrue((DATA / "tmp" / job_id).is_dir())
        deleted = client.delete(f"/api/jobs/{job_id}", headers=auth(self.token))
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")
        self.assertEqual(client.get(f"/api/jobs/{job_id}", headers=auth(self.token)).status_code, 404)
        self.assertFalse((DATA / "tmp" / job_id).exists())
        with Session(get_engine()) as db:
            self.assertIsNone(db.get(Segment, kept_id))
            self.assertEqual(db.query(VoiceProfile).count(), 1)

    def test_transcript_marks_and_actions(self) -> None:
        job_id = upload(self.token, b"abc", "hop.mp3").json()["job_id"]
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.status = "ready"
            segment = Segment(
                job_id=job.id,
                pass_index=2,
                position=0,
                start_ms=1000,
                end_ms=4000,
                text_raw="Hôm nay",
                speaker_label="SPEAKER_00",
            )
            db.add(segment)
            db.flush()
            db.add(Word(segment_id=segment.id, position=0, text="Hôm", start_ms=1000, end_ms=1500, speaker_label="SPEAKER_00"))
            db.add(Word(segment_id=segment.id, position=1, text="nay", start_ms=1500, end_ms=2000, speaker_label="SPEAKER_00"))
            db.commit()
            segment_id = str(segment.id)

        renamed = client.patch(
            f"/api/jobs/{job_id}/speakers/SPEAKER_00",
            headers=auth(self.token),
            json={"display_name": " An "},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["source"], "manual")
        transcript = client.get(f"/api/jobs/{job_id}/transcript", headers=auth(self.token)).json()
        self.assertEqual(transcript["pass"], 2)
        self.assertEqual(transcript["segments"][0]["speaker_name"], "An")
        self.assertEqual(transcript["segments"][0]["words"][0]["text"], "Hôm")
        self.assertEqual(transcript["speakers"][0]["display_name"], "An")

        edited = client.patch(
            f"/api/jobs/{job_id}/segments/{segment_id}",
            headers=auth(self.token),
            json={"text_edited": "Hôm nay họp."},
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["text_edited"], "Hôm nay họp.")
        cleared = client.patch(
            f"/api/jobs/{job_id}/segments/{segment_id}",
            headers=auth(self.token),
            json={"text_edited": None},
        )
        self.assertIsNone(cleared.json()["text_edited"])

        cleared_name = client.patch(
            f"/api/jobs/{job_id}/speakers/SPEAKER_00",
            headers=auth(self.token),
            json={"display_name": "  "},
        )
        self.assertEqual(cleared_name.json()["display_name"], "SPEAKER_00")
        self.assertIsNone(cleared_name.json()["source"])

        outside = client.post(
            f"/api/jobs/{job_id}/highlights",
            headers=auth(self.token),
            json={"segment_id": segment_id, "quote": "ngoài", "start_ms": 9000, "end_ms": 9500},
        )
        self.assertEqual(outside.status_code, 422)

        mark = client.post(
            f"/api/jobs/{job_id}/highlights",
            headers=auth(self.token),
            json={"segment_id": segment_id, "quote": " Hôm nay ", "start_ms": 1000, "end_ms": 2000},
        )
        self.assertEqual(mark.status_code, 201)
        self.assertEqual(mark.json()["quote"], "Hôm nay")

        queued = upload(self.token, b"abc", "khac.mp3").json()["job_id"]
        denied = client.post(
            f"/api/jobs/{queued}/actions",
            headers=auth(self.token),
            json={"segment_id": segment_id, "task": "Việc"},
        )
        self.assertEqual(denied.status_code, 409)

        action = client.post(
            f"/api/jobs/{job_id}/actions",
            headers=auth(self.token),
            json={"segment_id": segment_id, "task": " Gửi biên bản ", "owner": "An", "deadline": ""},
        )
        self.assertEqual(action.status_code, 201)
        self.assertEqual(action.json()["task"], "Gửi biên bản")
        self.assertEqual(action.json()["start_ms"], 1000)
        self.assertEqual(action.json()["source"], "manual")
        listed = client.get(f"/api/jobs/{job_id}/actions", headers=auth(self.token))
        self.assertEqual(len(listed.json()["items"]), 1)

    def test_media_token_range_and_expiry(self) -> None:
        job_id = upload(self.token, b"abc", "hop.mp3").json()["job_id"]
        audio = DATA / "audio" / f"{job_id}.opus"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"abcdefghij")
        with Session(get_engine()) as db:
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.audio_path = str(audio)
            db.commit()

        issued = client.post(f"/api/jobs/{job_id}/media-token", headers=auth(self.token))
        self.assertEqual(issued.status_code, 200)
        token = issued.json()["token"]
        self.assertEqual(issued.json()["expires_in"], 300)
        first = client.get(f"/api/media/{token}")
        second = client.get(f"/api/media/{token}")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, b"abcdefghij")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.headers["content-type"], "audio/ogg")
        partial = client.get(f"/api/media/{token}", headers={"Range": "bytes=2-5"})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, b"cdef")
        self.assertEqual(partial.headers["content-range"], "bytes 2-5/10")

        with Session(get_engine()) as db:
            row = db.query(MediaToken).one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        expired = client.get(f"/api/media/{token}")
        self.assertEqual(expired.status_code, 404)


if __name__ == "__main__":
    unittest.main()
