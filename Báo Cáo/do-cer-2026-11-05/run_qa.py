"""Đo hỏi đáp (#23): hỏi từng câu trong qa_set.json qua API thật, ghi câu trả lời, thời gian, và số token.

Chạy trong container backend:
  JOBS="hop1=<job id>,hop2=<job id>" python run_qa.py qa_set.json qa_out.json

Mỗi câu hỏi chạy trên lịch sử trống (xóa lịch sử trước khi hỏi), để câu trước không lẫn vào câu sau.
Token: luồng SSE của app không trả usage, nên trước mỗi câu hỏi script gọi thẳng LLM một lần với đúng
ngữ cảnh app dựng (stream=false) để lấy prompt_tokens và completion_tokens thật, gồm cả token suy luận.
Câu trả lời được chấm là câu trả lời qua app, không phải lần gọi thẳng này.
"""
import json
import os
import sys
import time
import uuid

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db import get_engine
from app.models import Job
from app.services.chat_service import build_messages

BASE = "http://127.0.0.1:8000/api"
qa_path, out_path = sys.argv[1], sys.argv[2]
jobs = dict(item.split("=", 1) for item in os.environ["JOBS"].split(","))
questions = json.load(open(qa_path, encoding="utf-8"))
settings = get_settings()


def usage_of(job_id: str, question: str) -> dict:
    """Gọi thẳng LLM với ngữ cảnh app dựng cho câu hỏi này, trên lịch sử trống, để lấy usage."""
    with Session(get_engine()) as db:
        messages = build_messages(db, db.get(Job, uuid.UUID(job_id)), question)
    body = {"model": settings.llm_model, "temperature": 0.2, "max_tokens": settings.llm_max_output_tokens,
            "messages": messages}
    r = httpx.post(f"{settings.llm_base_url}/chat/completions", json=body,
                   headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=180)
    r.raise_for_status()
    usage = r.json().get("usage") or {}
    return {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "context_chars": sum(len(m["content"]) for m in messages)}


def ask(client: httpx.Client, job_id: str, question: str) -> dict:
    t0 = time.perf_counter()
    first = None
    parts: list[str] = []
    event = None
    result = {"status": None, "error": None}
    with client.stream("POST", f"{BASE}/jobs/{job_id}/chat/messages", json={"question": question}) as resp:
        if resp.status_code != 200:
            resp.read()
            return {"status": "http_error", "error": f"{resp.status_code} {resp.text[:300]}", "answer": "",
                    "ttft_s": None, "total_s": round(time.perf_counter() - t0, 2)}
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                if event == "delta":
                    if first is None:
                        first = time.perf_counter()
                    parts.append(data["text"])
                elif event == "done":
                    result["status"] = "done"
                    result["model"] = data.get("model")
                elif event == "error":
                    result["status"] = "failed"
                    result["error"] = data.get("code")
    end = time.perf_counter()
    result.update({"answer": "".join(parts), "ttft_s": round(first - t0, 2) if first else None,
                   "total_s": round(end - t0, 2)})
    return result


out = {"model": settings.llm_model, "jobs": jobs, "answers": []}
clients = {}
with Session(get_engine()) as db:
    for clip, job_id in jobs.items():
        token, _ = create_access_token(db.get(Job, uuid.UUID(job_id)).user_id)
        clients[clip] = httpx.Client(timeout=300, headers={"Authorization": f"Bearer {token}"})

for item in questions:
    clip = item["clip"]
    clients[clip].delete(f"{BASE}/jobs/{jobs[clip]}/chat/messages").raise_for_status()
    try:
        usage = usage_of(jobs[clip], item["question"])
    except httpx.HTTPError as exc:
        usage = {"usage_error": str(exc)[:200]}
    res = ask(clients[clip], jobs[clip], item["question"])
    out["answers"].append({**item, **res, "usage": usage})
    print(f"{item['id']} {res['status']} ttft={res['ttft_s']}s total={res['total_s']}s usage={usage}", flush=True)
    time.sleep(2)

json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("done")
