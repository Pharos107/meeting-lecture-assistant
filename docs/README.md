# Bộ tài liệu triển khai

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.9.1  
**Ngày:** 2026-11-09  
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
| D13 | PT2 là pha kép: nháp bằng `large-v3-turbo` beam 1 khi đang nghe, rồi `large-v3-turbo` beam 5 và pyannote quét lại file đã thu khi phiên dừng. Pass 2 dùng lại model đã nạp cho bản nháp. |
| D14 | Mỗi tài khoản có hồ sơ giọng nói. Sau diarization, cụm giọng đủ giống hồ sơ được gán tên của hồ sơ. Đổi tên tay không bị bước này ghi đè. |
| D15 | Trang job là hai vùng: trình phát và transcript. Bôi đen một đoạn trong câu để đánh dấu hoặc tạo việc cần làm tại mốc đó. |
| D16 | LLM chỉ dùng để người dùng hỏi về nội dung transcript của một bản ghi. Không có tác vụ biên bản theo mẫu. Lịch sử hỏi đáp lưu theo bản ghi. |
| D17 | Trang sau đăng nhập là khung ba vùng: menu điều hướng bên trái, nội dung ở giữa, dãy công cụ của job bên phải. Tạo bản ghi là hộp thoại, không chuyển trang. |
| D18 | Chia sẻ một bản ghi bằng liên kết chỉ đọc, ai có liên kết cũng xem được mà không cần đăng nhập. Chỉ gồm transcript và tên người nói. Chủ tắt được bất cứ lúc nào. Phiên nghe chia sẻ được ngay lúc đang ghi, người xem theo dõi chữ nháp trực tiếp. |
| D19 | Model bản chuẩn là `large-v3-turbo`, cùng model với bản nháp PT2. Chốt ngày 2026-11-09 sau vòng đo trên 7 bài giảng và cuộc họp thật: gộp 6 bài, turbo CER 23,66% và WER 32,05%, PhoWhisper CER 24,97% và WER 34,68%, turbo nhanh gấp 1,85 lần. Không chờ ghi âm họp do nhóm tự thu. |

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
| 1.6.3 | 2026-11-02 | Panel công cụ của trang job đổi được độ rộng, kiến trúc mục 2.7 |
| 1.7 | 2026-11-02 | Thêm D18: liên kết chia sẻ chỉ đọc, bảng `job_shares`, migration `0004_share`, API mục 5, kiến trúc mục 2.7 và mục 8. Thanh tiêu đề trang job chiếm trọn cột, thêm `Cài đặt hiển thị` |
| 1.7.1 | 2026-11-03 | Luật lời mời đăng ký kênh ở kiến trúc mục 2.4 so khớp ở mọi vị trí trong câu, thêm cụm mới, quy "đăng kí" về "đăng ký". Ghi kết quả đo CER vòng hai trên dữ liệu thực tế, giữ `large-v3-turbo`. Cập nhật #19 và thứ tự làm tiếp ở [`FLOWS.md`](FLOWS.md). Không đổi quyết định D1–D18 |
| 1.7.2 | 2026-11-03 | Code PT2: vòng nháp trong `run_live_session`, bàn giao sang pass 2, trang `/live`. Kiến trúc mục 3.2 ghi tham số VAD của bản nháp và bản chốt rỗng, mục 3.3 ghi dấu `live:{sid}:worker` thay cho việc FastAPI nhả khóa. Code bước vá #19. Đóng #2, #7 ở [`FLOWS.md`](FLOWS.md). Không đổi quyết định D1–D18 |
| 1.7.3 | 2026-11-03 | Đổi D13: bản nháp PT2 dùng `large-v3-turbo` thay `small`, vì khi thử trên cuộc họp thật `small` sai quá nhiều chữ. Pass 2 dùng lại model đã nạp. Thêm `websockets` vào `requirements.txt`: thiếu gói này thì uvicorn trả 404 cho WebSocket. Whisper nạp từ cache trước khi hỏi Hugging Face |
| 1.8 | 2026-11-03 | Mở rộng D18: chia sẻ phiên nghe lúc đang ghi, thêm `GET /api/shared/{token}/live` và trường `state` ở API mục 5. Hỏi trợ lý được khi job live đang `capturing`. Trang `/live` có `Chia sẻ`, `Cài đặt hiển thị`, `Trợ lý AI`, và chữ nháp hiện dần từng ký tự, kiến trúc mục 3.3 |
| 1.8.1 | 2026-11-05 | Kiến trúc mục 2.3 thêm bước 7: nhận dạng riêng vùng VAD trống, vẫn rỗng thì giải mã greedy. Đo lại #19 và đo hỏi đáp #23 trên bộ dữ liệu thực tế, số đo ở `Báo Cáo/Báo cáo đo lại #19 và đo hỏi đáp #23 (2026-11-05).md`. Đóng #23, thêm #24 và #25 ở [`FLOWS.md`](FLOWS.md). Không đổi quyết định D1–D18 |
| 1.9 | 2026-11-09 | Kiến trúc mục 1: job PT1 nhường GPU cho phiên nghe, API thêm mã `gpu_yielding`. Mục 2.3: greedy khi cả chunk trống, thêm khoảng VAD bỏ trống mà to, kẹp PCM. Mục 2.4: bỏ câu lặp theo tỉ lệ nén, luật và phần cắt lời mời đăng ký kênh cho câu dài. Mục 2.5: tách câu tại chỗ đổi người nói. Mục 6: luồng LLM không có `finish_reason` là `llm_upstream`. `rate_limit` đếm trong Redis. Đóng #9, #18, #24, #25 ở [`FLOWS.md`](FLOWS.md). Số đo ở `Báo Cáo/Báo cáo chẩn đoán #19, đo PT2 và nhường GPU (2026-11-09).md`. Không đổi quyết định D1–D18 |
| 1.9.1 | 2026-11-09 | Thêm D19: chốt `large-v3-turbo` làm model bản chuẩn. Bỏ dòng model bản chuẩn khỏi việc còn mở, ghi các hướng tối ưu đã khóa. Cập nhật môi trường mục Whisper, ý tưởng mục 6, và thứ tự việc ở [`FLOWS.md`](FLOWS.md) mục 14 |

