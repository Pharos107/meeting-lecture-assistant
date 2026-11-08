"""Gọi API LLM tương thích OpenAI và đọc chữ trả về theo từng mảnh."""

import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings


class LlmTimeout(Exception):
    pass


class LlmUpstream(Exception):
    pass


class LlmRateLimited(Exception):
    pass


class LlmTruncated(LlmUpstream):
    """Luồng đóng mà server không báo finish_reason, câu trả lời có thể bị cụt."""


def _parse_line(line: str) -> tuple[str | None, str | None]:
    """Một dòng SSE của server LLM, trả (chữ, finish_reason). Phần nào không có thì là None."""
    if not line.startswith("data:"):
        return None, None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None, None
    try:
        choice = json.loads(data)["choices"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None, None
    if not isinstance(choice, dict):
        return None, None
    delta = choice.get("delta")
    text = delta.get("content") if isinstance(delta, dict) else None
    return text or None, choice.get("finish_reason") or None


async def stream_chat(
    messages: list[dict[str, str]],
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[str]:
    settings = get_settings()
    # Trần đọc là thời gian chờ giữa hai mảnh chữ, không phải tổng thời gian trả lời.
    timeout = httpx.Timeout(10.0, read=settings.llm_timeout_seconds)
    body = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "max_tokens": settings.llm_max_output_tokens,
        "stream": True,
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    url = f"{settings.llm_base_url}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code == 429:
                    raise LlmRateLimited("Hết hạn mức của nhà cung cấp LLM.")
                if response.status_code >= 400:
                    raise LlmUpstream(f"Server LLM trả {response.status_code}.")
                finish_reason = None
                async for line in response.aiter_lines():
                    text, reason = _parse_line(line)
                    if text:
                        yield text
                    finish_reason = reason or finish_reason
                if finish_reason is None:
                    raise LlmTruncated("Luồng LLM đóng trước khi trả lời xong.")
    except httpx.TimeoutException as exc:
        raise LlmTimeout("LLM hết hạn.") from exc
    except httpx.HTTPError as exc:
        raise LlmUpstream("Không kết nối được server LLM.") from exc
