# API và dữ liệu

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.3  
**Ngày:** 2026-10-16  
**Vai trò của file này:** Hợp đồng để viết client và server. Hành vi pipeline nằm ở [kiến trúc](ARCHITECTURE_SPEC.md).

Thời gian trong JSON là số nguyên mili giây, mốc 0 là đầu file hoặc đầu phiên nghe. Chuỗi thời gian người đọc, dạng `MM:SS` hoặc `HH:MM:SS`, chỉ xuất hiện trong nội dung biên bản và file xuất.

## 1. Quy ước

- Trình duyệt chỉ gọi cùng origin qua Caddy. Tiền tố `/api`, kể cả SSE và WebSocket, sang FastAPI. Các đường còn lại sang Next.js. Next.js không rewrite và không proxy các đường này.
- REST và SSE dùng access token: `Authorization: Bearer {access_token}`.
- Body JSON dùng `Content-Type: application/json; charset=utf-8`.
- Id là UUID v4.
- Danh sách dùng `?limit=` mặc định 20, tối đa 100, và `?cursor=` là `created_at` cộng id của phần tử cuối trang trước.
- Lỗi có một dạng:

```json
{
  "error": {
    "code": "gpu_busy",
    "message": "GPU đang bận với một phiên khác."
  }
}
```

`message` là câu tiếng Việt để hiện trên giao diện.

### Mã lỗi

| HTTP | `error.code` | Khi nào |
|---|---|---|
| 400 | `bad_request` | Body không đọc được |
| 401 | `unauthorized` | Thiếu token, token hết hạn, hoặc sai mật khẩu |
| 404 | `not_found` | Không có bản ghi, hoặc bản ghi thuộc người khác |
| 409 | `gpu_busy` | Mở phiên nghe khi khóa GPU đang bị giữ |
| 409 | `invalid_state` | Hủy, sửa, hoặc gọi LLM khi trạng thái không cho phép |
| 413 | `file_too_large` | Vượt 64 MB Opus hoặc 500 MB file gốc |
| 415 | `unsupported_media` | Không có stream audio |
| 422 | `validation` | Sai field, kèm `fields` là map tên field sang câu lỗi |
| 422 | `duration_exceeded` | Dài hơn 3 giờ hoặc PCM ước lượng vượt 800 MB |
| 422 | `llm_not_configured` | Chưa có `LLM_MODEL` |
| 502 | `llm_invalid_json` | Hai lần liên tiếp không ra JSON đúng schema |
| 503 | `gpu_oom` | Không nạp được Whisper trong phần VRAM còn lại |
| 504 | `llm_timeout` | Hết hạn một request LLM |

Lỗi nghiệp vụ trong lúc chạy job không trả trên request tải file. Chúng nằm ở `jobs.error_code` và sự kiện `error`.

## 2. Tài khoản

### `POST /api/auth/register`

```json
{ "email": "a@example.com", "password": "mot-mat-khau", "display_name": "An" }
```

`display_name` từ 1 đến 80 ký tự. Email đưa về chữ thường. Mật khẩu từ 8 đến 128 ký tự. Trùng email trả `validation` trên field `email`.

Thành công `201`, body cùng dạng login.

### `POST /api/auth/login`

```json
{ "email": "a@example.com", "password": "mot-mat-khau" }
```

```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "...",
  "user": { "id": "...", "email": "a@example.com", "display_name": "An" }
}
```

Sai mật khẩu và email không tồn tại cùng trả `unauthorized`.

### `POST /api/auth/refresh`

```json
{ "refresh_token": "..." }
```

Trả cặp token mới. Refresh token cũ bị thu hồi. Dùng lại token cũ trả `unauthorized`.

### `POST /api/auth/logout`

Body giống refresh. Thu hồi refresh token đó. Access token còn hạn thì hết hiệu lực ở client bằng cách xóa khỏi bộ nhớ. `204` rỗng.

### `GET /api/auth/me`

Trả object `user`.

## 3. Job file

### `POST /api/jobs`

`multipart/form-data`:

| Phần | Bắt buộc | Ràng buộc |
|---|---|---|
| `file` | có | Audio hoặc video. Đuôi được phép: mp3, wav, m4a, aac, ogg, opus, flac, mp4, mkv, webm, mov |
| `title` | không | Tối đa 200 ký tự. Thiếu thì lấy tên file, cắt còn 200 ký tự |
| `vocabulary` | không | Tối đa 800 ký tự |
| `num_speakers` | không | Số nguyên 1 đến 20 |

