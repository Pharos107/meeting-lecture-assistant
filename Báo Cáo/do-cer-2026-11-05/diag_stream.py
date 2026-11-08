"""In các dòng SSE cuối của LLM cho một câu hỏi, để xem vì sao câu trả lời bị cụt.

Chạy trong backend: python diag_stream.py <job id> "<câu hỏi>" [số lần]
"""
import json
import sys
import uuid

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import Job
from app.services.chat_service import build_messages
from app.services.llm_client import _delta_text

job_id, question = sys.argv[1], sys.argv[2]
times = int(sys.argv[3]) if len(sys.argv) > 3 else 1
settings = get_settings()
with Session(get_engine()) as db:
    messages = build_messages(db, db.get(Job, uuid.UUID(job_id)), question)
body = {"model": settings.llm_model, "temperature": 0.2, "max_tokens": settings.llm_max_output_tokens,
        "stream": True, "stream_options": {"include_usage": True}, "messages": messages}
for attempt in range(times):
    lines = []
    with httpx.stream("POST", f"{settings.llm_base_url}/chat/completions", json=body,
                      headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=120) as r:
        for line in r.iter_lines():
            if line.strip():
                lines.append(line)
    text = "".join(t for t in (_delta_text(line) for line in lines) if t)
    finish = [json.loads(line[5:])["choices"][0].get("finish_reason") for line in lines
              if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]") and json.loads(line[5:]).get("choices")]
    usage = [json.loads(line[5:]).get("usage") for line in lines
             if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]") and json.loads(line[5:]).get("usage")]
    print(f"== lần {attempt + 1}: {len(lines)} dòng, {len(text)} ký tự, finish={[f for f in finish if f]}, usage={usage[-1:]}")
    print("   đuôi:", text[-120:].replace("\n", " | "))
    for line in lines[-3:]:
        print("   raw:", line[:300])