## Việc còn mở

| Hạng mục | Cách xử lý trong đặc tả |
|---|---|
| Khóa Gemini và gói dùng | Điền `LLM_API_KEY` từ AI Studio. Gói miễn phí chỉ dùng cho dữ liệu demo, vì điều khoản cho phép Google dùng nội dung và cấm gửi nội dung nhạy cảm. Họp thật cần gói trả phí. |
| Mã card màn hình | Chưa gắn một SKU. Ngân sách thiết kế là card dưới 6GB, tính toán chặt cho card 4GB. |
| Các đoạn "Hướng tối ưu" | Đo trên bộ đối chiếu rồi mới ghi thành quy định. Đã khóa ngày 2026-11-09: job PT1 nhường GPU cho phiên nghe (kiến trúc mục 1), tách câu tại chỗ đổi người nói (kiến trúc mục 2.5). Các đoạn còn lại chưa khóa. |
| Phần code chưa hiện thực | Liệt kê và xếp mức ở [`FLOWS.md` mục 13](FLOWS.md#13-khoảng-trống-giữa-đặc-tả-và-code). |

## Thuật ngữ

| Từ | Nghĩa trong dự án |
|---|---|
| PT1 | Người dùng chọn file audio hoặc video có sẵn. |
| PT2 | Người dùng thu micro hoặc chia sẻ âm thanh tab/cửa sổ. |
| Pass 1 | Bản nháp của PT2, `large-v3-turbo` beam 1, không có mốc từ và người nói. |
| Pass 2 | Bản chuẩn của model `large-v3-turbo`. PT1 chỉ có pass 2. |
| Chunk | Đoạn PCM 20–30 giây đưa vào Whisper ở bản chuẩn. |
| Raw / edited | Lần lượt là chữ của model nhận dạng và chữ người dùng sửa. |
| Hồ sơ giọng | Mẫu giọng đã lưu của một tài khoản, dùng để gán tên sau diarization. |
| Trợ lý AI | Panel hỏi đáp về transcript của một bản ghi. |