`201`:

```json
{ "job_id": "7c1a6b4e-3e0a-4f5b-9c1d-2a8e5f0b6d11", "status": "queued" }
```

### `GET /api/jobs`

```json
{
  "items": [
    {
      "id": "...",
      "title": "Họp sprint",
      "source": "upload",
      "status": "ready",
      "duration_ms": 3600000,
      "warnings": [],
      "created_at": "2026-10-16T01:02:03Z"
    }
  ],
  "next_cursor": null
}
```

`source` là `upload` hoặc `live`.

### `GET /api/jobs/{job_id}`

Thêm `error_code`, `error_message`, `vocabulary`, `num_speakers`, `diarization_device` (`cuda`, `cpu`, hoặc null), `started_at`, `finished_at`.

### `POST /api/jobs/{job_id}/cancel`

Nhận `queued`, `capturing`, `preprocessing`, và `transcribing`. `202` và body job. Trạng thái khác trả `invalid_state`. Hủy lúc `capturing` không chạy pass 2.

### `POST /api/jobs/{job_id}/retry`

Chỉ khi `failed`. `202` và body job ở trạng thái `queued`.

### `DELETE /api/jobs/{job_id}`

Xóa job, segment, word, sự kiện, lần chạy LLM, alias, đánh dấu, việc manual, session nghe gắn với job, file Opus, và file tạm. Hồ sơ giọng của tài khoản không bị xóa theo job. Nếu job đang `capturing`, worker dừng thu, không chạy pass 2, và nhả `gpu:lock` trước khi các dòng bị xóa. `204`.

## 4. SSE tiến độ

### `GET /api/jobs/{job_id}/events?after_seq=0`

Request mang `Accept: text/event-stream` và Bearer. Response mang `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`, và không dùng gzip. Một khung:

```text
id: 12
event: chunk
data: {"seq":12,"chunk_index":1,"chunk_count":40,"processing_time_ms":1800,"expected_next_chunk_ms":1900,"segments":[...]}

```

`id` của khung SSE bằng `seq`. Client gửi lại `after_seq` bằng seq cuối đã áp dụng.

| `event` | `data` |
|---|---|
| `stage` | `seq`, `stage` (`preprocessing`, `transcribing`, `diarizing`), `detail` |
| `chunk` | `seq`, `chunk_index`, `chunk_count`, `processing_time_ms`, `expected_next_chunk_ms`, `segments` |
| `speakers` | `seq`. Client gọi lại API transcript |
| `warning` | `seq`, `code`, `message` |
| `done` | `seq` |
| `error` | `seq`, `code`, `message` |

Một phần tử `segments` trong sự kiện `chunk`:

```json
{
  "id": "...",
  "start_ms": 25400,
  "end_ms": 29800,
  "text_raw": "Hôm nay chúng ta vào phần kiến trúc.",
  "words": [
    { "text": "Hôm", "start_ms": 25400, "end_ms": 25650 },
    { "text": "nay", "start_ms": 25650, "end_ms": 25900 }
  ]
}
```

Sự kiện `chunk` của PT1 thuộc pass 2. Pass 1 của phiên nghe đi qua WebSocket, không đi qua kênh này. Khi job live chạy pass 2, kênh SSE của job đó dùng cùng schema.

## 5. Transcript

### `GET /api/jobs/{job_id}/transcript`

```json
{
  "pass": 2,
  "segments": [
    {
      "id": "...",
      "position": 0,
      "start_ms": 25400,
      "end_ms": 29800,
      "text_raw": "...",
      "text_cleaned": null,
      "text_edited": null,
      "speaker_label": "SPEAKER_00",
      "speaker_name": "An",
      "words": [{ "text": "Hôm", "start_ms": 25400, "end_ms": 25650, "speaker_label": "SPEAKER_00" }]
    }
  ],
  "speakers": [{ "label": "SPEAKER_00", "display_name": "Lê Hải Đăng", "source": "voice_profile" }]
}
```

`pass` là pass cao nhất có ít nhất một câu. Job live đang chạy pass 2 mà chưa có câu pass 2 thì `pass` vẫn là 1.

`speaker_name` là alias nếu có, ngược lại bằng `speaker_label`. Null khi câu chưa được gán. `source` của người nói là `manual`, `voice_profile`, hoặc null khi chưa có tên.

