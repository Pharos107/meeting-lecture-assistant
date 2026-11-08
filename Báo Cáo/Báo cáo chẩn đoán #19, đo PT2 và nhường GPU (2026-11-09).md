# Báo cáo chẩn đoán #19, đo PT2 và nhường GPU

**Ngày chạy:** 2026-11-09
**Người chạy:** nhóm dự án, với Claude Code hỗ trợ chạy lệnh, chẩn đoán và chấm điểm
**Máy:** Windows 11, Docker Desktop, RTX 4050 Laptop 6 GB, cùng bộ phiên bản với vòng 2026-11-05
**Dữ liệu:** 7 bài trong `data/Data thực tế/` (5 bài giảng, 2 cuộc họp, 108 phút), bản gỡ băng ở `ground_truth/`
**Code:** một worktree gộp các nhánh `fix/llm-truncated-answer`, `fix/cta-filter-21-words`, `feature/split-sentences-by-speaker`, `feature/gpu-yield`, `fix/redis-rate-limit`, `fix/empty-chunk-greedy`, `fix/stt-audio-robustness`, mount vào `backend` và `worker-gpu` bằng `override.yml`
**Script và output thô:** `Báo Cáo/do-cer-2026-11-09/`

## 1. Tóm tắt

| Gộp 6 bài như các vòng trước (bỏ `hop1`) | turbo 11-05 (vá + greedy) | turbo 11-09 cuối | PhoWhisper 11-03 |
|---|---|---|---|
| CER | 26,94% | **23,66%** | 24,97% |
| WER | 35,19% | **32,05%** | 34,68% |
| Số từ mất | 1.768 | 1.475 | 849 |
| Thay / Chèn | 2.960 / 261 | 2.740 / 329 | 3.339 / 729 |
| Thuật ngữ đúng nguyên văn | 323/978 | 357/978 | 312/978 |
| Câu bịa còn lọt (cả 7 file) | 2 | **0** | 1 |
| Thời gian xử lý / thời lượng (cả 7 file) | 0,116 | 0,120 | 0,222 |

| PT2 và nhường GPU, thử trên stack thật | Kết quả |
|---|---|
| Độ trễ câu nháp ổn định, câu không dài quá 8 giây | trung vị 1,03 s, p90 1,25 s, lớn nhất 3,03 s, 23/24 câu trong 3 giây |
| Rớt mạng 10 giây giữa phiên | nối lại bằng ticket mới, xả 100 khung đã giữ, pass 2 có 35 từ trong đúng khoảng rớt |
| Job PT1 28 phút đang nhận dạng, mở phiên nghe | job nhường ở chunk 5/71, phiên mở được ở lần thử thứ hai sau 3 giây, job chạy tiếp và về `ready` với 173 câu |

Kết luận ngắn:

1. **#19 có ba nguyên nhân mới, đã vá cả ba.** Sau vòng này turbo có CER và WER thấp hơn PhoWhisper trên cùng bộ dữ liệu mà vẫn nhanh gấp 1,85 lần. Turbo vẫn mất nhiều từ hơn PhoWhisper (1.475 so với 849), nhưng chèn ít hơn hẳn (329 so với 729).
2. **#25 đóng.** Bộ lọc bắt được cả câu 21 từ toàn cụm đã biết, cắt riêng phần lời mời dính trong câu dài, và có thêm cụm "like share và đăng ký kênh".
3. **#18 đóng.** Câu có từ mang hai nhãn người nói thật ở `hop2` giảm từ 10 ở vòng 11-03 xuống 4. Cả 4 câu còn lại là lượt ngắn được nhập vào lượt bên cạnh có chủ đích (mục 4).
4. **PT2 đạt mục tiêu độ trễ 3 giây** trên dữ liệu phát theo thời gian thực, và chịu được rớt mạng 10 giây mà không mất audio.
5. **Cơ chế nhường GPU chạy đúng trên stack thật**, gồm Redis, Postgres và worker Celery.

## 2. #19: ba nguyên nhân và cách vá

Mỗi lượt chạy 7 bài qua API bằng `run_1109.sh` và `run_job.py`, giống vòng 11-05. Chấm bằng `evaluate.py`, `score.py` chép từ vòng 11-05. Số gộp ở `compare_1109.py`, `raw-logs/compare_1109.txt`.

