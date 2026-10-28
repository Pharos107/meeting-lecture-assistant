# Ý tưởng, phạm vi, và tiêu chí nghiệm thu

**Dự án:** Hệ thống trợ lý chuyển đổi, tóm tắt và trích xuất biên bản cuộc họp / bài giảng tiếng Việt  
**Phiên bản:** 1.4  
**Ngày:** 2026-10-28  
**Vai trò của file này:** Mô tả bài toán, phạm vi làm, và cách biết hệ thống đạt yêu cầu. Cách làm nằm ở [kiến trúc](ARCHITECTURE_SPEC.md) và [API](API_AND_DATA.md).

## 1. Bài toán

Buổi học và cuộc họp kéo dài từ vài chục phút đến vài giờ. Ghi chép tay dễ mất ý, mất mốc thời gian, và tốn thêm một lượt tổng hợp việc cần làm.

Hệ thống nhận tiếng Việt từ file hoặc từ phiên nghe trực tiếp, ra văn bản có mốc thời gian và nhãn người nói, rồi tạo biên bản khi người dùng yêu cầu.

Ba phần việc đi cùng nhau:

- Nhận dạng tiếng nói, gắn thời gian tới từng từ ở bản chuẩn.
- Gắn nhãn người nói trên cùng timeline, và điền tên thật khi giọng khớp hồ sơ đã ghi.
- Hậu kỳ bằng LLM theo lệnh của người dùng: chuẩn hóa câu, và biên bản theo mẫu cuộc họp hoặc mẫu bài giảng.

## 2. Phạm vi

### Nằm trong bản triển khai

- Tài khoản: đăng ký, đăng nhập, làm mới phiên, đăng xuất.
- PT1: chọn audio hoặc video, nén ở trình duyệt khi làm được, nhận dạng, hiện chữ dần, sửa, xuất file.
- PT2 theo pha kép: bản nháp trong lúc nghe, rồi bản chuẩn quét lại cả file khi ngắt.
- Diarization trên file đã thu, sau bước nhận dạng, kèm hồ sơ giọng của chính tài khoản.
- Trang xem job hai vùng, đánh dấu đoạn chữ, và tạo việc cần làm từ câu đang chọn.
- Hai mẫu biên bản: cuộc họp doanh nghiệp, và ghi chú bài giảng.
- LLM qua giao thức tương thích OpenAI. Tên model cấu hình lúc triển khai.
- Xuất Markdown, DOCX, PDF, SRT, VTT.
- Xóa job và file âm thanh theo tài khoản chủ sở hữu.

### Nằm ngoài bản này

- Xác minh email, đăng nhập mạng xã hội, và phân quyền quản trị.
- Lưu video gốc trên server. Sau khi xử lý, máy chủ chỉ giữ Opus mono 16 kHz.
- Sửa từng từ bên trong một câu đã được người dùng hoặc LLM viết lại. Khi câu đã đổi, bấm câu sẽ tua theo mốc của cả câu.
- Tự gọi LLM khi nhận dạng xong.
- Chạy Whisper và pyannote cùng lúc.
- Cam kết một tỉ lệ phần trăm độ chính xác trước khi đo. Bản chuẩn của pha 2 được đo, không ghi sẵn một ngưỡng như 95%.
- Nhận ra người nói chưa từng ghi hồ sơ giọng trong tài khoản này.

PT2 dùng hộp thoại chia sẻ màn hình của Chromium và ô chia sẻ âm thanh. Micro dùng được trên các trình duyệt có `getUserMedia`. Thu âm thanh toàn hệ điều hành ngoài hộp thoại đó nằm ngoài phạm vi.

### Thứ tự triển khai

