# Công nghệ và môi trường

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.4  
**Ngày:** 2026-10-28  
**Vai trò của file này:** Khóa thư viện, máy, biến môi trường, Docker, và cây thư mục. Hành vi nằm ở [kiến trúc](ARCHITECTURE_SPEC.md). Hợp đồng nằm ở [API và dữ liệu](API_AND_DATA.md).

## 1. Hồ sơ máy

| Hạng mục | Bản demo |
|---|---|
| GPU | NVIDIA, VRAM dưới 6GB. Thiết kế tính cho card 4GB còn trống cho tiến trình này |
| Độ chính xác Whisper | `int8` trên CUDA. Một model trong VRAM |
| Batch | `1`. Không dùng `BatchedInferencePipeline` |
| CPU và RAM máy worker | 4 nhân, 16 GB RAM |
| Đĩa trống | 20 GB cho image, cache model, và audio |
| Hệ điều hành triển khai | Linux, hoặc Windows qua WSL2 khi cần GPU trong Docker |
| Trình duyệt PT2 chia sẻ âm thanh tab | Chromium hiện đại |

`large-v3-turbo` giữ encoder của dòng large. Lợi ích của bản turbo là thời gian giải mã, không phải là việc giảm VRAM xuống mức model small. Trên card 4GB, Whisper int8 và pyannote vì thế chạy lần lượt.

Worker ghi tên GPU và tổng VRAM vào log lúc khởi động. Thiếu CUDA thì worker thoát ngay với thông báo cấu hình. Pyannote được phép rơi về CPU khi CUDA trả out-of-memory. Whisper không tự đổi sang CPU giữa job.

## 2. Bảng thành phần

| Tầng | Công nghệ | Vai trò |
|---|---|---|
| Frontend | Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui | Trang tài khoản, tải file, transcript, phiên nghe |
| Nén trên trình duyệt | `@ffmpeg/ffmpeg` và `@ffmpeg/core` bản đơn luồng | Tách âm thanh khỏi video, đưa upload về Opus. WASM lỗi thì tải file gốc |
| Backend | FastAPI, Pydantic, Uvicorn | REST, SSE, WebSocket, xác thực |
| Hàng đợi | Celery, Redis 7 | Hàng `gpu` concurrency 1. Hàng `io` concurrency 4 cho LLM |
| STT | faster-whisper | Pass chuẩn `large-v3-turbo`, pass nháp `small` |
| VAD | Silero VAD đi kèm faster-whisper | CPU |
| Người nói | pyannote.audio dòng 3, pipeline `pyannote/speaker-diarization-3.1` | Sau khi Whisper đã được giải phóng |
| LLM | HTTP tương thích OpenAI, thư viện `httpx` | Model do `LLM_MODEL` quyết định |
| Dữ liệu | PostgreSQL 16, SQLAlchemy, Alembic | Người dùng, job, chữ, sự kiện |
| File | Volume Docker | Opus, PCM tạm, cache Hugging Face |
| Tài liệu xuất | python-docx, fpdf2, font Noto Sans | DOCX và PDF có dấu tiếng Việt |
| Mật khẩu | argon2-cffi | argon2id |
| Token | PyJWT | JWT HS256 cho access token |
| Ảnh và chạy | Docker Compose v2, NVIDIA Container Toolkit | GPU chỉ gắn vào service worker |

### Model nhận dạng

Tên ngắn dưới đây là khóa trong `faster_whisper/utils.py` của bản SYSTRAN đang dùng. Repo resolve hiện tại:

| Vai trò | Tên truyền vào `WhisperModel` | Repo Hugging Face mà thư viện resolve |
|---|---|---|
| Bản chuẩn | `large-v3-turbo` | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` |
| Bản nháp PT2 | `small` | `Systran/faster-whisper-small` |

Khi nâng faster-whisper, mở lại bảng `_MODELS` và ghi repo thực tế vào `backend/MODELS.lock`. Tham số runtime nằm ở kiến trúc.

`large-v3-turbo` cắt decoder từ 32 xuống 4 lớp. Mức giảm chất lượng thường rõ hơn ở ngôn ngữ ít dữ liệu. Ứng viên để so là PhoWhisper của VinAI, đã huấn luyện thêm trên khoảng 844 giờ tiếng Việt, chuyển sang định dạng CTranslate2 rồi chạy `int8` như bản chuẩn. Model bản chuẩn được chọn theo CER trên bộ đối chiếu, theo tiêu chí ở [ý tưởng mục 6](IDEA_AND_CHALLENGES.md#6-tiêu-chí-nghiệm-thu). Đổi model thì `WHISPER_MODEL` nhận đường dẫn thư mục model đã chuyển.

### Pyannote

- Thư viện: `pyannote.audio>=3.1,<4`.
- Bản để kiểm thử: `3.3.2`.
- Pipeline: `pyannote/speaker-diarization-3.1`.
- Tài khoản Hugging Face của token phải chấp nhận điều kiện ở [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) và [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1).
- Dòng 4 không dùng trên hồ sơ GPU này vì mức VRAM đã đo vượt 6GB.
- Cache tải lúc chạy vào volume, không nung weight gated vào image.
- Chạy trên CPU khi CUDA hết bộ nhớ chậm hơn nhiều lần. Đo thời gian với file 60 phút và 3 giờ trước khi hứa thời gian xử lý, và hiện tiến độ cho người dùng trong lúc chạy CPU.

`Pipeline.from_pretrained` của dòng 3.3 nhận `use_auth_token`.

### LLM

Không cài SDK của một nhà cung cấp. Worker gửi HTTP tới server tương thích OpenAI. Gemini ở chế độ tương thích OpenAI, Ollama, vLLM, và các cổng tương tự đều dùng một client, miễn là chúng có `POST /chat/completions`.

`LLM_MODEL` để trống cho đến khi nhóm chọn model. Thiếu biến này thì nút hậu kỳ trả `llm_not_configured`.

### Font và trình duyệt

PDF nhúng Noto Sans (OFL) để giữ dấu. File TTF lấy lúc build image, đặt tại `backend/assets/fonts/NotoSans-Regular.ttf`.

Next.js gửi kèm:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Hai header này bật `SharedArrayBuffer`. Chỉ bản đa luồng `@ffmpeg/core-mt` bắt buộc cần nó. Gói đang cài là `@ffmpeg/core` đơn luồng, chạy được không cần hai header. Giữ chúng để còn đổi sang bản đa luồng khi cần tốc độ. Font và asset khác của trang phải cùng origin hoặc có CORP. Trang không gọi script bên thứ ba.

## 3. Biến môi trường

Tạo `.env` từ bảng này. Không commit `.env`.

| Biến | Ví dụ | Ý nghĩa |
|---|---|---|
| `POSTGRES_DB` | `meeting` | Tên database |
| `POSTGRES_USER` | `meeting` | User Postgres |
| `POSTGRES_PASSWORD` | chuỗi dài ngẫu nhiên | Mật khẩu Postgres |
| `DATABASE_URL` | `postgresql+psycopg://meeting:…@postgres:5432/meeting` | Chuỗi SQLAlchemy |
| `REDIS_URL` | `redis://redis:6379/0` | Broker Celery và pub/sub |
| `JWT_SECRET` | chuỗi ngẫu nhiên ≥ 32 byte | Ký access token |
| `ACCESS_TOKEN_MINUTES` | `15` | Tuổi access token |
| `REFRESH_TOKEN_DAYS` | `7` | Tuổi refresh token |
| `HF_TOKEN` | token Hugging Face | Tải pyannote |
| `HF_HOME` | `/cache/huggingface` | Cache model trong container |
| `WHISPER_MODEL` | `large-v3-turbo` | Bản chuẩn |
| `WHISPER_DRAFT_MODEL` | `small` | Bản nháp |
| `WHISPER_DEVICE` | `cuda` | Thiết bị Whisper |
| `WHISPER_COMPUTE_TYPE` | `int8` | Độ chính xác số |
| `WHISPER_BEAM_SIZE` | `5` | Beam của bản chuẩn |
| `WHISPER_DRAFT_BEAM_SIZE` | `1` | Beam của bản nháp |
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | Gốc API, có hậu tố `/v1` |
| `LLM_API_KEY` | khóa hoặc chuỗi bất kỳ nếu server local không kiểm tra | Bearer gửi sang LLM |
| `LLM_MODEL` | để trống đến khi chọn | Tên model phía server LLM |
| `LLM_TIMEOUT_SECONDS` | `120` | Trần một request |
| `LLM_JSON_MODE` | `true` | Gửi `response_format` kiểu `json_object` |
| `DATA_DIR` | `/data` | Gốc audio và file tạm |
| `MAX_DURATION_SECONDS` | `10800` | 3 giờ |
| `MAX_OPUS_BYTES` | `67108864` | 64 MB |
| `MAX_ORIGINAL_BYTES` | `524288000` | 500 MB |
| `CUDA_VISIBLE_DEVICES` | `0` | Một GPU |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` | Giảm phân mảnh VRAM |
| `VOICE_MATCH_THRESHOLD` | `0.75` | Điểm cosine tối thiểu để gán hồ sơ giọng |
| `VOICE_MATCH_MARGIN` | `0.05` | Cách điểm tối thiểu khi hai hồ sơ cùng chạm một cụm |

`LLM_BASE_URL` đã gồm `/v1`. Client gọi thêm đường dẫn `/chat/completions`.

## 4. Cây thư mục

```text
meeting-lecture-assistant/
├── .env.example
├── docker-compose.yml
├── deploy/
│   └── Caddyfile
├── docs/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── MODELS.lock
│   ├── alembic/
│   ├── assets/fonts/NotoSans-Regular.ttf
│   └── app/
│       ├── main.py
│       ├── worker.py
│       ├── db.py
│       ├── core/                 # config, security, exceptions, rate_limit, timeutil
│       ├── api/
│       │   ├── routes_auth.py
│       │   ├── routes_jobs.py
│       │   ├── routes_events.py
│       │   ├── routes_live.py
│       │   ├── routes_voice.py
│       │   ├── routes_llm.py
│       │   └── routes_export.py
│       ├── services/
│       │   ├── audio_processor.py
│       │   ├── vad_chunker.py
│       │   ├── stt_engine.py
│       │   ├── diarization.py
│       │   ├── speaker_align.py
│       │   ├── voice_profile.py
│       │   ├── llm_client.py
│       │   ├── llm_runner.py     # cắt lát, map-reduce, validate
│       │   ├── pipeline.py       # bản chuẩn: chunk, ghi câu, diarization, sự kiện
│       │   ├── gpu_lock.py
│       │   ├── job_notify.py     # publish job:{job_id}:events sau commit
│       │   ├── live_channel.py   # quyền ghi PCM, kênh live:{sid}:out, open_draft
│       │   ├── live_heartbeat.py
│       │   ├── dispatch.py       # send_task sang Celery
│       │   ├── housekeeping.py   # xóa media token, ticket hết hạn
│       │   └── exporter.py
│       ├── tasks/
│       ├── models.py
│       └── schemas/
└── frontend/
    ├── Dockerfile
    ├── next.config.ts
    ├── public/ffmpeg/
    └── src/
        ├── app/
        │   ├── login/page.tsx
        │   ├── register/page.tsx
        │   ├── forgot-password/page.tsx   # chỉ giao diện, chưa có API
        │   ├── components/page.tsx        # trang mẫu component, không phải tính năng
        │   ├── jobs/page.tsx
        │   ├── jobs/new/page.tsx
        │   ├── jobs/[id]/page.tsx
        │   ├── live/page.tsx
        │   └── voice-profiles/page.tsx
        ├── components/
        │   ├── audio-uploader.tsx
        │   ├── transcript-layout.tsx
        │   ├── live-transcript.tsx
        │   ├── audio-player-bar.tsx
        │   ├── speaker-list.tsx
        │   ├── selection-toolbar.tsx
        │   ├── ai-action-panel.tsx
        │   ├── auth-shell.tsx
        │   └── ui/                        # shadcn/ui
        └── lib/
            ├── api.ts
            ├── auth.ts
            ├── ffmpeg-compressor.ts
            ├── typewriter-queue.ts
            └── live-capture.ts
