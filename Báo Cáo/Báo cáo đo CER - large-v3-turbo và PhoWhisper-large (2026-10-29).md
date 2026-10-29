# Báo cáo đo độ chính xác nhận dạng: `large-v3-turbo` và `PhoWhisper-large`

**Ngày đo:** 2026-10-29
**Mục đích:** Đo CER của pass 2 theo `docs/IDEA_AND_CHALLENGES.md` mục "Đo rồi mới ghi vào báo cáo", để chọn model bản chuẩn (việc còn mở "Model bản chuẩn" trong `docs/README.md`).
**Phạm vi:** 3 bản tin VTV24, tổng 37 phút 8 giây, 8.508 từ trong bản gỡ băng. Mỗi model chạy một lần trên mỗi bài, qua đúng pipeline PT1 của ứng dụng (API → FFmpeg → Silero VAD → Whisper → pyannote 3.1).

---

## 1. Tóm tắt

| Chỉ số (gộp 3 bài)                                    | `large-v3-turbo`                      | `PhoWhisper-large`        |
| --------------------------------------------------------- | --------------------------------------- | --------------------------- |
| CER, đầu ra thô của pipeline                          | **4,72%**                         | 20,67%                      |
| WER, đầu ra thô của pipeline                          | **6,59%**                         | 22,30%                      |
| CER sau khi bỏ câu bịa (cùng bộ lọc cho cả hai)    | 4,66%                                   | **3,77%**             |
| WER sau khi bỏ câu bịa                                 | 6,43%                                   | **6,09%**             |
| CER trên thuật ngữ, tên riêng (189 lần xuất hiện) | **9,82%**                         | 15,87%                      |
| Thuật ngữ khớp đúng nguyên cụm                     | **145/189**                       | 124/189                     |
| Tỉ lệ từ gán đúng người nói                      | 83,71%                                  | 82,88%                      |
| Thời gian xử lý / thời lượng âm thanh              | **0,123**                         | 0,286                       |
| Tốc độ riêng bước nhận dạng                       | **17,7–24,1× thời gian thực** | 4,2–4,9× thời gian thực |
| Đỉnh VRAM toàn card                                    | **3,05 GB**                       | 3,70 GB                     |

Kết luận ngắn:

1. **Với pipeline hiện tại, `large-v3-turbo` là lựa chọn dùng được ngay.** PhoWhisper sinh 49 câu bịa ở cuối các chunk, chiếm 1.380 từ trên 3 bài. Bộ lọc chữ bịa hiện có không bắt được các câu này, nên CER thô của PhoWhisper cao gấp 4 lần turbo.
2. **Khi đã bỏ câu bịa, PhoWhisper chính xác hơn trên tiếng Việt thuần.** Câu bịa của nó rất dễ nhận ra: 12–91 từ dồn vào dưới 0,7 giây. Bài y tế "Cơ sở 2" có CER 1,76%, so với 10,89% của turbo. PhoWhisper cũng viết đúng các thuật ngữ y khoa và pháp lý mà turbo nghe sai.
3. **PhoWhisper yếu rõ ở tên nước ngoài.** Nó phiên âm theo kiểu tiếng Việt: "tê hê ran" thay cho Tehran, "lu la đờ xin va" thay cho Lula da Silva, "rôn" thay cho drone. CER thuật ngữ của bài quốc tế là 29,89%, so với 8,32% của turbo.
4. **Đầu ra của PhoWhisper khó dùng hơn cho giao diện.** Toàn chữ thường, gần như không có dấu câu, số viết bằng chữ, và câu dài 18–24 giây (turbo chỉ 4–6 giây). Bước nhận dạng chậm hơn khoảng 4 lần.
5. **Turbo có hai lỗi nghiêm trọng cần sửa, bất kể chọn model nào.** Ở bài "Cơ sở 2", turbo bịa câu "Hãy subscribe cho kênh Ghiền Mì Gõ…" rồi bỏ trống 23 giây. Nó cũng bỏ qua hai đoạn phỏng vấn hiện trường có nhiễu. Riêng việc này chiếm phần lớn trong 197 từ bị mất của bài đó.

