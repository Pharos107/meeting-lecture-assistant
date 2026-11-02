# Bộ tài liệu triển khai

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.4  
**Ngày:** 2026-10-28  
**Trạng thái:** Đặc tả đủ để triển khai Phương thức 1 và Phương thức 2. Có bản phân tích luồng đối chiếu với code

Khi các tài liệu lệch nhau, dùng thứ tự này:

1. [`API_AND_DATA.md`](API_AND_DATA.md) là hợp đồng API, sự kiện, và cơ sở dữ liệu.
2. [`ARCHITECTURE_SPEC.md`](ARCHITECTURE_SPEC.md) là hành vi pipeline, GPU, và thuật toán.
3. [`TECH_STACK_AND_ENVIRONMENT.md`](TECH_STACK_AND_ENVIRONMENT.md) là phiên bản thư viện, Docker, và cây thư mục.
4. [`IDEA_AND_CHALLENGES.md`](IDEA_AND_CHALLENGES.md) là phạm vi sản phẩm và tiêu chí nghiệm thu.
5. [`FLOWS.md`](FLOWS.md) là bản tổng hợp luồng. Nó trích từ các file trên và từ code, không đặt ra quy định mới.
6. File này là nhật ký quyết định.

Đoạn mở đầu bằng "Hướng tối ưu" trong các file trên là đề xuất chưa khóa. Chỉ làm theo sau khi đo, rồi sửa đoạn đó thành quy định và thêm một dòng vào bảng quyết định.

## Cách đọc

| Tài liệu | Việc của nó |
|---|---|
| [Ý tưởng và thách thức](IDEA_AND_CHALLENGES.md) | Bài toán, phạm vi, tính năng, tiêu chí nghiệm thu |
| [Kiến trúc](ARCHITECTURE_SPEC.md) | Luồng PT1, luồng PT2, cắt âm, STT, diarization, chạy chữ, hỏi đáp bằng LLM |
| [API và dữ liệu](API_AND_DATA.md) | REST, SSE, WebSocket, schema Postgres, mã lỗi |
| [Công nghệ và môi trường](TECH_STACK_AND_ENVIRONMENT.md) | Thư viện, biến môi trường, Docker, GPU, Git |
| [Phân tích luồng](FLOWS.md) | Tác nhân, use case, sơ đồ tuần tự từng luồng, key Redis, file trên volume, hiện trạng code và khoảng trống |

## Quyết định đã khóa

| Mã | Quyết định |
|---|---|
| D1 | Phạm vi triển khai gồm cả hai phương thức: tải file (PT1) và nghe trực tiếp (PT2). |
| D2 | LLM là API cloud tương thích OpenAI (`POST {LLM_BASE_URL}/chat/completions`), có stream và ngữ cảnh từ 128 nghìn token. Bản này dùng `gemini-3.5-flash-lite` qua endpoint tương thích OpenAI của Gemini. Tên model vẫn là cấu hình `LLM_MODEL`. |
| D3 | Phân biệt người nói bằng `pyannote/speaker-diarization-3.1` là bước bắt buộc của bản demo. Job vẫn `ready` nếu bước này lỗi, kèm cảnh báo. |
| D4 | Có đăng ký và đăng nhập. Mọi job, phiên nghe, và file âm thanh gắn với một tài khoản. |
| D5 | Máy mục tiêu là NVIDIA VRAM dưới 6GB. Whisper chạy `int8`, một model trong VRAM tại một thời điểm. |
| D6 | Frontend là Next.js App Router, TypeScript, Tailwind, shadcn/ui. |
| D7 | PT1 đẩy chữ bằng SSE qua `fetch`. PT2 đẩy PCM lên bằng WebSocket. |
| D8 | Chỉ worker hàng `gpu` được nạp Whisper và pyannote. FastAPI không giữ model. |
| D9 | File nghe lại là Opus trên server, giữ đến khi người dùng xóa job. |
| D10 | `text_raw` và `text_edited` là hai lớp riêng. Không chuẩn hóa văn bản ở bản này. Nếu cần thì làm bằng code, không dùng LLM. |
| D11 | Cửa vào trình duyệt là Caddy. `/api` sang FastAPI, kể cả WebSocket và SSE. Next.js không proxy các đường này. |
| D12 | Hàng `gpu` chạy PT1, PT2, và ghi danh giọng. Hỏi đáp chạy trong FastAPI, không qua Celery. PT1 thấy khóa đang bận thì `retry` sau 5 giây. |
| D13 | PT2 là pha kép: nháp bằng model `small` khi đang nghe, rồi `large-v3-turbo` và pyannote quét lại file đã thu khi phiên dừng. |
| D14 | Mỗi tài khoản có hồ sơ giọng nói. Sau diarization, cụm giọng đủ giống hồ sơ được gán tên của hồ sơ. Đổi tên tay không bị bước này ghi đè. |
| D15 | Trang job là hai vùng: trình phát và transcript. Bôi đen một đoạn trong câu để đánh dấu hoặc tạo việc cần làm tại mốc đó. |
| D16 | LLM chỉ dùng để người dùng hỏi về nội dung transcript của một bản ghi. Không có tác vụ biên bản theo mẫu. Lịch sử hỏi đáp lưu theo bản ghi. |
| D17 | Trang sau đăng nhập là khung ba vùng: menu điều hướng bên trái, nội dung ở giữa, dãy công cụ của job bên phải. Tạo bản ghi là hộp thoại, không chuyển trang. |

## Lịch sử phiên bản