```

## 5. Docker Compose

Compose v2. Bỏ khóa `version`. Postgres, Redis, FastAPI, và Next.js chỉ ở mạng nội bộ. Cổng máy chủ mở ra là `80` của Caddy. Caddy gửi `/api` sang FastAPI, kể cả nâng cấp WebSocket và SSE, và gửi các đường còn lại sang Next.js. Next.js không đứng giữa upload, SSE, hay WebSocket.

`deploy.resources.reservations.devices` là cách Compose v2 gắn GPU. NVIDIA Container Toolkit phải có trên máy Linux hoặc trong WSL2. GPU chỉ gắn vào `worker-gpu`.

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20

  backend:
    build: ./backend
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    expose:
      - "8000"
    volumes:
      - audio-data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
      interval: 10s
      timeout: 5s
      retries: 20

  worker-gpu:
    build: ./backend
    env_file: .env
    command: celery -A app.worker.celery_app worker --loglevel=info -Q gpu --concurrency=1 --prefetch-multiplier=1
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - audio-data:/data
      - hf-cache:/cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility

  worker-io:
    build: ./backend
    env_file: .env
    command: celery -A app.worker.celery_app worker --loglevel=info -Q io --concurrency=4 --prefetch-multiplier=1
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  frontend:
    build: ./frontend
    expose:
      - "3000"
    depends_on:
      backend:
        condition: service_healthy

  caddy:
    image: caddy:2
    ports:
      - "80:80"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
    depends_on:
      - frontend
      - backend

volumes:
  pg-data:
  audio-data:
  hf-cache:
```

