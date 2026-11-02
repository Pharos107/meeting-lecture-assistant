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


def _delta_text(line: str) -> str | None:
    """Một dòng SSE của server LLM. Dòng không có chữ thì trả None."""
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
        return payload["choices"][0]["delta"].get("content") or None
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
        return None


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
                async for line in response.aiter_lines():
                    text = _delta_text(line)
                    if text:
                        yield text
    except httpx.TimeoutException as exc:
        raise LlmTimeout("LLM hết hạn.") from exc
    except httpx.HTTPError as exc:
        raise LlmUpstream("Không kết nối được server LLM.") from exc
