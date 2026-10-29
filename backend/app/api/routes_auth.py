"""Đăng ký, đăng nhập, làm mới phiên, đăng xuất, và hồ sơ."""

import json
import re
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ApiError
from app.core.rate_limit import client_key, login_attempts, register_attempts
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
    verify_password_dummy,
)
from app.db import get_db
from app.models import RefreshToken, User
from app.schemas.auth import TokenOut, UserOut
from app.schemas.http import LoginBody, RefreshBody, RegisterBody, request_body

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UNAUTHORIZED = "Email hoặc mật khẩu không đúng."
_TOKEN_INVALID = "Token không hợp lệ hoặc đã hết hạn."


async def read_object(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        raise ApiError(400, "bad_request", "Body không đọc được.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(400, "bad_request", "Body không đọc được.")
    if not isinstance(data, dict):
        raise ApiError(400, "bad_request", "Body không đọc được.")
    return data


def require_strings(data: dict, names: list[str]) -> None:
    labels = {
        "email": "Vui lòng nhập email.",
        "password": "Vui lòng nhập mật khẩu.",
        "display_name": "Vui lòng nhập tên hiển thị.",
        "refresh_token": "Vui lòng nhập refresh token.",
    }
    fields = {name: labels[name] for name in names if not isinstance(data.get(name), str)}
    if fields:
        message = next(iter(fields.values())) if len(fields) == 1 else "Dữ liệu không hợp lệ."
        raise ApiError(422, "validation", message, fields)


def validation(fields: dict[str, str]) -> None:
    if not fields:
        return
    message = next(iter(fields.values())) if len(fields) == 1 else "Dữ liệu không hợp lệ."
    raise ApiError(422, "validation", message, fields)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)


def issue_session(db: Session, user: User) -> TokenOut:
    access_token, expires_in = create_access_token(user.id)
    raw, digest, expires_at = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            expires_at=expires_at,
        )
    )
    db.commit()
    return TokenOut(
        access_token=access_token,
        token_type="Bearer",
        expires_in=expires_in,
        refresh_token=raw,
        user=user_out(user),
    )


def load_refresh(db: Session, raw: str) -> RefreshToken:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None or as_utc(row.expires_at) <= now:
        raise ApiError(401, "unauthorized", _TOKEN_INVALID)
    return row


_bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    _credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or not header.removeprefix("Bearer ").strip():
        raise ApiError(401, "unauthorized", "Thiếu token.")
    token = header.removeprefix("Bearer ").strip()
    try:
        user_id = decode_access_token(token)
    except (jwt.InvalidTokenError, ValueError):
        raise ApiError(401, "unauthorized", _TOKEN_INVALID)
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(401, "unauthorized", _TOKEN_INVALID)
    return user


@router.post("/register", status_code=201, openapi_extra=request_body(RegisterBody))
async def register(request: Request, db: Session = Depends(get_db)) -> TokenOut:
    register_attempts.hit(client_key(request))
    data = await read_object(request)
    require_strings(data, ["email", "password", "display_name"])
    email = data["email"].strip().lower()
    display_name = data["display_name"].strip()
    password = data["password"]
    fields: dict[str, str] = {}
    if not _EMAIL_RE.fullmatch(email):
        fields["email"] = "Email không hợp lệ."
    if not display_name or len(display_name) > 80:
        fields["display_name"] = "Tên hiển thị phải từ 1 đến 80 ký tự."
    if len(password) < 8 or len(password) > 128:
        fields["password"] = "Mật khẩu phải từ 8 đến 128 ký tự."
    validation(fields)

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            422,
            "validation",
            "Email này đã được đăng ký.",
            {"email": "Email này đã được đăng ký."},
        )
    return issue_session(db, user)


@router.post("/login", openapi_extra=request_body(LoginBody))
async def login(request: Request, db: Session = Depends(get_db)) -> TokenOut:
    login_attempts.hit(client_key(request))
    data = await read_object(request)
    require_strings(data, ["email", "password"])
    email = data["email"].strip().lower()
    password = data["password"]
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password_dummy(password)
        raise ApiError(401, "unauthorized", _UNAUTHORIZED)
    if not verify_password(password, user.password_hash):
        raise ApiError(401, "unauthorized", _UNAUTHORIZED)
    return issue_session(db, user)


@router.post("/refresh", openapi_extra=request_body(RefreshBody))
async def refresh(request: Request, db: Session = Depends(get_db)) -> TokenOut:
    data = await read_object(request)
    require_strings(data, ["refresh_token"])
    row = load_refresh(db, data["refresh_token"])
    user = db.get(User, row.user_id)
    if user is None:
        raise ApiError(401, "unauthorized", _TOKEN_INVALID)
    row.revoked_at = datetime.now(timezone.utc)
    return issue_session(db, user)


@router.post("/logout", status_code=204, openapi_extra=request_body(RefreshBody))
async def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    data = await read_object(request)
    require_strings(data, ["refresh_token"])
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(data["refresh_token"]))
    )
    if row is None:
        raise ApiError(401, "unauthorized", _TOKEN_INVALID)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return Response(status_code=204)


@router.get("/me", dependencies=[Depends(current_user)])
def me(request: Request, db: Session = Depends(get_db)) -> UserOut:
    return user_out(current_user(request, db))