`words` rỗng ở pass 1.

### `PATCH /api/jobs/{job_id}/segments/{segment_id}`

Chỉ khi job `ready`, hoặc job `failed` mà transcript đang trả pass 1.

```json
{ "text_edited": "Câu người dùng sửa." }
```

`text_edited: null` xóa bản sửa. `200` trả một segment cùng dạng trong transcript.

### `PATCH /api/jobs/{job_id}/speakers/{label}`

`label` là chuỗi đã mã hóa URL, ví dụ `SPEAKER_00`.

```json
{ "display_name": "An" }
```

Chuỗi rỗng xóa alias. Có chữ thì `source` của alias thành `manual`. `200` trả `{ "label": "SPEAKER_00", "display_name": "An", "source": "manual" }`.

## 6. Audio

### `POST /api/jobs/{job_id}/media-token`

`200`:

```json
{ "token": "...", "expires_in": 300, "url": "/api/media/{token}" }
```

Token dùng nhiều lần cho đến hết 5 phút, vì trình phát gửi nhiều request Range.

### `GET /api/media/{token}`

Không cần Bearer. Token sai hoặc hết hạn trả 404.

`Content-Type: audio/ogg`. `Accept-Ranges: bytes`. Hỗ trợ header `Range` và trả `206` với `Content-Range` khi client xin một khoảng.

## 7. Phiên nghe

### `POST /api/live/sessions`

```json
{ "title": "Buổi học", "vocabulary": "FastAPI", "num_speakers": 2 }
```

Request này lấy `gpu:lock` bằng `SET NX` trước khi tạo session. GPU đang bận trả `gpu_busy` và không tạo session. Tác vụ worker chỉ gia hạn khóa. Pass 2 của chính phiên đó chạy xong thì khóa mới được nhả. Thành công `201`:

Cùng transaction với session, API tạo job `source = live`, `status = capturing`, và gắn `job_id`. Các câu nháp đã chốt ghi vào pass 1 của job đó.

```json
{
  "session_id": "...",
  "job_id": "...",
  "ticket": "...",
  "expires_in": 60,
  "ws_path": "/api/live/sessions/{session_id}/stream"
}
```

### `POST /api/live/sessions/{session_id}/ticket`

Chỉ khi session đang `capturing`. Trả ticket mới, cùng dạng ba field `ticket`, `expires_in`, `ws_path`.

### `GET /api/live/sessions/{session_id}`

```json
{
  "id": "...",
  "status": "capturing",
  "job_id": "...",
  "title": "Buổi học"
}
```

`job_id` có ngay từ lúc tạo. Trong lúc `capturing`, transcript của job là pass 1.

### WebSocket `/api/live/sessions/{session_id}/stream?ticket=`

Tin client gửi:

| Khung | Nội dung |
|---|---|
| Text, tin đầu tiên, trong 5 giây | `{"type":"hello","sample_rate":16000}` |
| Binary | PCM s16le mono. 100 ms là 3200 byte. Độ dài khác chấp nhận khi chẵn byte và tương ứng 20–200 ms |
| Text | `{"type":"stop"}` |

Tin server gửi, toàn bộ là text JSON:

| `type` | Field |
|---|---|
| `hello_ok` | `session_id` |
| `draft` | `segment_id`, `start_ms`, `end_ms`, `text`, `stable`, `seq` |
| `warning` | `code`, `message` |
| `stopped` | `job_id` |
| `error` | `code`, `message` |

Cùng một `segment_id` với `stable: false` nghĩa là thay bong bóng đang mở. `stable: true` chốt câu đó.

Sau `hello_ok` của một lần nối lại, server gửi thêm một tin `draft` với `stable: false` nếu Redis còn `live:{session_id}:open_draft`. Không còn key thì không gửi tin giả.

Server đóng socket sau `stopped` hoặc `error`.

### `POST /api/live/sessions/{session_id}/stop`

Dùng khi client không còn socket. Cùng hiệu lực với tin `stop`. `202` và body session. Đã dừng rồi thì trả trạng thái hiện tại, không tạo job thứ hai.

## 8. Hồ sơ giọng

### `GET /api/voice-profiles`

Trả hồ sơ của tài khoản đang đăng nhập.