PT1 trọn vẹn là phần lõi của bản demo: tải file, chữ hiện dần, sửa, biên bản, xuất file. PT2 và hồ sơ giọng làm sau khi PT1 chạy hết đường trên máy mục tiêu. Hiện trạng từng phần nằm ở [phân tích luồng](FLOWS.md#13-khoảng-trống-giữa-đặc-tả-và-code).

## 3. Hai phương thức

| Tiêu chí | PT1, tải file | PT2, nghe trực tiếp |
|---|---|---|
| Đầu vào | File audio hoặc video trên máy người dùng | Micro, hoặc tab/cửa sổ được chia sẻ kèm âm thanh |
| Model chữ | `large-v3-turbo`, int8, beam 5 | Nháp: `small`, int8, beam 1. Khi dừng: cùng bản chuẩn như PT1 |
| Cách hiện chữ | SSE từng chunk 20–30 giây, frontend canh tốc độ gõ | WebSocket, câu nháp đóng khi có khoảng lặng hoặc đủ 8 giây |
| Người nói | Sau khi bản chuẩn xong | Sau khi bản chuẩn của pass 2 xong |
| Sửa và xuất file | Khi job ở trạng thái `ready` | Khi pass 2 đã `ready`. Nếu pass 2 lỗi, bản nháp vẫn xem và xuất được |
| Việc GPU đang bận | Job vào hàng đợi | Từ chối mở phiên mới với mã `gpu_busy` |

Độ chính xác của hai phương thức được đo bằng cùng một cách ở mục 6. PT2 không chọn một trong hai cực tốc độ hoặc độ chính xác. Pha 1 dùng model `small` để có chữ nháp trong lúc buổi đang diễn ra. Pha 2 bắt đầu khi người dùng dừng hoặc khi mất kết nối quá 30 giây: `large-v3-turbo` nhận dạng lại cả file đã thu, rồi pyannote gán người nói. Giao diện chuyển sang pha 2 khi pass đó có câu. Pass 1 vẫn lưu để đối chiếu. PT1 chỉ chạy pha chuẩn, vì file đã có đủ trước khi nhận dạng.

## 4. Tính năng người dùng thấy

1. Đăng ký và đăng nhập bằng email và mật khẩu.
2. Tải file `.mp3`, `.wav`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.flac`, `.mp4`, `.mkv`, `.webm`, `.mov`.
3. Nhập danh sách thuật ngữ, tối đa 800 ký tự, để đưa vào prompt của Whisper và của LLM.
4. Xem chữ bản chuẩn hiện dần, tua audio bằng cách bấm từ trên bản gốc. Nút gạt chuyển giữa bản gốc và bản đã chuẩn hóa mà không xóa kết quả chuẩn hóa.
5. Sửa câu, đổi tên hiển thị của `SPEAKER_00`, `SPEAKER_01`, và các nhãn khác.
6. Ghi hồ sơ giọng khoảng 30 giây. Những buổi sau, cụm giọng đủ giống hồ sơ được gán tên đã đặt, ví dụ "Lê Hải Đăng", thay cho nhãn `SPEAKER_00`. Đổi tên tay trên một buổi vẫn được.
7. Xem job trên hai vùng: bên trái là trình phát bám thời gian, bên phải là transcript. Bấm từ trên bản gốc để tua. Bôi đen một đoạn trong câu để đánh dấu, hoặc tạo một việc cần làm tại mốc của câu đó.
8. Bấm chuẩn hóa văn bản. Khi tạo biên bản, chọn một mẫu: biên bản cuộc họp doanh nghiệp, hoặc ghi chú bài giảng.
9. Tải Markdown, DOCX, PDF, SRT, hoặc VTT.
10. Mở phiên nghe trực tiếp, theo dõi bản nháp, bấm dừng để chạy bản chuẩn.
11. Xóa một job của chính mình.

## 5. Ràng buộc kỹ thuật đã biết

### File dài và đường truyền

File WAV hoặc video có thể nặng hàng trăm MB đến vài GB. Trình duyệt nén sang Opus 16 kHz, mono, 32 kb/s trước khi tải lên. Hai giờ âm thanh ở mức đó xấp xỉ 28 MB. Mức giảm so với file gốc phụ thuộc bitrate gốc, nên tài liệu không ghi một tỉ lệ phần trăm cố định.

Nếu FFmpeg.wasm không chạy, người dùng vẫn tải file gốc lên, tối đa 500 MB. Server luôn chuẩn hóa lại bằng FFmpeg của worker.

Trần thời lượng của một job hoặc một phiên nghe là 3 giờ.

### Bộ nhớ GPU

Máy demo có NVIDIA dưới 6GB. `large-v3-turbo` vẫn dùng encoder cỡ large và chỉ rút ngắn decoder, nên VRAM ở `int8` nằm gần nhóm model large. Benchmark int8 của faster-whisper cho model large ở beam 5 là khoảng 3 GB khi không batch. Vì vậy worker nạp một model, xong thì giải phóng, rồi mới nạp model sau. Không dùng batched inference.

`pyannote.audio` 4.0.3 với pipeline 3.1 đã được đo tới khoảng 9.5 GB ở bước tái dựng kết quả. Bản demo khóa dòng 3.x, mục tiêu kiểm thử là 3.3.2, nơi cùng pipeline được đo quanh 1.6 GB. Chi tiết phiên bản nằm ở [tài liệu môi trường](TECH_STACK_AND_ENVIRONMENT.md).

### Chữ chạy trên màn hình

Server gửi một cụm từ sau mỗi chunk. Frontend giữ một nhịp cố định cho cụm đó: thời gian xử lý dự kiến chia cho số từ của chính cụm đó, rồi kẹp trong khoảng 40–180 ms mỗi từ. Công thức và mã nằm ở kiến trúc.

### Hội thoại dài với LLM

Một buổi vài giờ tạo ra bản chữ dài. Hậu kỳ tóm tắt cắt theo từng lát khoảng 20 phút, tóm tắt từng lát, rồi hợp các lát thành một biên bản. Đầu ra là JSON có schema cố định, nên đổi model không đổi phần tích hợp.

### Người nói và câu nói chồng nhau

Mỗi từ nhận một nhãn: người có đoạn nói chồng nhiều nhất lên từ đó, khi phần chồng đạt ít nhất nửa độ dài từ. Từ không đủ độ chồng để trống. Hệ thống không tách hai lời nói trùng thời điểm thành hai dòng chữ.

Sau khi có các cụm, worker so vector giọng của từng cụm với hồ sơ đã ghi trong tài khoản. Điểm giống từ ngưỡng cấu hình thì tên hồ sơ được điền vào nhãn. Người chưa có hồ sơ vẫn là `SPEAKER_00` cho đến khi người dùng đổi tên trên buổi đó.

### Chữ bịa của Whisper

Ở đoạn ồn hoặc lặng, Whisper tiếng Việt hay sinh câu không có trong audio, thường là câu cuối video kiểu "Hãy đăng ký kênh…". Bản nháp PT2 dễ gặp hơn vì đoạn audio ngắn. Cách lọc nằm ở [kiến trúc mục 2.4](ARCHITECTURE_SPEC.md#24-nhận-dạng-bản-chuẩn). Bộ đối chiếu nên có ít nhất một đoạn nhiều khoảng lặng để đo hiện tượng này.

### Prompt thuật ngữ

`initial_prompt` của Whisper là ngữ cảnh ngắn, có trần ký tự ở hệ thống này là 800. Nó làm mô hình nghiêng về cách viết đã gợi ý. Nó không bảo đảm tên riêng được nhận đúng. Phần đo độ chính xác vì thế có một danh sách thuật ngữ riêng.

## 6. Tiêu chí nghiệm thu

### Bắt buộc với sản phẩm

- Người dùng A không đọc, không sửa, không nghe, và không xóa job của người dùng B.
- Một file tiếng Việt dài 60 phút, nằm dưới trần dung lượng, chạy hết trên GPU mục tiêu tới trạng thái `ready` mà worker không bị hệ điều hành giết vì hết VRAM.
- Bản `ready` có câu, mốc thời gian, và từ. Bấm một từ khi câu đang hiện đúng `text_raw` thì tua tới khoảng của từ đó.
- Diarization chạy sau Whisper. Nếu GPU từ chối pyannote, worker chạy pyannote trên CPU rồi vẫn về `ready`. Nếu cả CPU lỗi, job vẫn `ready`, mọi nhãn người nói để trống, và có cảnh báo `diarization_failed`.
- Tải lại trang giữa chừng một job PT1 thì chữ đã xong vẫn còn, và SSE tiếp tục từ số thứ tự sự kiện cuối.
- Phiên PT2 hiện câu nháp trong lúc thu. Sau khi dừng, pass 2 thay thế phần hiển thị khi nó hoàn tất, gồm chữ, ngắt câu, và nhãn người nói.
- Một hồ sơ giọng đã ghi được gán vào đúng cụm trong một file ngắn có cùng người nói. Alias người dùng đã sửa tay không bị lần chạy lại diarization ghi đè.
- Bôi đen một đoạn, đánh dấu, tải lại trang, dấu còn. Tạo việc từ câu đó còn sau khi tải lại, và tua tới mốc của câu.
- Mẫu cuộc họp và mẫu bài giảng trả hai dạng JSON khác nhau. JSON sai dạng bị từ chối sau đúng một lần thử lại.
- Chuẩn hóa và biên bản chỉ chạy khi người dùng bấm, qua endpoint tương thích OpenAI.
- Xóa job xóa luôn file Opus và các bản chữ.

### Đo rồi mới ghi vào báo cáo

Các con số dưới đây là việc phải đo, không phải mốc đã đạt.

- CER của pass 2 trên bộ đối chiếu do nhóm thu: ít nhất 3 đoạn tiếng Việt, tổng thời lượng ít nhất 30 phút, có transcript người làm. Báo cáo CER toàn bộ và CER trên danh sách tên riêng, thuật ngữ. Chạy cùng bộ này với `large-v3-turbo` và PhoWhisper đã chuyển sang CTranslate2 `int8`, kèm thời gian xử lý, để chọn model bản chuẩn.
- Với diarization, nếu có file RTTM đối chiếu thì báo cáo DER. Nếu chưa có, nghe lại 10 phút được rút ngẫu nhiên và ghi số chỗ gán nhầm.
- Với PT2, đo thời gian từ lúc hết một câu nói đến sự kiện nháp ổn định, trên câu không dài quá 8 giây. Mục tiêu thiết kế là trong 3 giây khi GPU đang dành cho phiên đó. Báo cáo số đo được, kể cả lần trượt mục tiêu.

Bộ đối chiếu và bảng số đo để trong thư mục báo cáo khi nhóm chạy thí nghiệm. Chúng không nằm trong repo mã nguồn nếu audio gốc là dữ liệu riêng của buổi họp.
