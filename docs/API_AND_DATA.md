# API và dữ liệu

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.4  
**Ngày:** 2026-10-28  
**Vai trò của file này:** Hợp đồng để viết client và server. Hành vi pipeline nằm ở [kiến trúc](ARCHITECTURE_SPEC.md).

Thời gian trong JSON là số nguyên mili giây, mốc 0 là đầu file hoặc đầu phiên nghe. Chuỗi thời gian người đọc, dạng `MM:SS` hoặc `HH:MM:SS`, chỉ xuất hiện trong câu trả lời của trợ lý và file xuất.

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
| 409 | `gpu_busy` | Mở phiên nghe khi một phiên nghe khác đang giữ khóa GPU, hoặc khóa đang giữ chỗ cho người khác |
| 409 | `gpu_yielding` | Mở phiên nghe khi khóa GPU thuộc job PT1 hoặc việc ghi danh giọng. API đã xin nhường, client thử lại sau vài giây |
| 409 | `invalid_state` | Hủy, sửa, hoặc hỏi trợ lý khi trạng thái không cho phép |
| 409 | `chat_busy` | Bản ghi đang có một câu trả lời chạy |
| 413 | `file_too_large` | Vượt 64 MB Opus hoặc 500 MB file gốc |
| 415 | `unsupported_media` | Không có stream audio |
| 422 | `validation` | Sai field, kèm `fields` là map tên field sang câu lỗi |
| 422 | `duration_exceeded` | Dài hơn 3 giờ hoặc PCM ước lượng vượt 800 MB |
| 422 | `llm_not_configured` | Chưa có `LLM_MODEL` hoặc `LLM_API_KEY` |
| 422 | `llm_context_exceeded` | Transcript và lịch sử vượt ngữ cảnh của model |
| 429 | `rate_limited` | Quá 60 request mỗi phút từ một IP trên `register`, `login`, `POST /api/jobs`, hoặc `POST .../chat/messages` |
| 502 | `llm_upstream` | Không kết nối được server LLM, server trả lỗi HTTP khác 429, hoặc luồng đóng mà không có `finish_reason` |
| 503 | `gpu_oom` | Không nạp được Whisper trong phần VRAM còn lại |
| 504 | `llm_timeout` | Server LLM im lặng quá `LLM_TIMEOUT_SECONDS` |

`llm_rate_limited` chỉ đi bằng sự kiện `error` của SSE hỏi đáp, vì lỗi xảy ra sau khi stream đã mở.

Trần của `rate_limited` đếm theo cửa sổ trượt 60 giây. Có `REDIS_URL` thì đếm trong Redis, nên mọi bản uvicorn dùng chung trần. Không có Redis, hoặc Redis lỗi, thì mỗi tiến trình đếm riêng.

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

File đi trong một request. Mất kết nối giữa chừng thì phải tải lại từ đầu. Hướng tối ưu: tải theo phần và tiếp tục được, ví dụ giao thức tus.

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

Chỉ khi `failed`. Xóa câu và từ pass 2 cùng đánh dấu trên các câu đó, và xóa lịch sử hỏi đáp. Việc `manual` gắn với câu bị xóa giữ lại với `segment_id = null`. Pass 1 giữ nguyên. `202` và body job ở trạng thái `queued`. Giao diện phải cảnh báo trước khi gọi, vì đánh dấu và lịch sử hỏi đáp mất theo.

### `DELETE /api/jobs/{job_id}`

Xóa job, segment, word, sự kiện, lịch sử hỏi đáp, alias, đánh dấu, việc manual, session nghe gắn với job, file Opus, và file tạm. Hồ sơ giọng của tài khoản không bị xóa theo job. Nếu job đang `capturing`, worker dừng thu, không chạy pass 2, và nhả `gpu:lock` trước khi các dòng bị xóa. `204`.

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

Server đọc từ của cả job trong một truy vấn rồi nhóm theo `segment_id`. Không truy vấn từ theo từng câu, vì bài 3 giờ có khoảng 3.000 câu.

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

