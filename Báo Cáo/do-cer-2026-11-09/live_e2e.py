"""Thử PT2 qua WebSocket thật, làm giống LiveSocket của trình duyệt.

Chạy trong container backend:
    python live_e2e.py <file audio> <số giây phát> <giây bắt đầu rớt mạng> <số giây rớt>

- Phát PCM s16le 16 kHz theo thời gian thực, khung 100 ms.
- Tới giây rớt mạng thì đóng socket, giữ khung trong hàng đợi tối đa 250 khung như trình duyệt,
  sau đó xin ticket mới, nối lại, gửi hello, rồi xả hàng đợi.
- Đo độ trễ từ lúc hết câu nói (mốc end_ms tính theo giờ phát) tới tin draft stable của câu đó,
  chỉ với câu không dài quá 8 giây và không nằm trong lúc rớt mạng hay 15 giây sau đó.
- Dừng phiên, chờ pass 2 xong, kiểm transcript có chữ trong khoảng rớt mạng.
"""
import asyncio
import json
import secrets
import statistics
import subprocess
import sys
import time

import httpx
import websockets

BASE = "http://127.0.0.1:8000/api"
WS = "ws://127.0.0.1:8000"
FRAME = 3200  # 100 ms
MAX_QUEUED = 250

path, seconds, drop_at, drop_for = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
pcm = subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-t", str(seconds), "-ac", "1", "-ar", "16000",
     "-f", "s16le", "-"],
    check=True, capture_output=True,
).stdout
frames = [pcm[i:i + FRAME] for i in range(0, len(pcm) - FRAME + 1, FRAME)]

http = httpx.Client(timeout=60)
r = http.post(f"{BASE}/auth/register", json={"email": f"live-{secrets.token_hex(4)}@example.test",
                                              "password": secrets.token_urlsafe(16), "display_name": "Live"})
r.raise_for_status()
http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
for _ in range(30):
    r = http.post(f"{BASE}/live/sessions", json={"title": "Thử PT2"})
    if r.status_code == 201:
        break
    print("mở phiên:", r.json()["error"]["code"], flush=True)
    time.sleep(3)
r.raise_for_status()
session = r.json()
stable: dict[str, tuple[float, int, int, str]] = {}
t0 = None
reconnects = []


async def open_socket(ticket):
    socket = await websockets.connect(f"{WS}{session['ws_path']}?ticket={ticket}", max_size=None)
    await socket.send(json.dumps({"type": "hello", "sample_rate": 16000}))
    while True:
        message = json.loads(await socket.recv())
        if message["type"] == "hello_ok":
            return socket
        if message["type"] == "error":
            raise RuntimeError(message)


async def reader(socket, done):
    try:
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "draft" and message["stable"] and message["text"]:
                stable.setdefault(message["segment_id"], (time.time(), message["start_ms"], message["end_ms"], message["text"]))
            elif message["type"] == "stopped":
                done.set()
            elif message["type"] in ("warning", "error"):
                print("tin:", message, flush=True)
    except websockets.ConnectionClosed:
        pass


async def main():
    global t0
    done = asyncio.Event()
    socket = await open_socket(session["ticket"])
    task = asyncio.create_task(reader(socket, done))
    queue: list[bytes] = []
    lost_until = None
    t0 = time.time()
    for index, frame in enumerate(frames):
        due = t0 + index * 0.1
        await asyncio.sleep(max(0.0, due - time.time()))
        audio_s = index * 0.1
        if lost_until is None and socket is not None and drop_at <= audio_s < drop_at + 0.1:
            await socket.close()
            await task
            socket = None
            lost_until = time.time() + drop_for
            print(f"[{audio_s:6.1f}s] rớt mạng {drop_for} giây", flush=True)
        if socket is None and lost_until is not None and time.time() >= lost_until:
            ticket = http.post(f"{BASE}/live/sessions/{session['session_id']}/ticket").json()["ticket"]
            socket = await open_socket(ticket)
            task = asyncio.create_task(reader(socket, done))
            for queued in queue:
                await socket.send(queued)
            reconnects.append((audio_s, len(queue)))
            print(f"[{audio_s:6.1f}s] nối lại, xả {len(queue)} khung", flush=True)
            queue = []
        if socket is None:
            queue.append(frame)
            if len(queue) > MAX_QUEUED:
                queue.pop(0)
        else:
            await socket.send(frame)
    await asyncio.sleep(3)
    await socket.send(json.dumps({"type": "stop"}))
    await asyncio.wait_for(done.wait(), 60)
    await task


asyncio.run(main())

latencies = []
for received, start_ms, end_ms, text in stable.values():
    if end_ms - start_ms > 8000:
        continue
    if drop_at - 1 <= end_ms / 1000 <= drop_at + drop_for + 15:
        continue
    latencies.append(received - (t0 + end_ms / 1000))
latencies.sort()
print(f"câu nháp ổn định: {len(stable)}, dùng để đo: {len(latencies)}")
if latencies:
    p90 = latencies[int(0.9 * (len(latencies) - 1))]
    within = sum(1 for x in latencies if x <= 3.0)
    print(f"độ trễ: trung vị {statistics.median(latencies):.2f} s, p90 {p90:.2f} s, lớn nhất {latencies[-1]:.2f} s, "
          f"trong 3 giây {within}/{len(latencies)}")

job_id = session["job_id"]
started = time.time()
while True:
    job = http.get(f"{BASE}/jobs/{job_id}").json()
    if job["status"] in ("ready", "failed", "cancelled"):
        break
    time.sleep(2)
print(f"pass 2: {job['status']} {job.get('error_code')} sau {time.time() - started:.0f} s, duration_ms {job.get('duration_ms')}")
tr = http.get(f"{BASE}/jobs/{job_id}/transcript").json()
words = [w for s in tr["segments"] for w in s["words"]]
inside = [w for w in words if drop_at * 1000 <= w["start_ms"] <= (drop_at + drop_for) * 1000]
print(f"pass {tr['pass']}: {len(tr['segments'])} câu, {len(words)} từ, {len(inside)} từ trong khoảng rớt mạng")
print("câu quanh chỗ rớt:")
for s in tr["segments"]:
    if (drop_at - 5) * 1000 <= s["start_ms"] <= (drop_at + drop_for + 5) * 1000:
        print(f"  {s['start_ms'] / 1000:6.1f} {s['text_raw'][:100]}")
