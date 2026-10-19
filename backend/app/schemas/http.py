"""Schema JSON để Swagger mô tả body. Route vẫn tự kiểm tra và trả lỗi tiếng Việt."""

from typing import Literal

from pydantic import BaseModel, Field


class RegisterBody(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class LoginBody(BaseModel):
    email: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class ExportBody(BaseModel):
    format: Literal["md", "docx", "pdf", "srt", "vtt"]
    text: Literal["auto", "raw", "cleaned", "edited"] = "auto"
    include_speakers: bool = True


class LlmBody(BaseModel):
    task: Literal["clean", "summarize"]
    template: Literal["meeting", "lecture"] | None = None
    restart: bool = False


class LiveSessionBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    vocabulary: str | None = Field(default=None, max_length=800)
    num_speakers: int | None = Field(default=None, ge=1, le=20)


def request_body(model: type[BaseModel]) -> dict:
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