```json
{
  "items": [
    {
      "id": "...",
      "display_name": "Lê Hải Đăng",
      "status": "ready",
      "duration_ms": 30000,
      "stale": false,
      "created_at": "2026-10-16T01:02:03Z"
    }
  ]
}
```

`stale: true` khi vector được tính bằng pipeline khác với pipeline đang cài. Hồ sơ đó không tham gia gán tên cho đến khi ghi lại.

### `POST /api/voice-profiles`

`multipart/form-data`: `file` và `display_name` (1 đến 80 ký tự). Tài khoản đã có 20 hồ sơ thì `validation`. Mẫu sau khi chuẩn hóa phải dài 20 đến 40 giây và còn ít nhất 15 giây có tiếng.

`202`:

```json
{ "profile_id": "...", "status": "processing" }
```

Việc tính vector là `app.tasks.enroll_voice` trên hàng `gpu`. Khóa GPU đang bận thì task `retry` sau 5 giây, giống PT1. `GET /api/voice-profiles/{profile_id}` trả `processing`, `ready`, hoặc `failed`.

### `DELETE /api/voice-profiles/{profile_id}`

Xóa hồ sơ, vector, và file mẫu. `204`. Alias `voice_profile` đã gán ở các job cũ giữ nguyên tên đã ghi.

## 9. Đánh dấu và việc tại câu

Cả hai nhóm chỉ nhận job `ready`, hoặc job `failed` khi transcript đang trả pass 1. Trạng thái khác trả `invalid_state`.

### `GET /api/jobs/{job_id}/highlights`

```json
{
  "items": [
    { "id": "...", "segment_id": "...", "quote": "phần kiến trúc", "start_ms": 25400, "end_ms": 28000 }
  ]
}
```

### `POST /api/jobs/{job_id}/highlights`

```json
{ "segment_id": "...", "quote": "phần kiến trúc", "start_ms": 25400, "end_ms": 28000 }
```

`quote` từ 1 đến 500 ký tự. `start_ms` nhỏ hơn `end_ms` và cả hai nằm trong câu. Câu phải thuộc pass transcript đang trả. `201` trả một phần tử cùng dạng GET.

### `DELETE /api/jobs/{job_id}/highlights/{highlight_id}`

`204`.

### `GET /api/jobs/{job_id}/actions`

```json
{
  "items": [
    {
      "id": "...",
      "segment_id": "...",
      "start_ms": 25400,
      "owner": "",
      "task": "Gửi lại sơ đồ cho cả nhóm",
      "deadline": "",
      "source": "manual"
    }
  ]
}
```

Danh sách này chỉ chứa việc `manual`. Việc do mẫu cuộc họp sinh ra nằm trong kết quả LLM của lần `summarize` mới nhất.

### `POST /api/jobs/{job_id}/actions`

```json
{ "segment_id": "...", "task": "Gửi lại sơ đồ cho cả nhóm", "owner": "", "deadline": "" }
```

`task` từ 1 đến 500 ký tự. `owner` và `deadline` tối đa 200 ký tự, được phép rỗng. `start_ms` lấy từ câu. `201` trả một phần tử, `source` là `manual`.

### `PATCH /api/jobs/{job_id}/actions/{action_id}`

Cùng các field `task`, `owner`, `deadline`. `200`.

### `DELETE /api/jobs/{job_id}/actions/{action_id}`

`204`.

## 10. LLM

### `POST /api/jobs/{job_id}/llm`

Chỉ khi job `ready`, hoặc `failed` với transcript pass 1 còn đọc được.

```json
{ "task": "summarize", "template": "meeting", "restart": false }
```

`task` là `clean` hoặc `summarize`. `template` bắt buộc khi `task` là `summarize`, và chỉ được `meeting` hoặc `lecture`. `restart` chỉ có hiệu lực với `clean`: `true` thì xóa `text_cleaned` của pass đang làm trước khi chạy. Mặc định `false`, và lần chạy sau một lần `failed` chỉ gửi các câu còn `text_cleaned` null.

Run thực thi trên hàng Celery `io`, không trên hàng `gpu`. `202`:

```json
{ "run_id": "...", "task": "summarize", "status": "running" }
```

Một job chỉ có một run `running`. Run thứ hai trả `invalid_state`.

### `GET /api/jobs/{job_id}/llm/{task}`

`task` trên path là `clean` hoặc `summarize`. Trả lần chạy mới nhất của tác vụ đó.