**Đề xuất:** giữ `large-v3-turbo` làm mặc định, chưa khóa model. Trước hết sửa bộ lọc câu bịa (mục 7). Sau đó đo lại cả hai model trên bộ đối chiếu là **ghi âm cuộc họp và bài giảng do nhóm tự thu**, như đặc tả yêu cầu, rồi mới quyết định. Bộ này hiện là tin truyền hình đọc sẵn (xem mục 8). Chi tiết ở mục 9.

---

## 2. Bộ dữ liệu

| Mã          | Bài                                                                  | Thời lượng | Từ trong bản gỡ băng | Người nói | Đặc điểm                                                                        |
| ------------ | --------------------------------------------------------------------- | ------------- | ------------------------ | ------------ | ----------------------------------------------------------------------------------- |
| `phapluat` | Nâng cao ý thức, trách nhiệm của nhân dân trước pháp luật | 7:54          | 1.922                    | 6            | Tọa đàm trường quay, 1 khách chiếm 62% số từ, 3 phỏng vấn hiện trường |
| `coso2`    | Cơ sở 2 giảm tải bệnh viện tuyến Trung ương (cụm tin)       | 8:29          | 1.904                    | 10           | Tin đọc, phóng sự y tế, phỏng vấn hiện trường có nhiễu                  |
| `thegioi`  | Thế giới toàn cảnh ngày 26/10                                    | 20:46         | 4.682                    | 12           | Tin quốc tế, nhiều tên riêng nước ngoài, 5 vai lồng tiếng                 |

Bản gỡ băng lấy từ các file `Phụ đề _….md` trong `data/phóng sự 7p/`. Script chỉ đọc phần lời, bắt đầu từ "### PHẦN 1", bỏ tiêu đề, danh sách nhân vật và các dòng chuyển cảnh `*(...)*`.

---

## 3. Cấu hình chạy

| Mục                         | Giá trị                                                                                                                                                        |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Máy                         | RTX 4050 Laptop 6 GB, driver 610.88, Docker trên WSL2. Windows giữ sẵn 1,2–1,4 GB VRAM                                                                       |
| Image                        | `stt-backend` nhánh `fix/gpu-image-bookworm`: torch 2.5.1 cu121, ctranslate2 4.5.0, faster-whisper 1.1.1, pyannote.audio 3.3.2                              |
| Model A                      | `large-v3-turbo` (faster-whisper tải `mobiuslabsgmbh/faster-whisper-large-v3-turbo`)                                                                        |
| Model B                      | `vinai/PhoWhisper-large`, chuyển bằng `ct2-transformers-converter` (transformers 4.46.3), lưu float16                                                     |
| Kiểu tính                  | `int8` cho cả hai, theo `WHISPER_COMPUTE_TYPE`                                                                                                              |
| Tham số giải mã           | Giữ nguyên như trong `stt_engine.py`: `beam_size=5`, `language="vi"`, `temperature=0`, `condition_on_previous_text=False`, `word_timestamps=True` |
| Thuật ngữ (`vocabulary`) | Không nhập                                                                                                                                                     |
| Số người nói             | Không nhập, pyannote tự đoán                                                                                                                                |
| Đổi model                  | Đặt `WHISPER_MODEL` cho `worker-gpu`. Không sửa code                                                                                                     |

---

## 4. Cách chấm

1. **Chuẩn hóa chữ, áp như nhau cho cả hai phía:** NFC, chữ thường, bỏ dấu câu, `%` đọc thành "phần trăm", số đọc thành chữ ("2023" thành "hai nghìn không trăm hai mươi ba"), quy kiểu bỏ dấu cũ về kiểu mới ("hoá" thành "hóa", giữ "quý"). Ghép lại "150 .000" thành "150.000" (xem lỗi pipeline ở mục 7.3).
2. **WER** là số từ thay + mất + chèn, chia cho số từ của bản gỡ băng. **CER** tính tương tự trên ký tự, có tính khoảng trắng.
3. **Bản "đã lọc"** bỏ câu bịa bằng cùng một quy tắc cho cả hai model: câu từ 4 từ trở lên mà nói nhanh hơn 12 từ/giây, hoặc câu chứa cụm "subscribe", "đăng ký kênh", "bỏ lỡ những video". Câu thật nhanh nhất trong 6 lần chạy là 8,5 từ/giây, nên ngưỡng 12 không cắt nhầm câu thật nào.
4. **Thuật ngữ:** mỗi bài có một danh sách tên riêng và thuật ngữ, tổng 189 lần xuất hiện. Với mỗi lần xuất hiện, script lấy đoạn chữ máy đã căn vào vị trí đó, rồi tính CER và xem có khớp nguyên cụm không.
5. **Người nói:** căn từng từ, rồi ghép mỗi nhãn của pyannote với một người trong bản gỡ băng bằng thuật toán Hungarian. **Độ chính xác** là tỉ lệ từ có nhãn khớp. **Độ thuần cụm** là tỉ lệ từ trong mỗi cụm thuộc về người chiếm đa số trong cụm đó.
6. **Từ đệm:** có thêm một cột WER bỏ "thì, ấy, ạ, vâng, dạ, à, ừ, ờ, ơ, ừm, cái". Lý do là bản gỡ băng giữ từ đệm không đều.