| Lượt | Code thêm so với lượt trước | CER gộp 6 bài | Từ mất |
|---|---|---|---|
| 11-05 vá + greedy | | 26,94% | 1.768 |
| 11-09 | Greedy khi cả chunk trống (2.1), #18, #25 phần đầu | 26,58% | 1.652 |
| 11-09b | Kẹp PCM về [-1, 1] (2.3) | 26,51% | 1.685 |
| 11-09c | Cứu khoảng VAD bỏ trống mà to, bỏ câu lặp (2.2) | 23,64% | 1.460 |
| 11-09d, cuối | Kẹp PCM theo khối, cắt lời mời dính trong câu, cụm "like share" | **23,66%** | 1.475 |

Lượt 11-09b chỉ đổi vài mẫu PCM ở `acid` và `quahat`, nơi đỉnh chạm 1,001, mà số từ mất từng bài lệch khoảng ±40. Đây là độ dao động của Whisper với thay đổi rất nhỏ ở đầu vào. Chênh lệch dưới mức đó giữa hai lượt không nên đọc là tác dụng của code.

### 2.1. Đầu bài `phoi42`: cả chunk trống nên greedy không chạy

`diag_exact.py` chạy chunk đúng mốc VAD 0,216–22,248 s. Beam search chỉ ra một câu "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn" phủ cả chunk. Bộ lọc xóa câu đó và chunk thành trống. `empty_spans` bỏ khoảng phủ cả chunk vì "nhận dạng lại cũng là cùng audio", nên bước greedy của vòng 11-05 không bao giờ chạy. Greedy trên chính chunk đó ra 6 câu thật.

Gọi lại với mốc làm tròn 0,2–22,2 s thì beam lại ra chữ. Kết quả nhạy với vài mili giây ở mép chunk, nên phải chẩn đoán đúng mốc VAD.

Vá: `fill_empty_spans` đưa khoảng phủ cả chunk thẳng sang greedy, không chạy lại beam. `phoi42` giảm từ 511 xuống 423 từ mất, CER 34,43% xuống 32,76%. Đoạn mất liền nhau ở đầu bài giảm từ 187 xuống 72 từ.

Còn lại ở `phoi42`: chunk 51,1–61,7 s vẫn trống với mọi cách giải mã đã thử (beam, greedy, temperature 0,4, prompt trung tính, cắt đôi, kèm 3 giây trước).

### 2.2. `acid`: VAD bỏ sót lời giảng to và beam rơi vào câu lặp

`diag_vad.py` ở 426–456 s: audio to và bị clip (rms 0,13–0,22, đỉnh 1,0), nhưng Silero chỉ thấy 1,6 s có tiếng ở ngưỡng 0,5 và 8,4 s ở ngưỡng 0,2. Whisper nhận dạng thẳng cả 30 giây ra lời giảng khớp bản gỡ băng: "Còn một nhóm nữa các bạn cũng nên biết, ví dụ như đây…".

`diag_gaps_rms.py` trên cả 7 bài, khoảng giữa hai vùng VAD dài từ 3 giây:

| Bài | rms phần có tiếng | Khoảng ≥ 3 s | Khoảng to ≥ 30% rms tiếng |
|---|---|---|---|
| `acid` | 0,215 | 56 khoảng, 476 s | 50 khoảng, 428 s |
| `phoi42` | 0,058 | 10 khoảng, 221 s | 5 khoảng, 106 s, phần lớn ở giờ nghỉ quanh giây 900–1.080 |
| `quahat` | 0,251 | 4 khoảng, 18 s | 4 khoảng, 18 s |
| các bài khác | | tối đa 32 s | tối đa 19 s |

Ngưỡng chọn là 50% rms phần có tiếng để không kéo tiếng nền giờ nghỉ của `phoi42` vào.

Khi các khoảng này vào chunk, beam có lúc ra câu lặp kiểu "Nói bạn, ví dụ như đây, thể chất CH3, CH3, CH3…" phủ cả chunk 25 giây. Với một mức `temperature`, faster-whisper chỉ dùng `compression_ratio_threshold` để quyết định giải mã lại, nên vẫn giữ câu lặp. `cr_scan.py` trên các transcript đã lưu: 12 câu khác nhau vượt tỉ lệ nén 2,4, đều là câu lặp ("vết tinh, vết tinh…", "VL3, VL3…", "dạy dạy dạy…"). Câu thật cao nhất là 2,08.

Vá:

- `add_loud_gaps`: khoảng VAD bỏ trống dài từ 3 giây mà rms đạt ít nhất 50% rms phần có tiếng thì vẫn đưa cho Whisper.
- `is_hallucination` bỏ câu có tỉ lệ nén trên 2,4. Khoảng đó thành trống và được nhận dạng lại, kể cả bằng greedy.

