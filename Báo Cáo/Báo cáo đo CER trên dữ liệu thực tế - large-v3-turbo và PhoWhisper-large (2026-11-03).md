# Báo cáo đo độ chính xác trên dữ liệu thực tế: `large-v3-turbo` và `PhoWhisper-large`

**Ngày đo:** 2026-11-03
**Mục đích:** Đo vòng hai theo đề xuất mục 9.3 của báo cáo 2026-10-29: chạy lại hai model trên bài giảng và cuộc họp thật, thay cho tin truyền hình đọc sẵn, rồi mới chốt model bản chuẩn.
**Phạm vi:** 7 file trong `data/Data thực tế/`, tổng 108 phút 9 giây âm thanh. Chấm được 6 file (79 phút 49 giây, 14.177 từ gỡ băng). Mỗi model chạy một lần trên mỗi file, qua đúng pipeline PT1 của ứng dụng (API → FFmpeg → Silero VAD → Whisper → pyannote 3.1). Code là nhánh `fix/media-token-loop`, đã có bộ lọc câu bịa của `fix/hallucination-filter`.

---

## 1. Tóm tắt

| Chỉ số (gộp 6 file chấm được) | `large-v3-turbo` | `PhoWhisper-large` |
|---|---|---|
| WER | 36,01% | **34,68%** |
| CER | 28,06% | **24,97%** |
| Thay / Mất / Chèn (số từ) | **2.797** / 2.073 / **235** | 3.339 / **849** / 729 |
| Thuật ngữ khớp đúng nguyên cụm | **323/978** | 312/978 |
| Câu bịa còn lọt bộ lọc (cả 7 file) | 7 | **1** |
| Thời gian xử lý / thời lượng âm thanh (cả 7 file) | **0,106** | 0,222 |
| Tốc độ riêng bước nhận dạng | **21,8× thời gian thực** | 6,1× thời gian thực |
| Đỉnh VRAM toàn card | **2,65 GB** | 3,25 GB |

Kết luận ngắn:

1. **Dữ liệu thật khó hơn nhiều so với tin truyền hình.** Cùng model turbo, WER từ 5–7% ở bản tin lên 36% ở đây. Hai bài hóa hữu cơ (UMP, nguồn tự ghi "độ khó nghe rất khó") có WER 40–70% với cả hai model. Ở mức này transcript không dùng được để đọc lại nếu không sửa tay.
2. **PhoWhisper chính xác hơn một chút, chủ yếu vì turbo bỏ sót lời nói.** PhoWhisper có CER thấp hơn 3,1 điểm. Turbo làm mất 2.073 từ, gấp 2,4 lần PhoWhisper (849 từ). Có đoạn turbo bỏ trống liền 108 giây trong khi giảng viên vẫn nói. Nếu chỉ tính từ bị nghe sai thì PhoWhisper lại sai nhiều hơn (3.339 so với 2.797).
3. **PhoWhisper thắng ở từ tiếng Việt, turbo thắng ở từ Latin.** PhoWhisper đúng hơn với "dị tật bẩm sinh" (7/10 so với 2/10), "di truyền" (4/4 so với 0/4) và "dạ dày" (25/50 so với 15/50). Turbo đúng hơn với "DNA" (6/6 so với 0/6), "histone", "nucleotide", "benzoic" và "banner". Kết quả này giống vòng 10-29.
4. **Bộ lọc câu bịa vẫn còn lỗ hổng.** Turbo bịa 7 câu kiểu "Các bạn hãy đăng kí cho kênh lalaschool…", dài 1,3–29 giây, và cả 7 câu đều lọt bộ lọc (mục 6.2). Đã sửa cùng ngày (mục 10).
5. **Đầu ra của PhoWhisper vẫn khó dùng cho giao diện.** Toàn chữ thường, không có chữ số, câu dài 14–26 giây. Tính cả job thì chậm gấp 2,1 lần turbo, riêng bước nhận dạng chậm gấp 3,6 lần.

