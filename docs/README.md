# Bộ tài liệu triển khai

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.3  
**Ngày:** 2026-10-16  
**Trạng thái:** Đặc tả đủ để triển khai Phương thức 1 và Phương thức 2

Khi các tài liệu lệch nhau, dùng thứ tự này:

1. [`API_AND_DATA.md`](API_AND_DATA.md) là hợp đồng API, sự kiện, và cơ sở dữ liệu.
2. [`ARCHITECTURE_SPEC.md`](ARCHITECTURE_SPEC.md) là hành vi pipeline, GPU, và thuật toán.
3. [`TECH_STACK_AND_ENVIRONMENT.md`](TECH_STACK_AND_ENVIRONMENT.md) là phiên bản thư viện, Docker, và cây thư mục.
4. [`IDEA_AND_CHALLENGES.md`](IDEA_AND_CHALLENGES.md) là phạm vi sản phẩm và tiêu chí nghiệm thu.
5. File này là nhật ký quyết định.

## Cách đọc

| Tài liệu | Việc của nó |
|---|---|
| [Ý tưởng và thách thức](IDEA_AND_CHALLENGES.md) | Bài toán, phạm vi, tính năng, tiêu chí nghiệm thu |
| [Kiến trúc](ARCHITECTURE_SPEC.md) | Luồng PT1, luồng PT2, cắt âm, STT, diarization, chạy chữ, LLM |
| [API và dữ liệu](API_AND_DATA.md) | REST, SSE, WebSocket, schema Postgres, mã lỗi |
| [Công nghệ và môi trường](TECH_STACK_AND_ENVIRONMENT.md) | Thư viện, biến môi trường, Docker, GPU, Git |

## Quyết định đã khóa

| Mã | Quyết định |
|---|---|
| D1 | Phạm vi triển khai gồm cả hai phương thức: tải file (PT1) và nghe trực tiếp (PT2). |
| D2 | LLM đi qua API tương thích OpenAI (`POST {LLM_BASE_URL}/chat/completions`). Tên model là cấu hình `LLM_MODEL`, chưa chọn ở bản này. |
| D3 | Phân biệt người nói bằng `pyannote/speaker-diarization-3.1` là bước bắt buộc của bản demo. Job vẫn `ready` nếu bước này lỗi, kèm cảnh báo. |
| D4 | Có đăng ký và đăng nhập. Mọi job, phiên nghe, và file âm thanh gắn với một tài khoản. |
| D5 | Máy mục tiêu là NVIDIA VRAM dưới 6GB. Whisper chạy `int8`, một model trong VRAM tại một thời điểm. |
| D6 | Frontend là Next.js App Router, TypeScript, Tailwind, shadcn/ui. |
| D7 | PT1 đẩy chữ bằng SSE qua `fetch`. PT2 đẩy PCM lên bằng WebSocket. |
| D8 | Chỉ worker hàng `gpu` được nạp Whisper và pyannote. FastAPI không giữ model. |
| D9 | File nghe lại là Opus trên server, giữ đến khi người dùng xóa job. |
| D10 | `text_raw`, `text_cleaned`, và `text_edited` là ba lớp riêng. Giao diện gạt được giữa bản gốc và bản đã chuẩn hóa. |
| D11 | Cửa vào trình duyệt là Caddy. `/api` sang FastAPI, kể cả WebSocket và SSE. Next.js không proxy các đường này. |
| D12 | Hàng `gpu` chạy PT1, PT2, và ghi danh giọng. Hàng `io` chạy LLM. PT1 thấy khóa đang bận thì `retry` sau 5 giây. |
| D13 | PT2 là pha kép: nháp bằng model `small` khi đang nghe, rồi `large-v3-turbo` và pyannote quét lại file đã thu khi phiên dừng. |
| D14 | Mỗi tài khoản có hồ sơ giọng nói. Sau diarization, cụm giọng đủ giống hồ sơ được gán tên của hồ sơ. Đổi tên tay không bị bước này ghi đè. |
| D15 | Trang job là hai vùng: trình phát và transcript. Bôi đen một đoạn trong câu để đánh dấu hoặc tạo việc cần làm tại mốc đó. |
| D16 | Biên bản có hai mẫu: cuộc họp doanh nghiệp, và ghi chú bài giảng. Người dùng chọn mẫu lúc bấm. |

## Việc còn mở

| Hạng mục | Cách xử lý trong đặc tả |
|---|---|
| Model LLM cụ thể | Để trống `LLM_MODEL`. Điền trước khi chạy hậu kỳ. Schema JSON đầu ra đã khóa. |
| Mã card màn hình | Chưa gắn một SKU. Ngân sách thiết kế là card dưới 6GB, tính toán chặt cho card 4GB. |

## Thuật ngữ

| Từ | Nghĩa trong dự án |
|---|---|
| PT1 | Người dùng chọn file audio hoặc video có sẵn. |
| PT2 | Người dùng thu micro hoặc chia sẻ âm thanh tab/cửa sổ. |
| Pass 1 | Bản nháp của model `small` trong PT2. |
| Pass 2 | Bản chuẩn của model `large-v3-turbo`. PT1 chỉ có pass 2. |
| Chunk | Đoạn PCM 20–30 giây đưa vào Whisper ở bản chuẩn. |
| Raw / cleaned / edited | Lần lượt là chữ của model, chữ LLM đã chuẩn hóa, và chữ người dùng sửa. |
| Hồ sơ giọng | Mẫu giọng đã lưu của một tài khoản, dùng để gán tên sau diarization. |
| Mẫu biên bản | `meeting` là biên bản cuộc họp. `lecture` là ghi chú bài giảng. |
