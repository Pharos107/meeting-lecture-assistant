# Ghi chú sửa báo cáo Word theo đặc tả 1.6

**File cần sửa:** `ĐACNPM_Nhóm_7.docx`  
**Ngày ghi:** 2026-11-02  
**Trạng thái:** Chưa sửa. Đây là danh sách để nhóm sửa sau.

## Thay đổi cần phản ánh

- LLM chỉ dùng để người dùng hỏi về nội dung transcript của một bản ghi.
- Bỏ chuẩn hóa văn bản bằng LLM. Nếu cần chuẩn hóa thì làm bằng code ở bản sau.
- Bỏ biên bản theo mẫu. Nội dung kiểu biên bản lấy bằng câu hỏi, có câu hỏi gợi ý.
- Lịch sử hỏi đáp lưu theo bản ghi. Câu trả lời có mốc thời gian bấm để tua.
- LLM là API cloud có stream, ngữ cảnh từ 128 nghìn token. Mỗi câu hỏi gửi cả transcript, không dùng map-reduce.
- Hỏi đáp chạy trong FastAPI. Bỏ hàng `io` và `worker-io`.
- Văn bản còn hai lớp: `text_raw` và `text_edited`.
- Trang sau đăng nhập là khung ba vùng, tải file là hộp thoại.

Nguồn đối chiếu: `docs/README.md`, kiến trúc mục 2.7 và 6, API mục 10, `docs/FLOWS.md` mục 9.

## Cần nhóm chốt trước khi sửa

- Tên đề tài đã đăng ký có "Tóm tắt và Trích xuất Biên bản". Đặc tả giữ nguyên tên, và giải thích nội dung biên bản được lấy qua hỏi đáp. Nên hỏi giảng viên hướng dẫn xem cách hiểu này có được chấp nhận không.
- File kế hoạch 7 tuần ghi "module tích hợp LLM tạo biên bản theo mẫu họp/bài giảng" ở tuần 6. Việc này cần đổi thành module hỏi đáp.

## Danh sách mục cần sửa

| Mục | Việc cần sửa |
|---|---|
| Đầu tài liệu, mục lục, danh mục bảng và hình | Cập nhật tên mục và tên bảng, hình sau khi sửa. Tên đề tài giữ theo quyết định ở trên |
| 1.1.1, 1.1.2 | Đoạn nói về biên bản hậu kỳ và phần chữ thô: đổi giải pháp sang hỏi đáp |
| 1.1.3 | Giải pháp đề xuất: thay biên bản bằng trợ lý hỏi đáp |
| 1.2.1 | Vai trò người dùng: đổi nhu cầu lập biên bản thành hỏi về nội dung và việc cần làm |
| 1.2.2 | Viết lại Quy trình 4 "Hậu kỳ bằng mô hình ngôn ngữ lớn và kiến trúc 3 lớp văn bản" thành quy trình hỏi đáp, còn hai lớp văn bản |
| 1.2.3 | Quy tắc xóa dữ liệu: thêm lịch sử hỏi đáp |
| 1.3.1, 1.3.2 | Đổi mục tiêu "Trích xuất biên bản thông minh" thành hỏi đáp trên transcript |
| 1.4.1 | Đối tượng nghiên cứu: bỏ phần xử lý văn bản theo mẫu, đổi sang hỏi đáp trên văn bản dài |
| 1.4.2 | Phạm vi: bỏ 2 mẫu biên bản và 3 lớp văn bản, thêm hỏi đáp |
| 1.4.3 | Ngoài phạm vi: thêm chuẩn hóa văn bản, biên bản theo mẫu, hỏi trên nhiều bản ghi |
| 2.1.1 | Câu nói thuật ngữ quyết định giá trị biên bản: đổi sang chất lượng câu trả lời |
| 2.2.1 | Bảng 2.2: đổi "tạo biên bản cuộc họp bằng LLM" thành hỏi đáp |
| 2.2.2 | Bỏ tác nhân Worker IO. Server LLM là API cloud, không còn trả JSON theo schema |
| 2.2.3 | Bảng 2.3: UC15 thành hỏi về nội dung bản ghi, UC16 thành xem và xóa lịch sử hỏi đáp |
| 2.2.5 | Viết lại bố cục trang job theo khung ba vùng và hộp thoại tải file |
| 2.3.5 | Viết lại theo ngữ cảnh dài của hỏi đáp: gửi cả transcript, báo lỗi khi vượt, chi phí token |
| 3.1.1 | Bỏ `worker-io`, thêm luồng FastAPI gọi API LLM |
| 3.1.2 | Bỏ hàng `io` và tác vụ `run_llm` |
| 3.1.3 | Thêm SSE của hỏi đáp nếu mục này liệt kê từng luồng SSE |
| 3.1.4 | Sửa phần liệt kê dữ liệu trong PostgreSQL có nhắc tới LLM |
| 3.1.6 | Bảng công nghệ: bỏ hàng `io` và dòng "Chuẩn hóa văn bản, tạo biên bản" |
| 3.4.1 | Giữ lý thuyết LLM, sửa câu nói nhiệm vụ của hệ thống |
| 3.4.2 | Bỏ chế độ JSON, thay bằng prompt hỏi đáp: chỉ dùng transcript, không bịa, ghi mốc thời gian |
| 3.4.3 | Viết lại toàn mục thành hai lớp chữ, ghi rõ không dùng LLM để chuẩn hóa và lý do |
| 3.4.4 | Thay map-reduce bằng cách dựng ngữ cảnh cho hỏi đáp. Xóa Hình 3.4 và Bảng 3.4. Đánh số lại hình và bảng phía sau |
| 3.4.5 | Sửa biện pháp chống ảo giác theo hỏi đáp: trả lời "không có thông tin", kèm mốc kiểm chứng |
| 3.4.6 | Đổi từ worker sang FastAPI. Ghi rõ chọn API cloud và yêu cầu ngữ cảnh, stream |
| 3.5.1 | Bảng 3.5: từ bảy dịch vụ còn sáu, bỏ `worker-io` |
| 3.5.2 | Từ 15 bảng còn 14: bỏ `llm_runs`, `llm_map_shards`, thêm `chat_messages`. Bỏ cột `text_cleaned` |
| 3.6 | Sửa kết luận chương |
| Tài liệu tham khảo | Rà lại [13] và các nguồn về map-reduce, bỏ nguồn không còn được trích |

Các mục trên được rà bằng từ khóa, nên khi sửa cần đọc lại cả mục. Code đã theo đặc tả 1.6, migration là `0003_chat`.
