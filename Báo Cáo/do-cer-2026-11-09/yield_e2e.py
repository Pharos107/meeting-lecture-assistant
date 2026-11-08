"""Thử nhường GPU trên stack thật: một job PT1 dài đang nhận dạng, rồi mở phiên nghe.

Chạy trong container backend: python yield_e2e.py <file audio dài trong container>
In mốc thời gian của từng bước: lúc gặp gpu_yielding, lúc mở được phiên, lúc job chạy tiếp và xong.
"""
import secrets
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000/api"
path = sys.argv[1]
c = httpx.Client(timeout=600)
r = c.post(f"{BASE}/auth/register", json={"email": f"yield-{secrets.token_hex(4)}@example.test",
                                           "password": secrets.token_urlsafe(16), "display_name": "Yield"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

with open(path, "rb") as f:
    r = c.post(f"{BASE}/jobs", files={"file": (path.rsplit("/", 1)[-1], f, "audio/mpeg")})
r.raise_for_status()
job_id = r.json()["job_id"]
t0 = time.time()


def log(text):
    print(f"[{time.time() - t0:6.1f}s] {text}", flush=True)


while c.get(f"{BASE}/jobs/{job_id}").json()["status"] != "transcribing":
    time.sleep(1)
log("job transcribing")
time.sleep(8)

codes = []
session = None
deadline = time.time() + 90
while time.time() < deadline:
    r = c.post(f"{BASE}/live/sessions", json={"title": "Chen ngang"})
    if r.status_code == 201:
        session = r.json()
        break
    code = r.json()["error"]["code"]
    codes.append(code)
    if code != "gpu_yielding":
        break
    time.sleep(3)
log(f"mở phiên sau {len(codes)} lần thử, mã: {sorted(set(codes))}, được phiên: {session is not None}")
job = c.get(f"{BASE}/jobs/{job_id}").json()
log(f"job lúc đó: {job['status']} {job.get('stage')} {job.get('progress')}")
if session is None:
    sys.exit(1)

time.sleep(5)
r = c.post(f"{BASE}/live/sessions/{session['session_id']}/stop")
log(f"dừng phiên: {r.status_code} {r.json().get('status')}")

last = None
while True:
    job = c.get(f"{BASE}/jobs/{job_id}").json()
    state = (job["status"], job.get("stage"))
    if state != last:
        log(f"job {state} {job.get('progress')}")
        last = state
    if job["status"] in ("ready", "failed", "cancelled"):
        break
    time.sleep(2)
tr = c.get(f"{BASE}/jobs/{job_id}/transcript").json()
positions = [s["start_ms"] for s in tr["segments"]]
log(f"xong: {job['status']}, {len(tr['segments'])} câu, mốc tăng dần: {positions == sorted(positions)}")