`deploy/Caddyfile`:

```text
:80 {
  handle /api/* {
    reverse_proxy backend:8000 {
      flush_interval -1
    }
  }
  handle {
    reverse_proxy frontend:3000
  }
}
```

`flush_interval -1` để SSE không bị Caddy gom chunk. Profile `debug` có thể publish `5432`, `6379`, `8000`, và `3000` khi cần công cụ trên máy host. Profile mặc định không mở các cổng đó.

### Image backend

- Nền `python:3.11-slim`. Image này không có CUDA ở `/usr/lib`.
- Cài `ffmpeg` bằng apt.
- Cài PyTorch bản CUDA từ index wheel mà trang PyTorch chỉ định cho driver của máy. Wheel CPU mặc định trên PyPI không dùng cho worker.
- Sau đó cài phần còn lại trong `requirements.txt`.
- Ghi đúng dòng cài PyTorch vào `backend/MODELS.lock` cùng ngày build.
- `ctranslate2` không tự tìm `libcublas` trong `site-packages`. Dockerfile đặt `LD_LIBRARY_PATH` tới thư mục lib mà wheel NVIDIA giải nén, và soname phải trùng file thật sự có sau khi cài, ví dụ `libcublas.so.12`:

```dockerfile
ENV LD_LIBRARY_PATH="/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib:${LD_LIBRARY_PATH}"
```

- Nếu bản wheel đổi số CUDA, sửa đường dẫn và soname trong cùng commit với dòng cài PyTorch.
- Chạy bằng user không phải root.
- Lệnh API: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