`clean` thành công:

```json
{
  "run_id": "...",
  "task": "clean",
  "status": "done",
  "model": "tên-trong-LLM_MODEL",
  "result": null
}
```

Chữ đã ghi vào `text_cleaned`. Client tải lại transcript.

`summarize` thành công kèm `"template": "meeting"` hoặc `"lecture"`.

Mẫu `meeting`, `result` là:

```json
{
  "objective": "...",
  "open_issues": [{ "timestamp": "12:04", "text": "..." }],
  "decisions": [{ "timestamp": "12:08", "text": "..." }],
  "actions": [
    { "timestamp": "12:10", "owner": "An", "task": "Gửi biên bản", "deadline": "thứ Sáu" }
  ]
}
```

Mẫu `lecture`, `result` là:

```json
{
  "overview": "...",
  "concepts": [{ "timestamp": "05:10", "term": "chunk", "explanation": "..." }],
  "examples": [{ "timestamp": "08:00", "text": "..." }],
  "exam_notes": [{ "timestamp": "40:00", "text": "..." }]
}
```

`status` còn có `running` và `failed`. Khi `failed`, thêm `error_code` và `error_message`.

## 11. Xuất file

### `POST /api/jobs/{job_id}/exports`

```json
{ "format": "srt", "text": "auto", "include_speakers": true }
```

| Field | Giá trị |
|---|---|
| `format` | `md`, `docx`, `pdf`, `srt`, `vtt` |
| `text` | `auto`, `raw`, `cleaned`, `edited` |
| `include_speakers` | boolean, mặc định `true` |

`auto` dùng đúng thứ tự hiện chữ của kiến trúc. `edited` hoặc `cleaned` mà câu không có lớp đó thì rơi về lớp bên dưới, cùng thứ tự ấy.

Thành công `200` là file tải về.

| Format | Content-Type | Tên file |
|---|---|---|
| `md` | `text/markdown; charset=utf-8` | `{title}.md` |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `{title}.docx` |
| `pdf` | `application/pdf` | `{title}.pdf` |
| `srt` | `application/x-subrip; charset=utf-8` | `{title}.srt` |
| `vtt` | `text/vtt; charset=utf-8` | `{title}.vtt` |

Markdown và DOCX của transcript là các câu theo thời gian. Nếu job có lần `summarize` thành công mới nhất, phần biên bản đứng trước transcript và dựng theo `template` của lần đó. Mẫu `meeting` có mục tiêu, vấn đề tồn đọng, quyết định, và việc do LLM đề xuất. Mẫu `lecture` có tóm tắt, khái niệm, ví dụ, và dặn dò ôn. Việc `manual` là một mục riêng sau biên bản khi danh sách không rỗng. Các đoạn đánh dấu thành một mục nữa, mỗi dòng có mốc và `quote`. PDF nhúng Noto Sans.

SRT và VTT là các câu, một cue một câu. `include_speakers: true` và câu có tên thì dòng chữ bắt đầu bằng tên và dấu hai chấm.

Mốc SRT dùng dấu phẩy cho phần thập phân. Mốc VTT dùng dấu chấm. Cả hai lấy `start_ms` và `end_ms` của câu.

## 12. Sức khỏe

### `GET /api/health`

Không cần token.

```json
{ "status": "ok" }
```

Endpoint này không kiểm tra GPU.

## 13. Postgres

Khóa chính UUID, trừ `job_events.id` và các khóa thay thế đã ghi. Thời điểm là `timestamptz`.