---

## 5. Kết quả theo bài

### 5.1. Độ chính xác chữ

| Bài     | Model      | WER thô        | CER thô        | WER đã lọc   | CER đã lọc   | WER đã lọc, bỏ từ đệm | Thay / Mất / Chèn (đã lọc) |
| -------- | ---------- | --------------- | --------------- | --------------- | --------------- | ---------------------------- | ------------------------------- |
| phapluat | turbo      | 8,32%           | 6,39%           | **7,54%** | **5,52%** | 6,34%                        | 57 / 69 / 19                    |
| phapluat | PhoWhisper | 29,50%          | 29,66%          | 7,75%           | 5,85%           | **6,18%**              | 37 / 52 / 60                    |
| coso2    | turbo      | 12,03%          | 10,32%          | 12,08%          | 10,89%          | 11,41%                       | 33 / **197** / 0          |
| coso2    | PhoWhisper | 24,05%          | 24,34%          | **2,47%** | **1,76%** | **2,36%**              | 21 / 13 / 13                    |
| thegioi  | turbo      | **3,67%** | **1,87%** | **3,67%** | **1,87%** | **3,54%**              | 141 / 20 / 11                   |
| thegioi  | PhoWhisper | 18,62%          | 15,73%          | 6,88%           | 3,75%           | 6,84%                        | 152 / 36 / 134                  |

Đọc bảng:

- Ở bài `phapluat`, hai model gần như ngang nhau sau khi lọc.
- Ở bài `coso2`, turbo thua chủ yếu do mất chữ, không phải do nghe sai: 197 từ mất, 0 từ chèn (xem mục 6.1).
- Ở bài `thegioi`, PhoWhisper thua vì tên nước ngoài: mỗi tên bị phiên âm thành nhiều âm tiết, nên vừa sai vừa chèn thêm 134 từ.

### 5.2. Thuật ngữ và tên riêng

| Bài     | Model      | CER thuật ngữ | Khớp nguyên cụm |
| -------- | ---------- | --------------- | ------------------ |
| phapluat | turbo      | 10,55%          | 18/30              |
| phapluat | PhoWhisper | **4,77%** | **25/30**    |
| coso2    | turbo      | 11,73%          | 36/44              |
| coso2    | PhoWhisper | **1,35%** | **41/44**    |
| thegioi  | turbo      | **8,32%** | **91/115**   |
| thegioi  | PhoWhisper | 29,89%          | 58/115             |

Những thuật ngữ mà hai model cho kết quả khác nhau:

| Thuật ngữ                    | turbo | PhoWhisper | Ghi chú                                         |
| ------------------------------ | ----- | ---------- | ------------------------------------------------ |
| phòng cháy chữa cháy       | 0/5   | 2/5        | turbo: "chứ cháy", "trái trựa", "chế cháy" |
| răn đe                       | 0/2   | 2/2        | turbo: "gian đe"                                |
| kỷ cương                    | 2/4   | 4/4        |                                                  |
| ngân sách Nhà nước        | 0/1   | 1/1        | turbo: "ngân sanh nước"                       |
| nhồi máu cơ tim             | 0/2   | 2/2        | turbo: "nhỏ máu cơ tim"                       |
| thuế tiêu thụ đặc biệt   | 0/1   | 1/1        | turbo: "thuế xuất, thuế tiêu tụ"            |
| Bạch Mai                      | 2/4   | 4/4        | turbo: "Bệnh Mai"                               |
| Bệnh viện Nhi Trung ương   | 0/1   | 1/1        |                                                  |
| EVN                            | 2/2   | 0/2        |                                                  |
| Tehran                         | 2/2   | 0/2        | PhoWhisper: "tê hê ran"                        |
| Hormuz                         | 3/4   | 0/4        |                                                  |
| Lula, Bolsonaro                | 4/4   | 0/4        | PhoWhisper: "lu la đờ xin va"                  |
| Hamas, Palestine, Donald Trump | 4/4   | 0/4        |                                                  |
| drone                          | 5/5   | 0/5        | PhoWhisper: "rôn"                               |
| LNG                            | 13/14 | 8/14       |                                                  |
| Washi                          | 8/8   | 4/8        |                                                  |
| Tỷ Quy                        | 0/2   | 2/2        |                                                  |

Tóm lại, PhoWhisper mạnh ở từ Hán Việt và thuật ngữ chuyên ngành tiếng Việt, còn turbo mạnh ở tên riêng viết bằng chữ Latin.

### 5.3. Người nói

| Bài     | Model      | Người (gỡ băng / máy) | Độ chính xác | Độ thuần cụm | Từ không nhãn |
| -------- | ---------- | -------------------------- | ---------------- | ---------------- | ---------------- |
| phapluat | turbo      | 6 / 6                      | 96,82%           | 99,6%            | 52               |
| phapluat | PhoWhisper | 6 / 6                      | 96,10%           | 99,6%            | 66               |
| coso2    | turbo      | 10 / 9                     | 82,37%           | 100,0%           | 51               |
| coso2    | PhoWhisper | 10 / 10                    | 82,60%           | 98,1%            | 84               |
| thegioi  | turbo      | 12 / 12                    | 79,00%           | 96,4%            | 56               |
| thegioi  | PhoWhisper | 12 / 12                    | 77,68%           | 96,3%            | 106              |

Hai model dùng chung pyannote 3.1, nên chênh lệch ở đây chỉ đến từ mốc thời gian của từ. PhoWhisper có nhiều từ không nhãn hơn (66–106 so với 51–56), tức là mốc thời gian từng từ của nó kém chính xác hơn.

Độ chính xác chỉ khoảng 80% ở hai bài tin, nhưng độ thuần cụm đạt 96–100%. Như vậy diarization hầu như không trộn hai giọng vào một cụm. Lỗi đến từ hai nguồn:

- **Một người trong bản gỡ băng bị tách thành nhiều cụm.** "BTV Nữ 1" của bài `thegioi` thành ba cụm với 884, 627 và 125 từ. "BTV Nữ 1" của bài `coso2` thành hai cụm với 256 và 250 từ. Nhiều khả năng bản gỡ băng gán cả lời dẫn lẫn lời phóng sự cho cùng một vai, trong khi đó là các giọng khác nhau, hoặc cùng giọng nhưng thu ở hai môi trường khác nhau.
- **Nhiều vai lồng tiếng bị gộp vào một cụm.** "Nông dân", "Đại diện huyện Tỷ Quy" và "Đại diện doanh nghiệp taxi bay" cùng vào SPEAKER_04. "Chuyên gia năng lượng Mỹ" và "Đại diện mua hàng LNG" cùng vào SPEAKER_02. Bản gỡ băng gán theo vai, còn pyannote gom theo giọng, và các vai này nhiều khả năng do cùng một người lồng tiếng.

Vì vậy con số khoảng 80% là cận dưới. Muốn đo đúng, cần file RTTM gán nhãn theo giọng như đặc tả yêu cầu, hoặc nghe lại 10 phút để đếm chỗ gán nhầm.

### 5.4. Thời gian và VRAM