### `GET /api/jobs/{job_id}/share`

`200` trả trạng thái chia sẻ. Đang tắt thì `enabled` là `false`, hai trường còn lại là `null`.

```json
{ "enabled": true, "token": "...", "url": "/shared/..." }
```

### `PUT /api/jobs/{job_id}/share`

Bật chia sẻ, `200` trả cùng dạng. Gọi lại khi đang bật thì giữ nguyên token. Job chưa `ready` trả `409 invalid_state`, trừ job `source = live` đang `capturing`, `preprocessing`, `transcribing`, hoặc `diarizing`: phiên nghe chia sẻ được ngay lúc đang ghi.

### `DELETE /api/jobs/{job_id}/share`

Tắt chia sẻ, `204`. Liên kết cũ hết hiệu lực ngay. Bật lại sinh token mới. Gọi khi đang tắt vẫn trả `204`.

### `GET /api/shared/{token}`

Không cần đăng nhập. Token không tồn tại, đã tắt, hoặc job không xem được đều trả `404`. Xem được là job `ready`, hoặc job live ở một trong bốn trạng thái trên. Giới hạn 600 request mỗi phút theo IP, vượt thì `429 rate_limited`. Header `Cache-Control: no-store` và `X-Robots-Tag: noindex`.

```json
{
  "title": "Họp giao ban",
  "state": "ready",
  "duration_ms": 600000,
  "created_at": "2026-11-02T01:00:00Z",
  "segments": [
    { "start_ms": 0, "end_ms": 1800, "text": "Xin chào", "speaker": "An" }
  ]
}
```

`state` là `live` khi job đang `capturing`, `processing` khi đang chạy bản chuẩn, và `ready`. `segments` là pass cao nhất đang có câu, nên lúc `live` là các câu nháp đã chốt. `text` là `text_edited`, nếu null thì `text_raw`. `speaker` là tên hiển thị. Phản hồi không có id job, thông tin chủ, từng từ, đánh dấu, việc, hỏi đáp, hay đường dẫn audio.

### `GET /api/shared/{token}/live`

Không cần đăng nhập. SSE bản nháp của phiên đang ghi, chỉ khi job đang `capturing`, khác thì `404`. Cùng giới hạn request và header `X-Robots-Tag: noindex` như trên.

| `event` | `data` |
|---|---|
| `snapshot` | `{ "segments": [...] }`, các câu pass 1 đã chốt, mỗi câu có `segment_id`, `start_ms`, `end_ms`, `text`, `stable: true` |
| `draft` | `segment_id`, `start_ms`, `end_ms`, `text`, `stable`, cùng nghĩa với tin `draft` của WebSocket, không có `seq` |
| `ended` | `{}`. Phiên đã dừng hoặc bị hủy. Server đóng stream ngay sau tin này |

Server nghe kênh `live:{session_id}:out` trước rồi mới đọc câu đã chốt, nên câu chốt giữa hai bước không bị lỡ. Client khử trùng theo `segment_id`. Sau `snapshot`, server gửi câu đang mở nếu `open_draft` còn. Mỗi 2 giây server kiểm lại liên kết và trạng thái job. Chủ tắt chia sẻ, hoặc job rời `capturing`, thì gửi `ended` và đóng stream. Sau đó `GET /api/shared/{token}` của liên kết đã tắt trả `404`. Sau `ended`, client gọi lại `GET /api/shared/{token}` tới khi `state` là `ready`.

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

Request này lấy `gpu:lock` bằng `SET NX` trước khi tạo session. Khóa thuộc một phiên nghe khác thì trả `gpu_busy` và không tạo session. Khóa thuộc job PT1 hay việc ghi danh giọng thì API ghi id người dùng vào cờ `gpu:wanted` 30 giây, trả `gpu_yielding`, và cũng không tạo session. Job nhường thì giữ chỗ khóa 10 giây cho đúng người đó. Trang `/live` thử lại mỗi 3 giây, tối đa 90 giây. Lấy được khóa thì API xóa cờ. Cơ chế nhường ở kiến trúc mục 1. Tác vụ worker chỉ gia hạn khóa. Pass 2 của chính phiên đó chạy xong thì khóa mới được nhả. Thành công `201`:

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

