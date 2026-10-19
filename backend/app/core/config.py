"""Đọc biến môi trường của API."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def load_env_file() -> None:
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)
        return


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    access_token_minutes: int
    refresh_token_days: int
    data_dir: str
    max_opus_bytes: int
    max_original_bytes: int
    max_duration_seconds: int
    redis_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int
    llm_json_mode: bool
    voice_match_threshold: float
    voice_match_margin: float
    max_voice_bytes: int


@lru_cache
def get_settings() -> Settings:
    load_env_file()
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET phải dài ít nhất 32 byte.")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("Thiếu DATABASE_URL.")
    return Settings(
        database_url=database_url,
        jwt_secret=secret,
        access_token_minutes=int(os.environ.get("ACCESS_TOKEN_MINUTES", "15")),
        refresh_token_days=int(os.environ.get("REFRESH_TOKEN_DAYS", "7")),
        data_dir=os.environ.get("DATA_DIR", "/data"),
        max_opus_bytes=int(os.environ.get("MAX_OPUS_BYTES", "67108864")),
        max_original_bytes=int(os.environ.get("MAX_ORIGINAL_BYTES", "524288000")),
        max_duration_seconds=int(os.environ.get("MAX_DURATION_SECONDS", "10800")),
        redis_url=os.environ.get("REDIS_URL", ""),
        llm_base_url=os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", ""),
        llm_timeout_seconds=int(os.environ.get("LLM_TIMEOUT_SECONDS", "120")),
        llm_json_mode=os.environ.get("LLM_JSON_MODE", "true").lower() in {"1", "true", "yes"},
        voice_match_threshold=float(os.environ.get("VOICE_MATCH_THRESHOLD", "0.75")),
        voice_match_margin=float(os.environ.get("VOICE_MATCH_MARGIN", "0.05")),
        max_voice_bytes=int(os.environ.get("MAX_VOICE_BYTES", "33554432")),
    )