| Bài     | Model      | Tổng   | Chuẩn hóa | Nhận dạng | Diarization | Tổng / thời lượng | Đỉnh VRAM toàn card |
| -------- | ---------- | ------- | ----------- | ----------- | ----------- | --------------------- | ---------------------- |
| phapluat | turbo      | 70,8 s  | 8,1 s       | 26,8 s      | 34,9 s      | 0,149                 | 2,94 GB                |
| phapluat | PhoWhisper | 159,8 s | 9,8 s       | 114,1 s     | 34,9 s      | 0,337                 | 3,70 GB                |
| coso2    | turbo      | 55,8 s  | 7,8 s       | 21,1 s      | 25,9 s      | 0,110                 | 2,96 GB                |
| coso2    | PhoWhisper | 149,9 s | 7,8 s       | 116,1 s     | 25,0 s      | 0,294                 | 3,70 GB                |
| thegioi  | turbo      | 146,5 s | 16,8 s      | 64,9 s      | 63,8 s      | 0,118                 | 3,05 GB                |
| thegioi  | PhoWhisper | 327,8 s | 16,9 s      | 254,9 s     | 55,0 s      | 0,263                 | 3,70 GB                |

Thời gian mỗi bước là khoảng giữa hai lần đổi trạng thái của job, đọc mỗi giây qua API. Thời gian nạp model nằm trong bước nhận dạng.

Ngoại suy cho một bài 3 giờ (trần thời lượng của đặc tả): turbo khoảng 22 phút, PhoWhisper khoảng 52 phút. Cả hai đều dưới hạn 6 giờ của task GPU.

Riêng phần model chiếm khoảng 1,7 GB VRAM với turbo và 2,2–2,4 GB với PhoWhisper. Cả hai đều vừa ngân sách của card 4 GB trong D5, nhưng với PhoWhisper thì phần dư còn lại mỏng hơn.

### 5.5. Dạng chữ đầu ra

| Đặc điểm              | turbo                                      | PhoWhisper                                          |
| ------------------------- | ------------------------------------------ | --------------------------------------------------- |
| Chữ hoa                  | Có (1,7–2,9% số chữ cái)              | Không (0%)                                         |
| Dấu câu trên 100 từ   | 4,5–7,5                                   | 1,3–1,6, gần như chỉ có dấu chấm cuối chunk |
| Số                       | Viết bằng chữ số ("50 triệu", "2023") | Viết bằng chữ ("năm mươi triệu")             |
| Độ dài câu, trung vị | 4,0–5,7 s                                 | 18,1–24,3 s                                        |
| Câu dài nhất           | 13–15 s                                   | 29–30 s, bằng nguyên một chunk                  |
| Từ đệm "à", "ờ"      | Thường bỏ                               | Giữ lại                                           |

Câu của PhoWhisper dài bằng cả một chunk. Điều này kéo theo ba hệ quả:

- SSE chỉ đẩy chữ theo từng khối khoảng 25 giây.
- Mỗi khối chỉ mang một nhãn người nói, nên vấn đề #18 trong `docs/FLOWS.md` (câu chứa lời nhiều người) nặng hơn.
- Phải dựa vào bước chuẩn hóa LLM (`text_cleaned`) để có chữ hoa và dấu câu.

---

## 6. Phân tích lỗi

### 6.1. Turbo bỏ sót đoạn và bịa câu

Ở bài `coso2`, turbo viết "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn" ở giây 61,0–62,8. Sau đó không có chữ nào cho tới giây 86,0. Toàn bộ đoạn dẫn của biên tập viên ("Giảm tải cho các bệnh viện tuyến Trung ương, đưa dịch vụ y tế chất lượng cao…") bị mất. PhoWhisper nhận đủ đoạn này.

Turbo còn bỏ hai đoạn phỏng vấn hiện trường có tiếng ồn:

- giây 98,8–109,8: lời người nhà bệnh nhân;
- giây 144,4–153,5: lời nữ bệnh nhân.

Ở bài `phapluat`, turbo bịa "Hãy subscribe cho kênh La La School…" giữa câu "mức phạt trong lĩnh vực / về phòng cháy chữa cháy".

Bộ lọc hiện tại (`stt_engine.is_hallucination`) có cụm "hãy subscribe cho kênh", nhưng chỉ bỏ câu khi phần đuôi sau cụm không dài quá 25 ký tự. Đuôi "La La School Để không bỏ lỡ những video hấp dẫn" dài 48 ký tự, nên câu lọt qua.

### 6.2. PhoWhisper bịa câu ở cuối chunk

PhoWhisper bịa 13, 16 và 20 câu trên ba bài, tổng 1.380 từ, trong khi turbo chỉ có 2 câu. Các câu này có ba đặc điểm chung:

- Mốc thời gian dài 0,02–0,7 giây nhưng có 12–91 từ, tức từ 24 từ/giây trở lên.
- Nằm ngay sau một câu dài khoảng 25 giây, tức là ở cuối cửa sổ 30 giây của Whisper.
- Nội dung không liên quan đến bài, đôi khi lặp lại.

Ví dụ:

- `phapluat` 22,8 s (0,24 s): "những bức ảnh chụp từ đầu năm một nghìn chín trăm bảy chín trăm năm một nghìn chín năm bảy chín."
- `coso2` 109,0 s (0,36 s): "học trò tiếp theo trong tiếng nói việt nam tiếp theo đấu tranh tiếp theo đấu tranh việt nam trên toàn thế giới."
- `thegioi` 113,7 s (0,30 s): "hạn chế gây phân hóa bệnh tâm thần và tâm hồn trong cơ thể trẻ nhỏ…"

Dấu hiệu tốc độ nói bất thường bắt được tất cả các câu này mà không cắt nhầm câu thật nào.

### 6.3. Lỗi nghe sai thường gặp

- **turbo:** nhầm phụ âm đầu và âm cuối: ch/tr ("trung cư", "trựa cháy"), r/d/gi ("gian đe", "tháo rỡ"), s/x ("sử phạt", "thuế xuất"), "nhồi" thành "nhỏ", "thiếu" thành "chiều", "trầm" thành "chậm", "mạch vành" thành "bành bành".
- **PhoWhisper:** ít nhầm âm hơn. Lỗi chính là phiên âm tên nước ngoài ("pa lô" thay cho Paulo, "i sơ ren" thay cho Israel, "chi lê" thay cho Cheniere), viết "ý" thay cho "ấy", và "hiệu quả" thay cho "hậu quả".

---

## 7. Vấn đề trong code phát hiện khi đo