`code` của tin `error`:

| `code` | Khi |
|---|---|
| `unauthorized` | Ticket sai, hết hạn, thuộc session khác, hoặc session không còn `capturing` |
| `gpu_busy` | `gpu:lock` đang thuộc id khác |
| `hello_timeout` | Không có tin `hello` trong 5 giây |
| `bad_request` | Tin đầu không phải `hello` với `sample_rate` 16000, khung PCM lẻ byte hoặc ngoài 20–200 ms, hoặc tin text không đọc được |
| `payload_too_large` | Tổng PCM của phiên vượt `MAX_DURATION_SECONDS` |
| `invalid_state` | Phiên đã đóng trong lúc socket xin quyền ghi |

Mỗi lần nối lại, socket mới giành quyền ghi PCM. Socket cũ thôi ghi và đóng mà không gửi `error`.

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
      "error_message": null,
      "created_at": "2026-10-16T01:02:03Z"
    }
  ]
}
```

`stale: true` khi vector được tính bằng pipeline khác với pipeline đang cài. Hồ sơ đó không tham gia gán tên cho đến khi ghi lại. `error_message` là lý do khi `status` là `failed`, ngược lại null.

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

Danh sách này chỉ chứa việc `manual`. Câu trả lời của trợ lý không tự thành việc.

### `POST /api/jobs/{job_id}/actions`

```json
{ "segment_id": "...", "task": "Gửi lại sơ đồ cho cả nhóm", "owner": "", "deadline": "" }
```

`task` từ 1 đến 500 ký tự. `owner` và `deadline` tối đa 200 ký tự, được phép rỗng. `start_ms` lấy từ câu. `201` trả một phần tử, `source` là `manual`.

### `PATCH /api/jobs/{job_id}/actions/{action_id}`

Cùng các field `task`, `owner`, `deadline`. `200`.

### `DELETE /api/jobs/{job_id}/actions/{action_id}`

`204`.

## 10. Hỏi đáp

### `POST /api/jobs/{job_id}/chat/messages`

Chỉ khi job `ready`, hoặc `failed` với transcript pass 1 còn đọc được, hoặc job `source = live` đang `capturing`. Lúc đang ghi, ngữ cảnh là các câu nháp đã chốt tới lúc hỏi, không có câu đang mở. Job live đang chạy bản chuẩn trả `invalid_state`, vì pass 1 và pass 2 đang lẫn nhau.

```json
{ "question": "Có những nhiệm vụ gì cần đề ra?" }
```

`question` từ 1 đến 2000 ký tự sau khi bỏ khoảng trắng hai đầu. Transcript trống trả `invalid_state`. Request mang `Accept: text/event-stream` và Bearer.

Lỗi kiểm tra trước khi gọi LLM trả JSON như các API khác, gồm `validation`, `invalid_state`, `chat_busy`, `llm_not_configured`, `llm_context_exceeded`, và `rate_limited`. Khi đó không tạo tin nhắn nào.

Qua bước kiểm tra, response là SSE với các header như mục 4. Đóng kết nối là dừng câu trả lời.

```text
event: start
data: {"question_id":"...","answer_id":"..."}

event: delta
data: {"text":"Có ba việc cần làm:"}

event: done
data: {"answer_id":"...","model":"tên-trong-LLM_MODEL"}