| Phiên bản | Ngày | Thay đổi |
|---|---|---|
| 1.3 | 2026-10-16 | Khóa đặc tả PT1, PT2, hồ sơ giọng, hai mẫu biên bản |
| 1.4 | 2026-10-28 | Thêm [`FLOWS.md`](FLOWS.md). Thêm các đoạn "Hướng tối ưu" từ lượt đánh giá thiết kế vào kiến trúc, API, môi trường, và ý tưởng. Khóa thêm yêu cầu cấu hình: `visibility_timeout` của Celery, ghim phiên bản torch, ctranslate2, faster-whisper, pyannote, mã lỗi `llm_upstream`, đọc từ của transcript trong một truy vấn. Làm rõ FFmpeg.wasm đang là bản đơn luồng. Ghi rõ những gì code đã làm mà đặc tả chưa nói: mã `429 rate_limited`, mã lỗi WebSocket, kênh `job:{job_id}:events`, cạnh `failed → queued` và việc dọn đánh dấu khi chạy lại. Cập nhật cây thư mục theo repo. Không đổi quyết định D1–D16 |
| 1.4.1 | 2026-10-29 | Code: pipeline PT1 thật, các trang job, tự làm mới token, cấu hình Celery. Ghim bộ ứng viên torch 2.5.1 cu121, ctranslate2 4.5.0, faster-whisper 1.1.1, pyannote.audio 3.3.2, `huggingface_hub<1.0`. Cập nhật hiện trạng ở [`FLOWS.md`](FLOWS.md). Không đổi quyết định D1–D16 |
| 1.4.2 | 2026-10-29 | Bộ phiên bản đã chạy một job PT1 có diarization trên RTX 4050 Laptop 6GB. Image nền ghim `python:3.11-slim-bookworm`. `requirements.txt` ghim lại torch và torchaudio. Worker kiểm GPU trong tiến trình riêng. Thêm #18 ở [`FLOWS.md`](FLOWS.md). Không đổi quyết định D1–D16 |
| 1.4.3 | 2026-10-29 | Khóa bộ lọc chữ bịa ở kiến trúc mục 2.4 sau khi đo trên 3 bản tin VTV24: `hallucination_silence_threshold=2.0`, ngưỡng 12 từ/giây, luật lời mời đăng ký kênh. Ghép mảnh word không có dấu cách đầu. Ghi số đo độ dài chunk ở kiến trúc mục 2.3. Đóng #16, thêm #19 và #20 ở [`FLOWS.md`](FLOWS.md). Không đổi quyết định D1–D16 |
| 1.5 | 2026-10-31 | Thêm D17: khung ba vùng và hộp thoại tạo bản ghi, viết lại kiến trúc mục 2.7. Thay cột trái của trang job bằng trình phát ở đáy và panel công cụ. Giao diện gọi job là bản ghi, code và API giữ tên `job` |
| 1.6 | 2026-11-02 | LLM chuyển sang hỏi đáp trên transcript: đổi D2, D10, D12, D16, viết lại kiến trúc mục 6, API mục 10, và F7. Bỏ chuẩn hóa bằng LLM, biên bản theo mẫu, `text_cleaned`, `llm_runs`, `llm_map_shards`, `worker-io`. Thêm bảng `chat_messages`, migration `0003_chat`. Chưa chạy với model thật, xem #23 ở [`FLOWS.md`](FLOWS.md) |
| 1.6.1 | 2026-11-02 | Chọn `gemini-3.5-flash-lite`, cập nhật D2. Thêm mã `llm_rate_limited`. Thiếu `LLM_API_KEY` cũng trả `llm_not_configured` |
| 1.6.2 | 2026-11-02 | Gộp đoạn Whisper cắt giữa câu sau khi gán người nói, kiến trúc mục 2.5 |

## Việc còn mở

| Hạng mục | Cách xử lý trong đặc tả |
|---|---|
| Khóa Gemini và gói dùng | Điền `LLM_API_KEY` từ AI Studio. Gói miễn phí chỉ dùng cho dữ liệu demo, vì điều khoản cho phép Google dùng nội dung và cấm gửi nội dung nhạy cảm. Họp thật cần gói trả phí. |
| Mã card màn hình | Chưa gắn một SKU. Ngân sách thiết kế là card dưới 6GB, tính toán chặt cho card 4GB. |
| Model bản chuẩn | `large-v3-turbo` là mặc định. So CER với PhoWhisper trên bộ đối chiếu trước khi khóa. |
| Các đoạn "Hướng tối ưu" | Chưa khóa. Đo trên bộ đối chiếu rồi mới ghi thành quy định. |
| Phần code chưa hiện thực | Liệt kê và xếp mức ở [`FLOWS.md` mục 13](FLOWS.md#13-khoảng-trống-giữa-đặc-tả-và-code). |

## Thuật ngữ

| Từ | Nghĩa trong dự án |
|---|---|
| PT1 | Người dùng chọn file audio hoặc video có sẵn. |
| PT2 | Người dùng thu micro hoặc chia sẻ âm thanh tab/cửa sổ. |
| Pass 1 | Bản nháp của model `small` trong PT2. |
| Pass 2 | Bản chuẩn của model `large-v3-turbo`. PT1 chỉ có pass 2. |
| Chunk | Đoạn PCM 20–30 giây đưa vào Whisper ở bản chuẩn. |
| Raw / edited | Lần lượt là chữ của model nhận dạng và chữ người dùng sửa. |
| Hồ sơ giọng | Mẫu giọng đã lưu của một tài khoản, dùng để gán tên sau diarization. |
| Trợ lý AI | Panel hỏi đáp về transcript của một bản ghi. |