**Đề xuất:** chưa chuyển sang PhoWhisper. Mức hơn 3 điểm CER chưa phải là "thắng rõ" theo tiêu chí đặt ra ở mục 9.3 của báo cáo trước, và phần lớn mức chênh đến từ lỗi bỏ sót của turbo. Lỗi này đã nằm trong danh sách cần sửa (#19). Nên làm trước: sửa bộ lọc ở mục 6.2, đưa bước nhận dạng lại từng vùng VAD trống (#19) vào pipeline, thử `hotwords` cho bài giảng chuyên ngành. Sau đó đo lại trên bộ này. Chi tiết ở mục 8.

---

## 2. Bộ dữ liệu

| Mã | Bài | Thời lượng | Từ gỡ băng | Người nói (gỡ băng) | Đặc điểm |
|---|---|---|---|---|---|
| `quahat` | Quả và Hạt (phần 2), Thực vật Dược, UMP | 5:34 | 794 | 1 | Giảng đường, thuật ngữ thực vật ("nội nhũ", "alêron") |
| `phoi21` | Phôi thai học phân tử và dị tật bẩm sinh (P1), ĐH Y HN | 8:48 | 2.252 | 2 | Giảng đường, xen thuật ngữ tiếng Anh (DNA, histone) |
| `phoi42` | Phôi thai học hệ tiêu hóa (4.2), ĐH Y HN | 18:02, chấm 13:50 | 3.120 | 1 | Giảng đường vang, micro xa |
| `aldehyd` | Aldehyd – Ceton (phần 1), Hóa hữu cơ 1, UMP | 13:33 | 2.840 | 1 | Nguồn ghi "độ khó nghe rất khó", danh pháp IUPAC |
| `acid` | Bài tập acid đơn chức và dẫn xuất (phần 2), UMP | 19:36 | 2.451 | 1 | Nguồn ghi "độ khó nghe rất khó", đọc tên hợp chất liên tục |
| `hop2` | Họp giao ban phòng marketing | 14:17 | 2.720 | 14 vai | Cuộc họp nhiều người, nói chồng, xen từ tiếng Anh |
| `hop1` | Kỹ năng điều hành cuộc họp (lớp đào tạo) | 28:20 | 5.017 | 3 | **Không đưa vào số gộp**, xem mục 7 |

Bản gỡ băng lấy từ `data/Data thực tế/ground_truth/`. Script chỉ đọc phần lời, bắt đầu từ "### PHẦN 1". Nó bỏ tên người nói, các dòng `*(…)*`, và cả ghi chú `*(Cười)*` nằm giữa câu.

---

## 3. Cấu hình chạy

| Mục | Giá trị |
|---|---|
| Máy | RTX 4050 Laptop 6 GB, Docker trên WSL2. Windows chiếm sẵn khoảng 0,76 GB VRAM |
| Image | `stt-backend:latest` build ngày 2026-11-02. Đã đối chiếu từng file trong `backend/app` với repo, không lệch |
| Model A | `large-v3-turbo` (faster-whisper) |
| Model B | `vinai/PhoWhisper-large`, bản đã chuyển sẵn ở `/cache/huggingface/phowhisper-large-ct2` (float16) |
| Kiểu tính, tham số giải mã | Giữ như `.env` và `stt_engine.py`: `int8`, `beam_size=5`, `language="vi"`, `hallucination_silence_threshold=2.0` |
| Thuật ngữ, số người nói | Không nhập |
| Đổi model | Đặt `WHISPER_MODEL` cho `worker-gpu` bằng file override. Không sửa code |

---

## 4. Cách chấm

Giữ nguyên cách chấm của vòng 10-29 (`score.py`): NFC, chữ thường, bỏ dấu câu, số đọc thành chữ, quy kiểu bỏ dấu cũ về kiểu mới. WER và CER tính bằng khoảng cách chỉnh sửa trên từ và trên ký tự. Vòng này thêm ba điểm:

1. **Quy các cách viết đều đúng về một dạng**, áp cho cả hai phía: axit/acid, aldehyde/andehit/aldehyd, xeton/ceton, ancol/alcol, cacbon/carbon, clorua/clorid, este/ester… Bản gỡ băng tự nó viết lẫn "axit" với "acid", nên không quy về một dạng thì cả hai model đều bị tính sai oan.
2. **`phoi42` chỉ chấm tới giây 830.** Bản gỡ băng dừng ở câu "các bạn nghỉ khoảng 30 phút". Turbo nhận câu này ở giây 815, và từ đó tới hết file là giờ giải lao. Đầu file gỡ băng ghi phần giảng là "00:00–07:35", nhưng mốc này sai.
3. **Thuật ngữ:** mỗi bài có một danh sách 22–43 thuật ngữ chuyên ngành, tổng 978 lần xuất hiện trên 6 bài. Danh sách nằm trong `evaluate.py`.

Không chấm người nói cho các bài giảng một người: con số 93–99% ở đó chỉ phản ánh số từ không được gán nhãn. Chỉ `hop2` có kết quả người nói đáng xem (mục 5.3).

---

## 5. Kết quả theo bài

### 5.1. Độ chính xác chữ

| Bài | Model | WER | CER | WER bỏ từ đệm | Thay / Mất / Chèn | Thuật ngữ khớp |
|---|---|---|---|---|---|---|
| quahat | turbo | 19,27% | 14,71% | 18,41% | 79 / 69 / 5 | 76/121 |
| quahat | PhoWhisper | **15,87%** | **10,46%** | **16,40%** | 84 / 25 / 17 | **84/121** |
| phoi21 | turbo | 13,06% | 9,84% | 10,29% | 94 / 191 / 9 | **97/134** |
| phoi21 | PhoWhisper | **10,79%** | **7,33%** | **10,00%** | 117 / 86 / 40 | 93/134 |
| phoi42 | turbo | 45,67% | 34,33% | 46,23% | 853 / 515 / 57 | 32/183 |
| phoi42 | PhoWhisper | **39,74%** | **28,66%** | **40,12%** | 893 / 189 / 158 | **45/183** |
| aldehyd | turbo | **40,42%** | 29,20% | **41,36%** | 822 / 231 / 95 | **64/276** |
| aldehyd | PhoWhisper | 42,96% | **29,14%** | 44,86% | 941 / 109 / 170 | 49/276 |
| acid | turbo | 70,42% | 57,89% | **71,06%** | 810 / 872 / 44 | **7/209** |
| acid | PhoWhisper | **70,01%** | **51,05%** | 71,44% | 1.142 / 375 / 199 | 3/209 |
| hop2 | turbo | **13,20%** | 10,09% | 11,90% | 139 / 195 / 25 | **47/55** |
| hop2 | PhoWhisper | 13,68% | **9,99%** | **11,71%** | 162 / 65 / 145 | 38/55 |

Gộp riêng 5 bài giảng (11.457 từ): turbo có WER 41,42% và CER 32,30%, PhoWhisper có WER 39,67% và CER 28,50%.

Đọc bảng:

- PhoWhisper có CER thấp hơn hoặc ngang turbo ở cả 6 bài, và WER thấp hơn ở 4/6 bài.
- Cột "Mất" cho thấy rõ khác biệt. Turbo mất nhiều chữ hơn ở mọi bài, gấp 2–3 lần ở `quahat`, `phoi21`, `phoi42`, `hop2`. Ngược lại PhoWhisper chèn nhiều hơn: có từ đệm, và có đoạn tự sinh chữ ở vùng nghe không rõ.
- `hop2` là cuộc họp thật, giọng gần micro. Hai model ngang nhau ở mức khoảng 10% CER, gần với mức của bản tin.
- `acid` hỏng với cả hai model, nhưng hỏng theo hai kiểu khác nhau. Turbo bỏ trống từng đoạn dài. PhoWhisper vẫn ra chữ nhưng chữ vô nghĩa: ở giây 257 nó viết "trong khi toàn bộ những thông tin bị lộ có rất nhiều ý nghĩ chiến tranh", ở giây 291 viết "đó là chuyên khoa vô địch".

### 5.2. Thuật ngữ khác nhau giữa hai model (từ 2 lần xuất hiện trở lên)

| Bài | Thuật ngữ | turbo | PhoWhisper | Ghi chú |
|---|---|---|---|---|
| phoi21 | DNA | **6/6** | 0/6 | PhoWhisper: "nay", "nây" |
| phoi21 | histone, nucleotide | **4/4** | 0/4 | PhoWhisper: "stone", "tít" |
| phoi21 | dị tật bẩm sinh | 2/10 | **7/10** | turbo: "dị tập ẩm sinh" (5 lần) |
| phoi21 | di truyền | 0/4 | **4/4** | turbo: "di chuyển" |
| phoi21 | biệt hóa | **2/6** | 0/6 | cả hai: "biến hóa" |
| phoi42 | dạ dày | 15/50 | **25/50** | turbo: "dạng dày", "dạng giày" |
| phoi42 | tá tràng | 0/20 | **2/20** | turbo: "tái trạng"; PhoWhisper: "tài trạm", "tai tràng" |
| phoi42 | môn vị | **9/21** | 1/21 | PhoWhisper: "con tuổi" (5 lần) |
| phoi42 | nôn | 0/9 | **3/9** | turbo: "nâu", "nông" |
| quahat | nội nhũ | 19/32 | **25/32** | cả hai: "nội nhổ" |
| quahat | vỏ quả | **3/3** | 1/3 | PhoWhisper: "giỏ quả" |
| aldehyd | carbon | **15/19** | 9/19 | PhoWhisper: "bò" |
| aldehyd | acrylic | 0/3 | **3/3** | turbo: "acrylite" |
| aldehyd | benzoic | **3/3** | 0/3 | |
| aldehyd | aldehyd | 3/33 | 0/33 | turbo bỏ trống 7 lần; PhoWhisper: "ý", "adenine" |
| acid | carbon | 0/10 | 1/10 | turbo: "con"; PhoWhisper: "bon", "bom" |
| hop2 | banner | **3/4** | 0/4 | PhoWhisper: "vendor" |

Từ tên hợp chất trở đi, cả hai model đều không dùng được: "aldehyd" đúng 0–3/33, "acid" ở bài `acid` đúng 1–2/40. Đây là chỗ cần nhập thuật ngữ (`vocabulary` hoặc `hotwords`), không phải chỗ đổi model là giải quyết được.

### 5.3. Người nói (`hop2`, 14 vai trong bản gỡ băng)

| Model | Số cụm máy tìm ra | Độ chính xác | Độ thuần cụm | Từ không nhãn |
|---|---|---|---|---|
| turbo | 10 | **92,6%** | 95,6% | **81** |
| PhoWhisper | 10 | 90,7% | 95,8% | 142 |

Hai model dùng chung pyannote 3.1. Kết quả giống vòng 10-29: PhoWhisper có nhiều từ không nhãn hơn, tức mốc thời gian từng từ kém chính xác hơn. Ở `phoi21`, câu hỏi 24 từ của học viên bị gộp vào cụm của giảng viên với cả hai model.

### 5.4. Thời gian và VRAM

| Bài | Thời lượng | turbo: tổng / nhận dạng / diarization | PhoWhisper: tổng / nhận dạng / diarization |
|---|---|---|---|
| quahat | 334 s | 57,9 / 20,1 / 29,9 s | 95,1 / 63,8 / 25,3 s |
| phoi21 | 528 s | 61,9 / 28,0 / 25,1 s | 162,1 / 129,7 / 24,4 s |
| phoi42 | 1.082 s | 105,1 / 43,0 / 48,0 s | 225,6 / 165,9 / 45,6 s |
| aldehyd | 813 s | 85,4 / 38,2 / 35,1 s | 180,0 / 133,1 / 34,5 s |
| acid | 1.176 s | 116,9 / 50,5 / 50,3 s | 195,2 / 131,5 / 48,6 s |
| hop1 | 1.700 s | 173,8 / 80,0 / 72,7 s | 375,9 / 282,1 / 73,7 s |
| hop2 | 857 s | 87,8 / 38,4 / 38,3 s | 204,8 / 154,7 / 37,6 s |
| **Cộng** | **6.489 s** | **688,8 / 298,2 s** (0,106 × thời lượng) | **1.438,7 / 1.060,8 s** (0,222 × thời lượng) |

Đỉnh VRAM toàn card, tính cả phần Windows giữ: turbo 2,61–2,65 GB, PhoWhisper 3,12–3,25 GB. Ngoại suy cho một bài 3 giờ: turbo khoảng 19 phút, PhoWhisper khoảng 40 phút.

### 5.5. Dạng chữ đầu ra

| Đặc điểm | turbo | PhoWhisper |
|---|---|---|
| Chữ hoa | 0,7–6,3% số chữ cái | 0% |
| Chữ số | Có ("1, 2, 3, 4") | Không, số viết bằng chữ |
| Độ dài câu, trung vị | 2,3–5,8 s | 5,4–25,8 s, đa số 20–25 s |
| Số câu (`hop1`) | 158 | 74 |

---

## 6. Phân tích lỗi

### 6.1. Turbo bỏ trống những đoạn có lời nói

| Bài | Đoạn turbo không ra chữ | PhoWhisper ở cùng chỗ |
|---|---|---|
| acid | 109,7–218,0 s (108 s), 424,7–495,9 s (71 s), 691–732 s, 767–802 s, 946–978 s | Có chữ, phần lớn là chữ vô nghĩa. Khoảng trống dài nhất là 32 s |
| phoi42 | Gần hết 50 giây đầu, mất khoảng 150 từ ("thai nhi đi tiểu… đa ối… rò khí quản") | Đủ |
| aldehyd | 761,8–780,4 s, mất 30 từ, rồi bịa câu "lalaschool" ở giây 802 | Đủ |
| hop1 | 460,1–487,4 s, mất 128 từ ("tự nhiên nó phải thấy trách nhiệm…") | Đủ |

Đây chính là lỗi 7.2 của báo cáo 10-29 (#19 trong `docs/FLOWS.md`): VAD đã đưa đoạn vào chunk, nhưng Whisper không trả ra chữ. Lỗi này xuất hiện nhiều hơn hẳn ở giảng đường vang và giọng nói xa micro.

### 6.2. Câu bịa còn lọt bộ lọc

| Model | Bài | Giây | Dài | Câu |
|---|---|---|---|---|
| turbo | acid | 0,7 | 8,9 s | "Các bạn hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn" |
| turbo | acid | 341,3 | 1,3 s | "Để không bỏ lỡ những video hấp dẫn" |
| turbo | acid | 1103,2 và 1112,5 | 6,2 s và 9,3 s | "Các bạn hãy đăng kí cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn" |
| turbo | aldehyd | 618,5 và 802,0 | 5,9 s và 7,1 s | như trên |
| turbo | hop1 | 1573,4 | 29,0 s | như trên |
| PhoWhisper | hop1 | 1421,9 | 25,8 s | "cảm ơn bạn đã cùng theo dõi và đăng ký kênh của chương trình." |

Lý do lọt, theo `backend/app/services/stt_engine.py`:

- `_CALL_TO_ACTION` có "hãy subscribe" và "các bạn hãy đăng kí kênh", nhưng không có "**các bạn** hãy subscribe" và "hãy đăng kí **cho** kênh". Hàm lại chỉ so khớp phần đầu câu (`startswith`).
- "Để không bỏ lỡ những video hấp dẫn" đứng riêng thành một câu, mà danh sách cụm không có câu này.
- `_HALLUCINATED` có "cảm ơn các bạn đã theo dõi", nhưng câu của PhoWhisper là "cảm ơn bạn đã **cùng** theo dõi".
- Mỗi câu kéo dài 1,3–29 giây, tức chỉ 0,4–2 từ/giây, nên điều kiện tốc độ nói không bắt được.

Đã sửa cùng ngày, xem mục 10. Nhờ cải tiến ở bản 10-29, PhoWhisper giờ không còn câu bịa kiểu nói nhanh (mỗi bài trước đó có 13–20 câu).

### 6.3. Lỗi nghe sai thường gặp

- **turbo:** nhầm phụ âm đầu và vần y như vòng trước: "tật" thành "tập" (9 lần), "bẩm" thành "ẩm", "tá tràng" thành "tái trạng", "dạ dày" thành "dạng dày", "chức" thành "chiếc"/"trích", "truyền" thành "chuyển", "mầm" thành "mộng". Ở bài `acid`, turbo hay thay cả cụm bằng chữ số ("là", "gốc", "acid" thành "4").
- **PhoWhisper:** ít nhầm âm Việt hơn, nhưng phiên âm từ Latin theo kiểu tiếng Việt: "DNA" thành "nay", "carbon" thành "bon"/"bò", "aldehyd" thành "ý", "-yl" thành "y" (9 lần). Nó cũng hay viết "ý" thay cho "ấy" và thay từ chức năng ("nó" thành "là", "cái" thành "kẻ").

---

## 7. Giới hạn của lần đo

- **Bản gỡ băng `hop1` không đầy đủ.** Từ khoảng giây 590 tới 1.480, cả hai model sinh ra những đoạn dài không có trong bản gỡ băng (turbo 1.307 từ, PhoWhisper 1.676 từ). **Toàn bộ 1.307 từ của turbo rơi đúng vào những chỗ PhoWhisper cũng chèn.** Nội dung các đoạn này là lời giảng thật ("trước khi bắt đầu cuộc họp chúng ta dùng cái này…"), nên đây là chỗ bản gỡ băng bị lược. Vì vậy `hop1` không vào số gộp. Để tham khảo: turbo có WER 61,67%, PhoWhisper 59,04%.
- **Bản gỡ băng đã biên tập.** Bài `acid` viết công thức dạng LaTeX (`$-SO_2-NH_2$`). Có chỗ đã sửa văn phong hoặc thêm chữ in đậm. Vì vậy CER đo được là cận trên. Phần chênh giữa hai model đáng tin hơn con số tuyệt đối.
- **Nguồn âm thanh là bài giảng đăng mạng, không do nhóm tự thu.** Chất lượng micro và độ vang khác nhau nhiều giữa các bài. Đây là lý do WER dao động từ 10% (`phoi21`, `hop2`) tới 70% (`acid`).
- **Mỗi cấu hình chạy một lần**, không nhập thuật ngữ. PhoWhisper vẫn dùng tham số giải mã của turbo.
- Đầu file gỡ băng `4.2` ghi phần giảng là 00:00–07:35, nhưng thực tế phần giảng kéo tới khoảng 13:40. Nên sửa lại dòng này trong file.

---

## 8. Đề xuất

1. **Giữ `large-v3-turbo` làm mặc định, chưa chuyển sang PhoWhisper.** PhoWhisper có CER thấp hơn 3,1 điểm, nhưng phần lớn mức chênh đến từ chỗ turbo bỏ trống lời nói (mục 6.1). Đó là lỗi của pipeline có thể sửa được. Đổi lại, PhoWhisper chậm gấp 2,1 lần, ra toàn chữ thường, câu dài 20–25 giây, và kém ở thuật ngữ Latin, vốn rất nhiều trong bài giảng Y Dược.
2. **Sửa bộ lọc câu bịa theo mục 6.2.** Đã làm (mục 10): bỏ được 7/7 câu bịa của turbo, không bắt nhầm câu thật nào trong 1.088 câu.
3. **Đưa bước nhận dạng lại từng vùng VAD trống (#19) vào pipeline.** Đây là việc ảnh hưởng nhiều nhất tới khoảng cách giữa hai model: 2.073 từ mất của turbo so với 849 của PhoWhisper.
4. **Đo turbo có nhập thuật ngữ** (`vocabulary`, hoặc thử `hotwords`) trên `aldehyd`, `acid`, `phoi42`. Với bài chuyên ngành, đây là đòn bẩy lớn hơn việc đổi model: tỉ lệ khớp đúng thuật ngữ hiện chỉ 1–20% ở các bài này.
5. **Sau 2–4, chạy lại `run_all.sh` trên bộ này** để so sánh. Nếu turbo đã sửa vẫn kém PhoWhisper quá 3 điểm CER ở bài giảng, có thể cân nhắc một chế độ "bài giảng" dùng PhoWhisper, kèm bước chuẩn hóa LLM để có chữ hoa và dấu câu.
6. Bổ sung phần bị lược trong bản gỡ băng `hop1` (khoảng 590–1.480 s), hoặc ghi rõ khoảng đã gỡ băng, để lần sau chấm được bài này.

---

## 9. Chạy lại

Thư mục `do-cer-2026-11-03/` nằm cạnh báo cáo này:

| File | Việc |
|---|---|
| `run_all.sh` | Đặt biến `S` là thư mục làm việc có `run_job.py`. Script chép 7 file vào container `backend`, đổi `WHISPER_MODEL` cho `worker-gpu`, chạy 7 bài × 2 model, ghi đỉnh VRAM vào `runs/<model>/` |
| `run_job.py` | Giữ nguyên từ vòng 10-29. Tải file lên `POST /api/jobs`, theo dõi trạng thái, lưu transcript và thời gian từng bước |
| `score.py` | Giữ nguyên từ vòng 10-29: chuẩn hóa chữ, đổi số thành chữ, căn từ, khoảng cách chỉnh sửa |
| `evaluate.py` | Đọc bản gỡ băng (bỏ cả ghi chú giữa câu), quy cách viết về một dạng, cắt `phoi42` ở giây 830, tính WER, CER, thuật ngữ, người nói, câu bịa, đoạn chèn/mất dài. Ghi `results.json` |
| `analyze.py` | Số gộp, kiểm tra đoạn chèn chung của hai model ở `hop1`, thời gian từng bước, dạng chữ |
| `results.json` | Toàn bộ số đo của báo cáo này |
| `raw-logs/` | Log và thời gian từng job, đầu ra của `evaluate.py` và `analyze.py` |

Transcript máy của 14 lần chạy không đặt vào thư mục này, vì chúng chứa nội dung bài giảng của bên thứ ba. Muốn chạy `evaluate.py` thì đặt thư mục `runs/` cạnh script.

---

## 10. Cập nhật cùng ngày: sửa bộ lọc lời mời đăng ký kênh

Thay đổi trong `backend/app/services/stt_engine.py`:

- `_plain` quy "đăng kí" về "đăng ký".
- `_CALL_TO_ACTION` được so khớp ở **bất kỳ vị trí nào** trong câu từ 20 từ trở xuống, không chỉ ở đầu câu. So khớp theo ranh giới từ.
- Danh sách cụm đổi thành: "hãy subscribe", "subscribe cho kênh", "hãy đăng ký kênh", "hãy đăng ký cho kênh", "không bỏ lỡ những video", "theo dõi và đăng ký kênh". Không thêm "đăng ký kênh" đứng riêng, để giữ câu thật như "bàn về việc đăng ký kênh phân phối mới".

Thêm test `test_call_to_action_inside_sentence_is_dropped` với 4 câu bịa đã gặp, và 2 câu thật phải giữ. Cả 78 test của backend đều qua.

Kiểm tra:

1. **Áp bộ lọc mới lên mọi câu của 14 transcript** (`check_filter.py`, 1.088 câu). Bộ lọc bắt 7/8 câu bịa và không bắt nhầm câu thật nào. Câu còn lại (turbo, `hop1`, giây 1573) bị `_merge_sentences` gộp với lời nói thật sau nó thành một câu 127 từ. Nhưng bộ lọc chạy trên đoạn Whisper trước khi gộp, nên cần chạy lại mới biết.
2. **Chạy lại turbo qua pipeline với code đã sửa** (`run_fix.sh`, mount `./backend` vào `worker-gpu`) trên 3 bài có câu bịa:

| Bài | Câu bịa trước → sau | WER trước → sau | CER trước → sau |
|---|---|---|---|
| acid | 4 → 0 | 70,42% → 70,42% | 57,89% → 58,51% |
| aldehyd | 2 → 0 | 40,42% → 40,46% | 29,20% → 29,60% |
| hop1 | 1 → 0 | 61,67% → 61,51% | 51,42% → 51,29% |

Câu bịa ở `hop1` bị bỏ, còn lời nói thật từ giây 1579 trở đi vẫn giữ nguyên.

WER và CER gần như không đổi, vì bộ lọc chỉ xóa chữ bịa, không lấy lại được lời nói bị che. Ở `acid` còn tăng nhẹ, vì vài chữ trong câu bịa ("các bạn", "những") tình cờ khớp với bản gỡ băng. Chỗ câu bịa từng nằm nay thành khoảng trống. Ví dụ ở `acid`, giây 1077–1141 là 63 giây không có chữ. Như vậy lợi ích của bản sửa nằm ở giao diện: không còn câu quảng cáo lạ trong transcript. Muốn lấy lại phần lời nói đó thì phải làm #19 (mục 8.3).

Thời gian chạy lại chậm hơn lần đầu (`acid` 210 s so với 117 s), vì code được mount từ ổ Windows vào container. Không so sánh thời gian giữa hai lần chạy.