```sql
create table users (
  id uuid primary key,
  email text not null unique,
  password_hash text not null,
  display_name text not null,
  created_at timestamptz not null
);

create table refresh_tokens (
  id uuid primary key,
  user_id uuid not null references users (id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz
);

create table jobs (
  id uuid primary key,
  user_id uuid not null references users (id) on delete cascade,
  title text not null,
  source text not null check (source in ('upload', 'live')),
  status text not null check (status in (
    'queued', 'capturing', 'preprocessing', 'transcribing', 'diarizing', 'ready', 'failed', 'cancelled'
  )),
  error_code text,
  error_message text,
  warnings jsonb not null default '[]',
  audio_path text,
  duration_ms integer,
  vocabulary text,
  num_speakers integer check (num_speakers between 1 and 20),
  diarization_device text check (diarization_device in ('cuda', 'cpu')),
  created_at timestamptz not null,
  started_at timestamptz,
  finished_at timestamptz
);

create index jobs_user_created_idx on jobs (user_id, created_at desc);
create index refresh_tokens_user_idx on refresh_tokens (user_id);

create table live_sessions (
  id uuid primary key,
  user_id uuid not null references users (id) on delete cascade,
  job_id uuid references jobs (id) on delete set null,
  title text not null,
  status text not null check (status in ('capturing', 'stopping', 'finalized', 'failed')),
  vocabulary text,
  num_speakers integer check (num_speakers between 1 and 20),
  pcm_path text,
  created_at timestamptz not null,
  ended_at timestamptz
);

create table segments (
  id uuid primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  pass smallint not null check (pass in (1, 2)),
  position integer not null,
  start_ms integer not null,
  end_ms integer not null,
  text_raw text not null,
  text_cleaned text,
  text_edited text,
  speaker_label text,
  unique (job_id, pass, position)
);

create table words (
  id uuid primary key,
  segment_id uuid not null references segments (id) on delete cascade,
  position integer not null,
  text text not null,
  start_ms integer not null,
  end_ms integer not null,
  speaker_label text,
  unique (segment_id, position)
);

create table speaker_aliases (
  job_id uuid not null references jobs (id) on delete cascade,
  speaker_label text not null,
  display_name text not null,
  source text not null check (source in ('manual', 'voice_profile')),
  primary key (job_id, speaker_label)
);

create table job_events (
  id bigint generated always as identity primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  seq integer not null,
  event_type text not null,
  payload jsonb not null,
  created_at timestamptz not null,
  unique (job_id, seq)
);

create table llm_runs (
  id uuid primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  task text not null check (task in ('clean', 'summarize')),
  template text check (template in ('meeting', 'lecture')),
  status text not null check (status in ('running', 'done', 'failed')),
  model_name text,
  result jsonb,
  error_code text,
  error_message text,
  created_at timestamptz not null,
  finished_at timestamptz,
  check (task = 'clean' or template is not null)
);

create table llm_map_shards (
  run_id uuid not null references llm_runs (id) on delete cascade,
  shard_index integer not null,
  input_start_ms integer not null,
  input_end_ms integer not null,
  status text not null check (status in ('running', 'done', 'failed')),
  result jsonb,
  primary key (run_id, shard_index)
);

create table media_tokens (
  token_hash text primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  expires_at timestamptz not null
);

create table ws_tickets (
  token_hash text primary key,
  session_id uuid not null references live_sessions (id) on delete cascade,
  expires_at timestamptz not null
);

create table voice_profiles (
  id uuid primary key,
  user_id uuid not null references users (id) on delete cascade,
  display_name text not null,
  status text not null check (status in ('processing', 'ready', 'failed')),
  embedding bytea,
  embedding_dim integer,
  embedding_model text,
  sample_path text,
  duration_ms integer,
  error_message text,
  created_at timestamptz not null
);

create table highlights (
  id uuid primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  segment_id uuid not null references segments (id) on delete cascade,
  quote text not null,
  start_ms integer not null,
  end_ms integer not null,
  created_at timestamptz not null
);

create table action_items (
  id uuid primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  segment_id uuid references segments (id) on delete set null,
  start_ms integer,
  owner text not null default '',
  task text not null,
  deadline text not null default '',
  source text not null check (source in ('manual')),
  created_at timestamptz not null
);

create index live_sessions_job_idx on live_sessions (job_id);
create index voice_profiles_user_idx on voice_profiles (user_id);
create index highlights_job_idx on highlights (job_id, created_at);
create index action_items_job_idx on action_items (job_id, created_at);
create index llm_runs_job_task_created_idx on llm_runs (job_id, task, created_at desc);
create index media_tokens_job_idx on media_tokens (job_id);
create index ws_tickets_session_idx on ws_tickets (session_id);
```

`warnings` là mảng object `{ "code", "message" }`. Token media và ticket WebSocket lưu SHA-256 của chuỗi gửi cho client.

`audio_path` trỏ tới `/data/audio/{job_id}.opus` trong volume. `pcm_path` trỏ tới file tạm của phiên và được xóa khi phiên sang `finalized` hoặc `failed`. `sample_path` của hồ sơ giọng trỏ tới `/data/voice/{user_id}/{profile_id}.opus` và được xóa cùng hồ sơ.