```

| `event` | `data` |
|---|---|
| `start` | `question_id`, `answer_id` |
| `delta` | `text`, là mảnh chữ tiếp theo |
| `done` | `answer_id`, `model` |
| `error` | `code` (`llm_upstream`, `llm_timeout`, `llm_rate_limited`), `message`. Phần đã nhận vẫn được lưu, tin nhắn ở trạng thái `failed` |

SSE này không có `seq` và không nối lại được. Kết nối rớt thì client đọc lại lịch sử.

### `GET /api/jobs/{job_id}/chat/messages`

Trả tối đa 200 tin nhắn gần nhất, cũ trước.

```json
{
  "items": [
    {
      "id": "...",
      "role": "user",
      "content": "Có những nhiệm vụ gì cần đề ra?",
      "status": "done",
      "created_at": "2026-11-02T08:00:00Z"
    },
    {
      "id": "...",
      "role": "assistant",
      "content": "- Anh Minh gửi báo cáo cuối vào thứ Sáu [00:31]",
      "status": "done",
      "created_at": "2026-11-02T08:00:01Z"
    }
  ]
}
```

`role` là `user` hoặc `assistant`. `status` là `streaming`, `done`, `stopped`, hoặc `failed`. Khi `failed`, thêm `error_code`. Mốc trong `content` là chuỗi `[MM:SS]` hoặc `[HH:MM:SS]`.

### `DELETE /api/jobs/{job_id}/chat/messages`

Xóa toàn bộ lịch sử hỏi đáp của bản ghi. Có câu trả lời đang chạy thì trả `chat_busy`. `204`.

## 11. Xuất file

### `POST /api/jobs/{job_id}/exports`

```json
{ "format": "srt", "text": "auto", "include_speakers": true }
```

| Field | Giá trị |
|---|---|
| `format` | `md`, `docx`, `pdf`, `srt`, `vtt` |
| `text` | `auto`, `raw` |
| `include_speakers` | boolean, mặc định `true` |

`auto` dùng `text_edited` nếu câu có bản sửa, ngược lại `text_raw`. `raw` luôn dùng `text_raw`.

Thành công `200` là file tải về.

| Format | Content-Type | Tên file |
|---|---|---|
| `md` | `text/markdown; charset=utf-8` | `{title}.md` |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `{title}.docx` |
| `pdf` | `application/pdf` | `{title}.pdf` |
| `srt` | `application/x-subrip; charset=utf-8` | `{title}.srt` |
| `vtt` | `text/vtt; charset=utf-8` | `{title}.vtt` |

Markdown và DOCX của transcript là các câu theo thời gian. Việc `manual` là một mục riêng đứng trước transcript khi danh sách không rỗng. Các đoạn đánh dấu thành một mục nữa, mỗi dòng có mốc và `quote`. Lịch sử hỏi đáp không đưa vào file xuất. PDF nhúng Noto Sans.

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

create table chat_messages (
  id uuid primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null default '',
  status text not null check (status in ('streaming', 'done', 'stopped', 'failed')),
  model_name text,
  error_code text,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table media_tokens (
  token_hash text primary key,
  job_id uuid not null references jobs (id) on delete cascade,
  expires_at timestamptz not null
);

create table job_shares (
  job_id uuid primary key references jobs (id) on delete cascade,
  token text not null unique,
  created_at timestamptz not null
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
create index chat_messages_job_created_idx on chat_messages (job_id, created_at);
create unique index chat_messages_one_streaming_idx on chat_messages (job_id) where status = 'streaming';
create index media_tokens_job_idx on media_tokens (job_id);
create index ws_tickets_session_idx on ws_tickets (session_id);
```

`warnings` là mảng object `{ "code", "message" }`. Token media và ticket WebSocket lưu SHA-256 của chuỗi gửi cho client. Token của `job_shares` lưu nguyên văn, vì chủ bản ghi phải lấy lại được đúng liên kết đã gửi. Đọc được bảng này cũng đã đọc được transcript, nên băm token không che thêm gì.

`audio_path` trỏ tới `/data/audio/{job_id}.opus` trong volume. `pcm_path` trỏ tới file tạm của phiên và được xóa khi phiên sang `finalized` hoặc `failed`. `sample_path` của hồ sơ giọng trỏ tới `/data/voice/{user_id}/{profile_id}.opus` và được xóa cùng hồ sơ.
