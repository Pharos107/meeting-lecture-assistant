"""Chạy một job PT1 qua API trong container backend và in tóm tắt kết quả.

Dùng: python run_job.py <đường dẫn file trong container> [số người nói]
"""
import json
import os
import secrets
import sys
import time
from collections import Counter

import httpx

BASE = "http://127.0.0.1:8000/api"
path = sys.argv[1]
num_speakers = sys.argv[2] if len(sys.argv) > 2 else None

c = httpx.Client(timeout=600)
email = f"gpu-check-{secrets.token_hex(4)}@example.test"
r = c.post(f"{BASE}/auth/register", json={"email": email, "password": secrets.token_urlsafe(16), "display_name": "GPU check"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

data = {"num_speakers": num_speakers} if num_speakers else {}
if os.environ.get("VOCAB"):
    data["vocabulary"] = os.environ["VOCAB"]
t0 = time.time()
with open(path, "rb") as f:
    r = c.post(f"{BASE}/jobs", files={"file": (path.rsplit("/", 1)[-1], f, "audio/mpeg")}, data=data)
print("upload", r.status_code, round(time.time() - t0, 1), "s", flush=True)
r.raise_for_status()
job_id = r.json()["job_id"]
print("job", job_id, flush=True)

last = None
t1 = time.time()
stages = {}
while True:
    job = c.get(f"{BASE}/jobs/{job_id}").json()
    state = (job.get("status"), job.get("stage"), job.get("progress"))
    if state != last:
        print(f"[{time.time() - t1:7.1f}s] {state}", flush=True)
        stages[job["status"]] = round(time.time() - t1, 1)
        last = state
    if job["status"] in ("ready", "failed", "cancelled"):
        break
    time.sleep(1)
if os.environ.get("META"):
    with open(os.environ["META"], "w", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "elapsed": round(time.time() - t1, 1), "stages": stages,
                   "status": job["status"], "warnings": job.get("warnings"), "duration_ms": job.get("duration_ms"),
                   "diarization_device": job.get("diarization_device")}, f, ensure_ascii=False)

print("elapsed", round(time.time() - t1, 1), "s")
print(json.dumps({k: job.get(k) for k in ("status", "error_code", "error_message", "warnings", "duration_ms", "diarization_device")}, ensure_ascii=False))

tr = c.get(f"{BASE}/jobs/{job_id}/transcript").json()
if os.environ.get("OUT"):
    with open(os.environ["OUT"], "w", encoding="utf-8") as f:
        json.dump(tr, f, ensure_ascii=False)
segs = tr["segments"]
print("pass", tr["pass"], "segments", len(segs), "speakers", [s["label"] for s in tr["speakers"]])
talk = Counter()
for s in segs:
    talk[s["speaker_label"]] += s["end_ms"] - s["start_ms"]
for label, ms in talk.most_common():
    print(f"  {label}: {ms / 1000:.0f}s")
words = sum(len(s["words"]) for s in segs)
mixed = sum(1 for s in segs if len({w["speaker_label"] for w in s["words"]}) > 1)
print("words", words, "segments with >1 word speaker", mixed)
for s in segs[:12]:
    print(f"  {s['start_ms'] / 1000:7.1f} {s['speaker_label']}: {s['text_raw'][:110]}")