`acid` giảm từ CER 53,14% xuống 41,54%, `quahat` từ 14,83% xuống 11,75%, `aldehyd` từ 28,85% xuống 26,78%. Số từ chèn tăng từ 260 lên 329 trên 6 bài. Thời gian xử lý không đổi.

Còn lại ở `acid`: 9 đoạn mất liền nhau, 159 từ (vòng 11-05 là 12 đoạn, 327 từ).

### 2.3. `hop1`: mẫu PCM hỏng

`diag_pcm.py`: `hop1` có 77 mẫu cỡ 26.933, đều quanh giây 1.423, do một khung Opus giải mã hỏng. Vòng 11-03 có khoảng trống dài nhất của turbo ở đúng giây 1.419,6. Một mẫu như vậy làm lệch phổ mel của cả cửa sổ 30 giây.

Vá: `slice_pcm` kẹp đoạn đưa cho Whisper về [-1, 1]. VAD đi theo khối 10 giây và chỉ kẹp tại chỗ những khối có mẫu vượt, trên memmap copy-on-write, nên file không đổi và RAM không tăng theo độ dài bài. `diag_vadmem0.py` trên `hop1` (109 MB PCM): phần kẹp chỉ chạm các trang file đã đọc, bước cứu khoảng trống không thêm gì, còn khoảng 419 MB là của chính Silero như trước.

Bản gỡ băng `hop1` bị lược từ giây 590 tới 1.480, nên không đo được tác dụng ở giây 1.423.

### 2.4. Từng bài, lượt cuối

| Bài | CER 11-05 | CER 11-09 cuối | PhoWhisper 11-03 | Từ mất 11-05 → 11-09 |
|---|---|---|---|---|
| `quahat` | 14,83% | 11,75% | 10,46% | 66 → 42 |
| `phoi21` | 9,79% | 9,81% | 7,33% | 188 → 189 |
| `phoi42` | 34,43% | 31,75% | 28,66% | 511 → 435 |
| `aldehyd` | 28,85% | 26,78% | 29,14% | 221 → 183 |
| `acid` | 53,17% | 41,54% | 51,05% | 622 → 469 |
| `hop2` | 8,98% | 8,91% | 9,99% | 160 → 157 |
| `hop1`* | 51,22% | 51,48% | 50,98% | 464 → 473 |

\* `hop1` không vào số gộp, vì bản gỡ băng bị lược.

Đỉnh VRAM toàn card của lượt cuối là 2,90–2,93 GB.

## 3. #25: bộ lọc lời mời đăng ký kênh

- Câu dài hơn 20 từ mà số từ nằm ngoài mọi cụm đã biết không quá 8 thì bỏ cả câu. Bắt được câu 21 từ ở `acid` giây 791.
- Lời mời dính với lời thật thì cắt riêng phần lời mời, giữ phần còn lại. `hop1` giây 894 còn "Mày đi ra đi, hãy nhớ lại đi,". `hop1` giây 1573 vòng 11-03 bỏ 16 từ lời mời ở đầu câu 127 từ.
- Thêm cụm "like share và đăng ký kênh" và "đăng ký kênh để ủng hộ kênh", sau khi lượt 11-09c lọt câu "Các bạn có thể nhớ like, share và đăng ký kênh để ủng hộ kênh của chúng mình nhé." ở `acid` giây 870.

`trim_scan.py` và các lần so trước sau đều chạy trên mọi câu đã lưu của vòng 11-03 và các lượt 11-09. Mỗi luật chỉ đổi đúng những câu kể trên. Lượt cuối không còn câu bịa nào lọt.

## 4. #18: tách câu tại chỗ đổi người nói

`mixed.py` đếm câu có từ mang từ hai nhãn người nói thật trở lên, không tính từ null:

| Bài | 11-03 (code cũ) | 11-09 trước khi tách | 11-09 cuối |
|---|---|---|---|
| `hop2`, 10 nhãn | 10/154 | 4/165 | 4/161 |
| `hop1`, 2 nhãn | 1/158 | 1/185 | 1/173 |
| 5 bài giảng, 1 nhãn | 0 | 0 | 0 |

Lượt "11-09 trước khi tách" đã chạy code tách câu. Số 4 còn lại là các lượt dưới 2 từ và ngắn hơn 800 ms được nhập vào lượt bên cạnh đúng như thiết kế, để một từ lệch biên không cắt câu thành mảnh. Bộ dữ liệu này ít đổi lượt nói, nên chưa đo được trường hợp 553/1.287 câu của bài 86 phút ghi ở `FLOWS.md`. Cả 7 job đều về `ready` trên Postgres sau khi tách, vị trí câu và từ đúng thứ tự.

