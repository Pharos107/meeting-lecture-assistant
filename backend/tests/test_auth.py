"""Hợp đồng đăng ký và đăng nhập."""

import os
import unittest
import uuid

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "t" * 32
os.environ["ACCESS_TOKEN_MINUTES"] = "15"
os.environ["REFRESH_TOKEN_DAYS"] = "7"

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.main import app
from app.models import Base, RefreshToken, User

Base.metadata.create_all(get_engine())
client = TestClient(app)


def clear_rows() -> None:
    with Session(get_engine()) as db:
        db.query(RefreshToken).delete()
        db.query(User).delete()
        db.commit()


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_rows()

    def test_register_then_login(self) -> None:
        created = client.post(
            "/api/auth/register",
            json={"email": "A@Example.com", "password": "mot-mat-khau", "display_name": " An "},
        )
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["expires_in"], 900)
        self.assertEqual(body["user"]["email"], "a@example.com")
        self.assertEqual(body["user"]["display_name"], "An")
        uuid.UUID(body["user"]["id"])
        self.assertNotIn("password", body["user"])

        logged = client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "mot-mat-khau"},
        )
        self.assertEqual(logged.status_code, 200)
        self.assertEqual(logged.json()["user"]["id"], body["user"]["id"])

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {logged.json()['access_token']}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["display_name"], "An")

    def test_login_hides_unknown_email(self) -> None:
        client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "mot-mat-khau", "display_name": "An"},
        )
        missing = client.post(
            "/api/auth/login",
            json={"email": "khong-co@example.com", "password": "mot-mat-khau"},
        )
        wrong = client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "sai-mat-khau-123"},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json(), wrong.json())
        self.assertEqual(missing.json()["error"]["code"], "unauthorized")
        self.assertNotIn("fields", missing.json()["error"])

    def test_register_validation(self) -> None:
        short = client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "ngan", "display_name": "An"},
        )
        self.assertEqual(short.status_code, 422)
        self.assertEqual(short.json()["error"]["fields"]["password"], "Mật khẩu phải từ 8 đến 128 ký tự.")

        client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "mot-mat-khau", "display_name": "An"},
        )
        duplicate = client.post(
            "/api/auth/register",
            json={"email": "A@example.com", "password": "mot-mat-khau", "display_name": "An hai"},
        )
        self.assertEqual(duplicate.status_code, 422)
        self.assertEqual(duplicate.json()["error"]["fields"]["email"], "Email này đã được đăng ký.")

        blank = client.post(
            "/api/auth/register",
            json={"email": "b@example.com", "password": "mot-mat-khau", "display_name": "   "},
        )
        self.assertEqual(blank.status_code, 422)
        self.assertIn("display_name", blank.json()["error"]["fields"])

    def test_refresh_rotates_and_logout_revokes(self) -> None:
        created = client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "mot-mat-khau", "display_name": "An"},
        ).json()
        first = created["refresh_token"]
        rotated = client.post("/api/auth/refresh", json={"refresh_token": first})
        self.assertEqual(rotated.status_code, 200)
        second = rotated.json()["refresh_token"]
        self.assertNotEqual(first, second)

        reused = client.post("/api/auth/refresh", json={"refresh_token": first})
        self.assertEqual(reused.status_code, 401)

        gone = client.post("/api/auth/logout", json={"refresh_token": second})
        self.assertEqual(gone.status_code, 204)
        self.assertEqual(gone.content, b"")
        again = client.post("/api/auth/refresh", json={"refresh_token": second})
        self.assertEqual(again.status_code, 401)

        with Session(get_engine()) as db:
            row = db.scalar(select(User).where(User.email == "a@example.com"))
            assert row is not None
            self.assertNotEqual(row.password_hash, "mot-mat-khau")
            self.assertTrue(row.password_hash.startswith("$argon2"))

    def test_bad_body_and_missing_token(self) -> None:
        bad = client.post("/api/auth/login", content=b"not-json", headers={"Content-Type": "application/json"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["error"]["code"], "bad_request")

        me = client.get("/api/auth/me")
        self.assertEqual(me.status_code, 401)
        self.assertEqual(client.get("/api/health").json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