| #   | Mức        | Vấn đề                                                                                                                                                                                                                                 | Chỗ sửa                                                                                                                                                                                           |
| --- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 7.1 | Cao         | Bộ lọc câu bịa chỉ so khớp cụm cố định với đuôi tối đa 25 ký tự. Bỏ sót "Hãy subscribe cho kênh La La School / Ghiền Mì Gõ…", và không bắt được câu bịa của PhoWhisper                                  | `stt_engine.is_hallucination`. Thêm điều kiện tốc độ nói: từ 4 từ trở lên và quá 12 từ/giây. Thêm cụm "để không bỏ lỡ những video". Đây là #16 trong `docs/FLOWS.md` |
| 7.2 | Cao         | Turbo bỏ trống 23 giây ngay sau câu bịa. Câu bịa che mất phần còn lại của chunk                                                                                                                                               | Cần đo thêm. Hướng thử: khi đã bỏ một câu bịa, chạy lại riêng khoảng thời gian đó, hoặc giảm `no_speech_threshold` cho chunk đó                                            |
| 7.3 | Trung bình | Chữ hiển thị chèn khoảng trắng vào giữa số: "150 .000", "1 -11 -2026", "0 %". `stt_engine` cắt khoảng trắng đầu của từ (`word.word.strip()`), rồi `pipeline._write_chunk` ghép lại bằng `" ".join` (dòng 60) | Giữ thông tin "từ có khoảng trắng đầu hay không" khi ghép câu, còn chữ của từng từ vẫn lưu dạng đã cắt                                                                        |
| 7.4 | Thấp       | Từ không nhãn chiếm phần lớn lỗi người nói ở bài 2 người. Ở bài `phapluat`, 52 trong 59 từ gán sai là từ không nhãn                                                                                               | Hướng tối ưu ở kiến trúc mục 2.5 (#18): gán từ không nhãn cho lượt nói gần nhất nếu cách dưới 500 ms                                                                           |

---

## 8. Giới hạn của lần đo

- **Khác lĩnh vực.** Đặc tả yêu cầu bộ đối chiếu "do nhóm thu" từ cuộc họp hoặc bài giảng. Bộ này là tin truyền hình: đọc sẵn, thu bằng micro tốt, có lồng tiếng. Lời nói tự nhiên trong họp có nhiều từ đệm, nói chồng, ít tên nước ngoài. Đó là kiểu dữ liệu mà PhoWhisper nhiều khả năng có lợi thế, nên kết quả ở đây chưa đủ để kết luận cho sản phẩm.
- **Bản gỡ băng đã biên tập.** Có chỗ chèn "(sửa đổi)", có danh sách đánh số, có câu đã sửa văn phong. CER đo được vì vậy là cận trên. Phần chênh giữa hai model đáng tin hơn con số tuyệt đối.
- **Mỗi cấu hình chạy một lần.** `temperature=0` nên chữ ổn định, nhưng thời gian có thể dao động vài giây vì Windows cũng dùng GPU.
- **PhoWhisper chạy với tham số giải mã của turbo.** Chưa thử `hotwords`, `condition_on_previous_text=True` hay chunk ngắn hơn, là những thay đổi có thể giảm câu bịa.
- **Chưa thử nhập thuật ngữ.** Một lần thử riêng với turbo trên bài `phapluat` (ngoài bảng trên) cho thấy: nhập 8 thuật ngữ làm tỉ lệ nhận đúng thuật ngữ tăng từ 60% lên 90%. Nhưng turbo lại bỏ sót hai câu nói, nên WER tăng từ 8,32% lên 10,15%.

---

## 9. Đề xuất

1. **Giữ `large-v3-turbo` làm mặc định cho pass 2 lúc này, chưa khóa.** Lý do:
   - Đầu ra thô dùng được ngay: có chữ hoa và dấu câu, câu ngắn hợp với SSE và với việc gán người nói.
   - Nhanh gấp khoảng 2,3 lần tính cả job, và khoảng 4 lần riêng bước nhận dạng.
   - Không phụ thuộc vào bộ lọc câu bịa để có kết quả chấp nhận được.
2. **Sửa mục 7.1 và 7.3 trước khi đo tiếp.** Sửa 7.1 xong thì PhoWhisper mới dùng được trong pipeline, và turbo cũng không còn câu "subscribe".
3. **Đo vòng hai trên dữ liệu đúng lĩnh vực:** ít nhất 3 đoạn họp hoặc bài giảng do nhóm thu, tổng ít nhất 30 phút, có bản gỡ băng sát lời nói. Chạy turbo và PhoWhisper (đã có bộ lọc mới), mỗi model một lần không nhập thuật ngữ và một lần có nhập thuật ngữ. Chỉ chuyển sang PhoWhisper nếu nó vẫn thắng rõ về CER trên dữ liệu này, và nhóm chấp nhận được việc chậm hơn khoảng 4 lần ở bước nhận dạng cùng chữ thường không dấu câu.
4. **Có thể thử sau:** dùng PhoWhisper-medium (3,06 GB, nhanh hơn bản large) hoặc tham số `hotwords` của faster-whisper thay cho `initial_prompt`, để tránh việc model bỏ sót câu khi có danh sách thuật ngữ.

---

## 10. Chạy lại

Thư mục `do-cer-2026-10-29/` nằm cạnh báo cáo này:

| File             | Việc                                                                                                                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_job.py`   | Chạy trong container `backend`. Đăng ký tài khoản thử, tải file lên `POST /api/jobs`, theo dõi trạng thái, lưu transcript (`OUT`) và thời gian từng bước (`META`) |
| `run_all.sh`   | Đổi `WHISPER_MODEL` cho `worker-gpu`, chạy 3 bài × 2 model, ghi đỉnh VRAM bằng `nvidia-smi`                                                                                   |
| `score.py`     | Chuẩn hóa chữ, đổi số thành chữ, đọc bản gỡ băng, căn từ, tính khoảng cách chỉnh sửa                                                                                    |
| `evaluate.py`  | Tính WER, CER, thuật ngữ, người nói, câu bịa cho mọi lần chạy, ghi `results.json`                                                                                              |
| `results.json` | Toàn bộ số đo của báo cáo này                                                                                                                                                       |

Model PhoWhisper đã chuyển nằm trong volume `hf-cache` của Docker, tại `/cache/huggingface/phowhisper-large-ct2`. Lệnh chuyển:

```bash
ct2-transformers-converter --model vinai/PhoWhisper-large --output_dir /cache/huggingface/phowhisper-large-ct2 --copy_files tokenizer.json preprocessor_config.json --quantization float16
```

Transcript máy của 6 lần chạy không đặt vào thư mục này, vì chúng chứa nội dung của bản tin VTV24.

---

## 11. Cập nhật cùng ngày: chia chunk, nhiễu, và kết quả sau khi sửa

### 11.1. Chia chunk

- VAD phủ 90–96% thời lượng mỗi bài. Cả 4 đoạn mất chữ đều nằm trong chunk: VAD đã đưa vào, Whisper không ra chữ.
- Chunk trung vị 24–25 giây, 1–5 lần cắt cứng ở 30 giây mỗi bài. Phần chồng 1 giây được khử đúng, không có câu lặp ở chỗ nối.
- Lỗi trong vòng 1 giây quanh mép chunk cao hơn giữa chunk vài điểm (turbo 5–16% so với 4–12%).
- Hạ trần chunk xuống 15 giây làm tệ hơn ở 4/5 trường hợp thử, vì model thiếu ngữ cảnh và bịa nhiều hơn. Giữ trần 30 giây.

### 11.2. Nhiễu (bài `phapluat`, turbo, trước khi sửa)

| SNR | Nhiễu hồng | Tiếng người nói lẫn nhau |
|---|---|---|
| sạch | 8,3% WER | 8,3% WER |
| 20 dB | 9,1% | 12,7% |
| 10 dB | 9,8% | 16,4% |
| 5 dB | 13,8% | 41,4% |
| 0 dB | 24,9% | 89,9% |

Nhiễu tiếng người được ghép từ 4 luồng podcast Vietcetera lệch thời điểm. SNR tính trên vùng có tiếng. Với nhiễu đều, VAD vẫn bắt 98–99% tiếng nói đến 0 dB. Với tiếng người từ 5 dB trở xuống, VAD coi cả bài là tiếng nói, và diarization ra 8 người thay vì 6.

### 11.3. Sau khi sửa mục 7.1 và 7.3

Đã sửa trên nhánh `fix/hallucination-filter`: `hallucination_silence_threshold=2.0`, bỏ câu quá 12 từ/giây, bỏ câu ngắn mở đầu bằng lời mời đăng ký kênh, ghép mảnh word không có dấu cách đầu. Chạy lại qua pipeline với turbo:

| Bài | WER trước → sau | CER trước → sau | Câu bịa | Tiếng nói không ra chữ |
|---|---|---|---|---|
| phapluat | 8,32% → 7,54% | 6,39% → 5,52% | 1 → 0 | 2,2 → 2,2 s |
| coso2 | 12,03% → 6,78% | 10,32% → 5,44% | 1 → 0 | 35,1 → 14,5 s |
| thegioi | 3,67% → 3,67% | 1,87% → 1,87% | 0 → 0 | 5,9 → 5,9 s |
| babble 10 dB | 16,39% → 12,96% | 13,16% → 10,20% | 1 → 0 | 26,5 → 9,2 s |
| babble 5 dB | 41,36% → 30,44% | 34,09% → 25,09% | 6 → 0 | 93,1 → 73,6 s |
| hồng 5 dB | 13,79% → 13,79% | 9,54% → 9,54% | 0 → 0 | 2,3 → 2,3 s |
| hồng 0 dB | 24,87% → 21,80% | 18,54% → 15,64% | 1 → 0 | 6,4 → 2,2 s |

Gộp 3 bản tin, turbo sau khi sửa có **WER 5,24%, CER 3,46%**. Con số này tốt hơn cả PhoWhisper đã lọc câu bịa ở mục 1 (WER 6,09%, CER 3,77%), trong khi vẫn nhanh hơn khoảng 2,3 lần. Như vậy đề xuất giữ `large-v3-turbo` ở mục 9 càng có cơ sở. Việc đo trên ghi âm họp do nhóm thu vẫn cần làm trước khi khóa model.

Còn mở:
- Turbo vẫn bỏ khoảng 14,5 giây lời phỏng vấn hiện trường ở bài `coso2`. Nhận dạng riêng từng vùng VAD lấy lại được, nhưng chưa đưa vào pipeline (#19 trong `docs/FLOWS.md`).
- Nền có người nói vẫn là điểm yếu (#20).