`requirements.txt` ghim các gói có ảnh hưởng VRAM và hợp đồng. `torch` và `torchaudio` cài trước từ index CUDA trong Dockerfile:

```text
ctranslate2==4.5.0
faster-whisper==1.1.1
pyannote.audio==3.3.2
numpy==1.26.4
huggingface_hub<1.0
fastapi
uvicorn
celery[redis]
redis
sqlalchemy
alembic
psycopg[binary]
pydantic
python-multipart
argon2-cffi
PyJWT
httpx
python-docx
fpdf2
```

`huggingface_hub` dòng 1.x bỏ gói `requests` mà faster-whisper 1.1.1 import, và bỏ tham số `use_auth_token` mà pyannote.audio 3.3.2 dùng. Trên Windows, ctranslate2 4.5.0 còn cần `setuptools` để có `pkg_resources`. Image Linux không gặp lỗi này.

Các gói còn lại lấy bản tương thích lúc khóa lockfile. `pyannote.audio` không được giải lên dòng 4.

`ctranslate2` từ 4.5 cần cuDNN 9, còn PyTorch đời cũ đi kèm cuDNN 8. Cài bản mới nhất của từng gói dễ làm Whisper và pyannote không chạy chung một image. Trước khi demo, ghim đúng phiên bản `torch`, `ctranslate2`, `faster-whisper`, và `pyannote.audio` đã chạy cùng nhau trên máy mục tiêu, bằng `==` trong `requirements.txt`, và ghi bộ đó vào `backend/MODELS.lock`.

Trên Windows, GPU trong Docker đi qua WSL2: driver NVIDIA cài ở Windows, toolkit cài trong bản phân phối WSL, rồi `docker compose up` chạy từ WSL.

## 6. Celery

Hai tiến trình, cùng mã, khác hàng:

| Tiến trình | Hàng | Concurrency | Việc |
|---|---|---|---|
| `worker-gpu` | `gpu` | 1, prefetch 1 | `app.tasks.transcribe_upload`, `app.tasks.run_live_session`, `app.tasks.enroll_voice` |
| `worker-io` | `io` | 4, prefetch 1 | `app.tasks.run_llm` |

Không chạy worker trên hàng mặc định `celery`. Mọi tác vụ khai báo hàng trong `task_routes`. Tác vụ không có trong bảng này không được phép tồn tại.

- `task_acks_late = true`
- `task_reject_on_worker_lost = true`
- Hết hạn cứng của một task GPU là 6 giờ, dài hơn trần audio 3 giờ để còn chỗ cho diarization CPU.
- Task LLM dùng trần `LLM_TIMEOUT_SECONDS` cho từng request HTTP, và hết hạn task 30 phút cho cả lần map-reduce.
- `broker_transport_options = {"visibility_timeout": 25200}`. Với broker Redis, task đã nhận mà chưa ack quá `visibility_timeout` sẽ được giao lại. Mặc định là 1 giờ, nên khi bật `task_acks_late`, task GPU dài hơn 1 giờ sẽ chạy hai lần. 7 giờ dài hơn hạn cứng 6 giờ của task GPU.

`gpu:lock`, `retry` sau 5 giây của PT1, và các key `live:{session_id}:*` nằm ở kiến trúc. PT1 không chiếm slot worker bằng vòng lặp chờ khóa.

## 7. Git

| Nhánh | Vai trò |
|---|---|
| `main` | Bản đã kiểm thử, dùng để bảo vệ hoặc triển khai |
| `dev` | Nhánh tích hợp của nhóm |
| `feature/...` | Một việc, ví dụ `feature/vad-chunking` |

Commit theo Conventional Commits: `feat(stt): nhận dạng chunk và cộng offset`, `fix(live): đóng câu nháp khi mất kết nối`.

Audio đối chiếu, `.env`, cache Hugging Face, và thư mục dữ liệu không vào Git.