## 5. PT2

`live_e2e.py` chạy trong container `backend`, làm giống `LiveSocket` của trình duyệt: phát 3 phút đầu `hop2` theo thời gian thực, khung 100 ms. Tới giây 90 thì đóng socket, giữ khung trong hàng đợi tối đa 250 khung, sau 10 giây xin ticket mới, nối lại, gửi `hello`, rồi xả hàng đợi.

- Độ trễ tính từ mốc `end_ms` của câu theo giờ phát tới tin `draft` ổn định của câu đó. Chỉ tính câu không dài quá 8 giây và không nằm trong lúc rớt mạng hay 15 giây sau đó: 24 câu, trung vị 1,03 s, p90 1,25 s, lớn nhất 3,03 s, 23/24 trong 3 giây. Đạt mục tiêu thiết kế ở ý tưởng mục 6.
- Server gửi `draft_degraded` hai lần, một lần ngay sau khi xả 10 giây audio dồn lại. Đây là đúng thiết kế khi nháp chạy chậm.
- Pass 2 về `ready` sau 30 giây, 26 câu, 517 từ, có 35 từ trong khoảng rớt mạng, nên không mất audio.

Chưa thử: chia sẻ âm thanh tab trên trình duyệt thật, vì cần người chọn tab trong hộp thoại của trình duyệt. Lần thử này cũng không đi qua giao diện `/live`, nên chưa kiểm phần hiển thị lúc nối lại.

## 6. Nhường GPU

`yield_e2e.py` tải `hop1` (28 phút) lên làm job PT1, chờ job vào `transcribing`, rồi mở phiên nghe như trang `/live`:

1. Lần gọi đầu trả `409 gpu_yielding`.
2. Job đọc cờ giữa hai chunk, nhường ở chunk 5/71, trao khóa giữ chỗ cho người xin và `retry`.
3. Lần gọi thứ hai, 3 giây sau, mở được phiên.
4. Dừng phiên. Pass 2 của phiên rỗng thì báo lỗi và nhả khóa như test có sẵn.
5. Job lấy lại khóa, chạy tiếp từ chunk 5 và về `ready` sau 211 giây kể từ lúc tải lên, 173 câu, mốc tăng dần.

## 7. Việc còn lại

- #19: chunk 51,1–61,7 s của `phoi42` và 9 đoạn của `acid` (159 từ). Turbo vẫn mất gấp 1,7 lần số từ so với PhoWhisper.
- #20 và việc khóa model bản chuẩn vẫn cần ghi âm họp do nhóm tự thu.
- PT2: thử chia sẻ tab và rớt mạng trên giao diện `/live` thật.
- Chỉnh `VOICE_MATCH_THRESHOLD` cần mẫu giọng của nhóm.

## 8. File trong `do-cer-2026-11-09/`

| File | Việc của nó |
|---|---|
| `run_1109.sh`, `run_job.py`, `override.yml` | Chạy 7 bài qua API trong Docker, code mount từ worktree tích hợp. Biến `OUT` đặt tên lượt |
| `evaluate.py`, `score.py` | Chấm CER, WER, thuật ngữ, người nói. Chép từ vòng 11-05 |
| `compare_1109.py` | Số gộp và so với vòng 11-05, PhoWhisper 11-03 |
| `diag_exact.py`, `diag_filter.py` | Chunk đúng mốc VAD và lý do bộ lọc bỏ câu |
| `diag_vad.py`, `diag_gaps_rms.py`, `diag_loud.py` | VAD bỏ sót lời nói to, rms của khoảng trống, khoảng được thêm |
| `diag_pcm.py`, `diag_vadmem0.py` | Mẫu PCM hỏng và bộ nhớ của bước VAD |
| `cta_scan.py`, `cta_compare.py`, `trim_scan.py`, `cr_scan.py` | Thử luật lời mời, phần cắt và tỉ lệ nén trên câu đã lưu |
| `mixed.py` | Đếm câu lẫn hai nhãn người nói |
| `live_e2e.py`, `yield_e2e.py` | Thử PT2 và nhường GPU trên stack thật |
| `results.json` | Kết quả chấm của 4 lượt 11-09 |
| `raw-logs/` | Log từng job, VRAM, output của các script |

Transcript đầy đủ của từng job không đưa vào repo, giống các vòng trước. Các script chẩn đoán đọc audio trong container, nên đường dẫn `/tmp/...` là của container.
