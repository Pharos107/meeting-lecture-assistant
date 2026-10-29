# Báo cáo quy trình test nhận dạng giọng nói và raw output

**Ngày chạy:** 2026-10-29
**Người chạy:** nhóm dự án, với Claude Code hỗ trợ chạy lệnh và chấm điểm
**Phạm vi:**
1. So sánh hai model nhận dạng: `large-v3-turbo` (Whisper v3 turbo) và `PhoWhisper-large`.
2. Đo khả năng chịu nhiễu và chất lượng chia chunk của pipeline.
3. Sửa bộ lọc câu bịa, rồi đo lại để so trước và sau.

Báo cáo này ghi **cách chạy** và **output thô (raw output)**. Phần phân tích và đề xuất nằm ở `Báo cáo đo CER - large-v3-turbo và PhoWhisper-large (2026-10-29).md`, cùng thư mục.

---

## Mục lục

1. Môi trường
2. Dữ liệu test
3. Quy trình chạy test, từng bước
4. Cách chấm điểm
5. Kết quả tóm tắt: hai model, trước và sau khi sửa
6. Raw output: so sánh hai model
7. Raw output: trước và sau khi sửa
8. Raw output: chia chunk và nhiễu
9. Raw output: log chạy job
10. Vị trí file

---

## 1. Môi trường

| Mục | Giá trị |
|---|---|
| Máy | Windows 11, Docker Desktop (WSL2), 16 nhân CPU, 15 GB RAM cho Docker |
| GPU | NVIDIA GeForce RTX 4050 Laptop, 6 GB VRAM, driver 610.88. Windows giữ sẵn 1,2–1,4 GB |
| Image backend | `stt-backend:latest`, nền `python:3.11-slim-bookworm`, 10,3 GB |
| Thư viện | torch 2.5.1+cu121, cuDNN 9.1, ctranslate2 4.5.0, faster-whisper 1.1.1, pyannote.audio 3.3.2, numpy 1.26.4, huggingface_hub 0.36.2 |
| Dịch vụ | `postgres`, `redis`, `backend` (FastAPI), `worker-gpu` (Celery, hàng `gpu`) chạy bằng `docker compose` |
| Model A | `large-v3-turbo`: faster-whisper tự tải `mobiuslabsgmbh/faster-whisper-large-v3-turbo` |
| Model B | `vinai/PhoWhisper-large`, tự chuyển sang CTranslate2 (float16 trên đĩa) |
| Kiểu tính | `int8` cho cả hai model |
| Diarization | `pyannote/speaker-diarization-3.1` trên CUDA |

Output kiểm phiên bản trong container `worker-gpu`:

```text
torch 2.5.1+cu121 torchaudio 2.5.1+cu121 cuda 12.1 avail True NVIDIA GeForce RTX 4050 Laptop GPU
cudnn 90100
ct2 4.5.0 cuda devices 1 True
fw 1.1.1 pyannote 3.3.2 numpy 1.26.4 hf_hub 0.36.2
```

---

## 2. Dữ liệu test

Ba bản tin VTV24 trong `data/phóng sự 7p/`, mỗi bài kèm một bản gỡ băng `Phụ đề _….md` có tên người nói:

| Mã | Bài | Thời lượng | Từ trong bản gỡ băng | Người nói |
|---|---|---|---|---|
| `phapluat` | Nâng cao ý thức, trách nhiệm của nhân dân trước pháp luật | 7:54 | 1.922 | 6 |
| `coso2` | Cơ sở 2 giảm tải bệnh viện tuyến Trung ương (cụm tin) | 8:29 | 1.904 | 10 |
| `thegioi` | Thế giới toàn cảnh ngày 26/10 | 20:46 | 4.682 | 12 |
| | **Tổng** | **37:08** | **8.508** | |

Bản nhiễu được tạo từ bài `phapluat`:
- **nhiễu hồng**, giống tiếng quạt, điều hòa, xe cộ;
- **babble**, tiếng người nói lẫn nhau, ghép từ 4 luồng của hai podcast Vietcetera trong `data/`, lệch thời điểm.

Mỗi loại trộn ở SNR 20, 10, 5 và 0 dB, tính trên vùng có tiếng nói.

---

## 3. Quy trình chạy test, từng bước

Các script nằm trong `Báo Cáo/do-cer-2026-10-29/`. Mọi lần chạy đều đi qua đúng luồng tải file (PT1) của ứng dụng: `POST /api/jobs` → FFmpeg chuẩn hóa → Silero VAD → chia chunk → Whisper → pyannote → ghi Postgres. Không có bước nào gọi model trực tiếp, trừ bước 8 và bước 10, là các thí nghiệm giải mã có ghi chú riêng.

### Bước 1. Chuẩn bị môi trường

```bash
# .env tạo từ .env.example: mật khẩu Postgres và JWT_SECRET sinh ngẫu nhiên, HF_TOKEN do người dùng điền
docker compose build backend
docker compose up -d postgres redis
docker compose run --rm backend alembic upgrade head
docker compose up -d backend worker-gpu
```

Trước khi chạy được, phải sửa ba lỗi chỉ gặp trên GPU. Chúng đã merge qua PR #9:
- ghim image nền bookworm;
- ghim torch và torchaudio trong `requirements.txt`;
- kiểm GPU trong một tiến trình riêng.

### Bước 2. Chuyển PhoWhisper sang CTranslate2

Chạy một lần trong container dùng một lần. Model được ghi vào volume `hf-cache`:

```bash
docker compose run --rm --no-deps --entrypoint sh worker-gpu -c "pip install --user transformers==4.46.3 && ct2-transformers-converter --model vinai/PhoWhisper-large --output_dir /cache/huggingface/phowhisper-large-ct2 --copy_files tokenizer.json preprocessor_config.json --quantization float16 --force"
```

Output:

```text
-rw-r--r-- 1 appuser appuser       2796 config.json
-rw-r--r-- 1 appuser appuser 3086913037 model.bin
-rw-r--r-- 1 appuser appuser        339 preprocessor_config.json
-rw-r--r-- 1 appuser appuser    2204003 tokenizer.json
-rw-r--r-- 1 appuser appuser    1068103 vocabulary.json
feature_size 80, alignment_heads 23
```

### Bước 3. Chạy 3 bài × 2 model

`run_all.sh` làm lần lượt các việc sau cho mỗi model:
1. Ghi file override đặt `WHISPER_MODEL` cho `worker-gpu`, rồi tạo lại container worker.
2. Chạy `run_job.py` trong container `backend` cho từng bài. Script này đăng ký một tài khoản thử, `POST /api/jobs`, đọc trạng thái mỗi giây, và lưu transcript (`GET /api/jobs/{id}/transcript`) cùng thời gian từng bước.
3. Ghi VRAM bằng `nvidia-smi` mỗi giây trong lúc job chạy.

```bash
bash run_all.sh
```

Không nhập danh sách thuật ngữ và số người nói. Tham số giải mã giữ nguyên như trong `stt_engine.py`: `beam_size=5`, `language="vi"`, `temperature=0`, `condition_on_previous_text=False`, `word_timestamps=True`.

### Bước 4. Chấm điểm hai model

```bash
python -I -X utf8 evaluate.py
```

### Bước 5. Dựng lại VAD và chunk, đo lỗi quanh mép chunk

```bash
# trong container worker-gpu
python diag_chunks.py /tmp/chunks.json /tmp/phapluat.mp3 /tmp/coso2.mp3 /tmp/thegioi.mp3
# trên máy
python -I -X utf8 chunk_errors.py
```

### Bước 6. Tìm nguyên nhân turbo bỏ sót lời

Bước này chạy lại riêng 3 chunk bị mất chữ của bài `coso2` với 4 cấu hình giải mã, và với từng vùng VAD riêng lẻ:

```bash
# trong container worker-gpu
python retry_chunks.py /tmp/coso2.mp3 58.73:83.88 86.01:109.35 137.4:163.08
```

### Bước 7. Tạo bản nhiễu và chạy qua pipeline

```bash
# trong container worker-gpu
python make_noisy.py /tmp/phapluat.mp3 /data/noisetest /tmp/babble1.mp3 /tmp/babble2.mp3
# 8 file chạy qua run_job.py như bước 3, rồi trên máy:
python -I -X utf8 score_noise.py
```

### Bước 8. Thử các cách sửa (thí nghiệm, không qua API)

`exp_decode.py` chạy lại đúng chuỗi VAD → chunk → turbo → khử chồng của pipeline, nhưng bỏ bước diarization. Nó thử 5 cấu hình:
- **A:** như hiện tại;
- **B:** `hallucination_silence_threshold=2`;
- **C:** chunk tối đa 15 giây;
- **D:** C cộng B;
- **E:** lọc nhiễu FFmpeg `afftdn`.

Cấu hình A cho ra đúng WER của pipeline thật, nên khung thử đáng tin.

```bash
# trong container worker-gpu
python exp_decode.py /tmp/exp coso2=/tmp/coso2.mp3 babble_10db=/data/noisetest/babble_10db.wav babble_5db=/data/noisetest/babble_5db.wav pink_5db=/data/noisetest/pink_5db.wav pink_0db=/data/noisetest/pink_0db.wav
python -I -X utf8 score_exp.py
```

### Bước 9. Sửa code, test, chạy lại

Sửa `backend/app/services/stt_engine.py` trên nhánh `fix/hallucination-filter`:
- bật `hallucination_silence_threshold=2.0`;
- bỏ câu có từ 4 từ trở lên mà nói nhanh hơn 12 từ/giây;
- bỏ câu không quá 20 từ mở đầu bằng lời mời đăng ký kênh;
- ghép mảnh word không có dấu cách đầu (`.000`, `%`) vào từ trước.

```bash
cd backend && python -m pytest -q
docker compose build backend
docker compose up -d --force-recreate backend worker-gpu
# chạy lại 3 bài và 4 bản nhiễu qua run_job.py, rồi:
python -I -X utf8 compare_fix.py
```

### Bước 10. Xuất raw output

```bash
python -I -X utf8 export_raw.py data/raw-output-2026-10-29 excerpts.md
```

---

## 4. Cách chấm điểm

- **Chuẩn hóa, áp như nhau cho bản gỡ băng và bản máy:**
  - NFC, chữ thường, bỏ dấu câu;
  - `%` đọc thành "phần trăm", số đọc thành chữ ("2023" thành "hai nghìn không trăm hai mươi ba");
  - quy kiểu bỏ dấu cũ về kiểu mới ("hoá" thành "hóa");
  - ghép "150 .000" thành "150.000".
- **WER** = (thay + mất + chèn) / số từ của bản gỡ băng. **CER** tính tương tự trên ký tự.
- **Bản "đã lọc"** bỏ cùng một loại câu bịa cho cả hai model: câu từ 4 từ trở lên nói nhanh hơn 12 từ/giây, hoặc câu chứa "subscribe", "đăng ký kênh", "bỏ lỡ những video".
- **Thuật ngữ:** 189 lần xuất hiện của tên riêng và thuật ngữ. Mỗi lần xuất hiện được tính CER và xét có khớp nguyên cụm không.
- **Người nói:** ghép mỗi nhãn của pyannote với một người trong bản gỡ băng bằng thuật toán Hungarian, rồi tính tỉ lệ từ gán đúng.
- **Tiếng nói không ra chữ:** tổng thời gian trong các vùng VAD (của bản sạch) mà không có từ nào, chỉ tính khoảng từ 1,5 giây trở lên.

---

## 5. Kết quả tóm tắt

### 5.1. Hai model (trước khi sửa bộ lọc)

| Bài | Model | WER thô | CER thô | WER đã lọc | CER đã lọc | CER thuật ngữ | Gán đúng người nói | Thời gian |
|---|---|---|---|---|---|---|---|---|
| phapluat | large-v3-turbo | 8,32% | 6,39% | 7,54% | 5,52% | 10,55% | 96,82% | 70,8 s |
| phapluat | PhoWhisper-large | 29,50% | 29,66% | 7,75% | 5,85% | 4,77% | 96,10% | 159,8 s |
| coso2 | large-v3-turbo | 12,03% | 10,32% | 12,08% | 10,89% | 11,73% | 82,37% | 55,8 s |
| coso2 | PhoWhisper-large | 24,05% | 24,34% | 2,47% | 1,76% | 1,35% | 82,60% | 149,9 s |
| thegioi | large-v3-turbo | 3,67% | 1,87% | 3,67% | 1,87% | 8,32% | 79,00% | 146,5 s |
| thegioi | PhoWhisper-large | 18,62% | 15,73% | 6,88% | 3,75% | 29,89% | 77,68% | 327,8 s |
| **gộp** | **large-v3-turbo** | **6,59%** | **4,72%** | 6,43% | 4,66% | 9,82% | 83,71% | 273,1 s |
| **gộp** | **PhoWhisper-large** | 22,30% | 20,67% | **6,09%** | **3,77%** | 15,87% | 82,88% | 637,5 s |

### 5.2. large-v3-turbo trước và sau khi sửa bộ lọc

| Bài | WER trước → sau | CER trước → sau | Câu bịa | Tiếng nói không ra chữ | Số bị tách |
|---|---|---|---|---|---|
| phapluat | 8,32% → 7,54% | 6,39% → 5,52% | 1 → 0 | 2,2 → 2,2 s | 0 → 0 |
| coso2 | 12,03% → 6,78% | 10,32% → 5,44% | 1 → 0 | 35,1 → 14,5 s | 5 → 0 |
| thegioi | 3,67% → 3,67% | 1,87% → 1,87% | 0 → 0 | 5,9 → 5,9 s | 9 → 0 |
| babble 10 dB | 16,39% → 12,96% | 13,16% → 10,20% | 1 → 0 | 26,5 → 9,2 s | 0 → 0 |
| babble 5 dB | 41,36% → 30,44% | 34,09% → 25,09% | 6 → 0 | 93,1 → 73,6 s | 0 → 0 |
| hồng 5 dB | 13,79% → 13,79% | 9,54% → 9,54% | 0 → 0 | 2,3 → 2,3 s | 0 → 0 |
| hồng 0 dB | 24,87% → 21,80% | 18,54% → 15,64% | 1 → 0 | 6,4 → 2,2 s | 0 → 0 |
| **gộp 3 bản tin** | **6,59% → 5,24%** | **4,72% → 3,46%** | 2 → 0 | | 14 → 0 |

Sau khi sửa, turbo (CER gộp 3,46%) tốt hơn cả PhoWhisper đã lọc (3,77%), và nhanh hơn khoảng 2,3 lần.

---

## 6. Raw output: so sánh hai model

### 6.1. Output thô của `evaluate.py`

```text
large-v3-turbo   phapluat  raw WER 8.32% CER 6.39% | filtered WER 7.54% CER 5.52% nofill 6.34% termCER 10.55% exact 18/30 spk 96.82% flagged 1 time 70.8s
large-v3-turbo   coso2     raw WER 12.03% CER 10.32% | filtered WER 12.08% CER 10.89% nofill 11.41% termCER 11.73% exact 36/44 spk 82.37% flagged 1 time 55.8s
large-v3-turbo   thegioi   raw WER 3.67% CER 1.87% | filtered WER 3.67% CER 1.87% nofill 3.54% termCER 8.32% exact 91/115 spk 79.00% flagged 0 time 146.5s
phowhisper-large phapluat  raw WER 29.50% CER 29.66% | filtered WER 7.75% CER 5.85% nofill 6.18% termCER 4.77% exact 25/30 spk 96.10% flagged 13 time 159.8s
phowhisper-large coso2     raw WER 24.05% CER 24.34% | filtered WER 2.47% CER 1.76% nofill 2.36% termCER 1.35% exact 41/44 spk 82.60% flagged 16 time 149.9s
phowhisper-large thegioi   raw WER 18.62% CER 15.73% | filtered WER 6.88% CER 3.75% nofill 6.84% termCER 29.89% exact 58/115 spk 77.68% flagged 20 time 327.8s
```

Cách đọc: `raw` là chữ đúng như pipeline xuất ra; `filtered` là sau khi bỏ câu bịa bằng cùng một quy tắc cho cả hai model; `nofill` là WER khi bỏ từ đệm; `termCER` là CER trên thuật ngữ; `exact` là số lần thuật ngữ khớp nguyên cụm; `spk` là tỉ lệ từ gán đúng người nói; `flagged` là số câu bịa; `time` là thời gian cả job.

### 6.2. Các đoạn so sánh song song

Mỗi đoạn có bản gỡ băng, `large-v3-turbo` trước khi sửa, `large-v3-turbo` sau khi sửa, và `PhoWhisper-large` thô, theo cùng một khung thời gian. Chữ của model là `text_raw` lấy nguyên từ `GET /api/jobs/{id}/transcript`. Dòng có `⚠ CÂU BỊA` là câu bị quy tắc lọc ở mục 4 bắt.

#### `phapluat` 00:20.0–00:52.0

PhoWhisper bịa hai câu ở cuối chunk (22,8 s và 49,0 s).

**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):

```text
MC Nam: dài đối với tính mạng sức khỏe và môi trường sống
MC Nữ: và để cùng trao đổi về vấn đề này thì chương trình ngày hôm nay đã mời tới trường quay ông nguyễn hải long đại biểu quốc hội và là ủy viên chuyên trách của ủy ban công tác đại biểu của quốc hội xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ
Ông Nguyễn Hải Long: chào các bạn
MC Nữ: vâng thưa ông từ góc độ lập pháp và thực tiễn vì sao việc nâng cao ý thức tự giác chấp hành pháp luật cũng như là ý thức chúng ta giữ gìn trật tự kỷ cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ
Ông Nguyễn Hải Long: thì theo tôi cái thông điệp quan
```

**large-v3-turbo, trước khi sửa:**

```text
[00:08.2 → 00:22.7] SPEAKER_04 | Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi hướng tới nâng cao ý thức chấp hành pháp luật, thiết lập trật tự, kỳ cương, đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra những hiệu quả nghiêm trọng lâu dài đối với tính mạng, sức khỏe và môi trường sống.
[00:23.6 → 00:32.8] SPEAKER_01 | Và để cùng trao đổi về vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu Quốc hội và là ủy viên chuyên trách của Ủy ban công tác đại biểu của Quốc hội.
[00:33.1 → 00:35.3] SPEAKER_01 | Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
[00:35.5 → 00:36.0] SPEAKER_03 | Chào các bạn.
[00:37.0 → 00:48.9] SPEAKER_01 | Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như là ý thức chúng ta giữ gìn trật tự kỳ cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ?
[00:50.1 → 00:54.0] SPEAKER_03 | Thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật
```

**large-v3-turbo, sau khi sửa:**

```text
[00:08.2 → 00:22.7] SPEAKER_04 | Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi hướng tới nâng cao ý thức chấp hành pháp luật, thiết lập trật tự, kỳ cương, đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra những hiệu quả nghiêm trọng lâu dài đối với tính mạng, sức khỏe và môi trường sống.
[00:23.6 → 00:32.8] SPEAKER_01 | Và để cùng trao đổi về vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu Quốc hội và là ủy viên chuyên trách của Ủy ban công tác đại biểu của Quốc hội.
[00:33.1 → 00:35.3] SPEAKER_01 | Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
[00:35.5 → 00:36.0] SPEAKER_03 | Chào các bạn.
[00:37.0 → 00:48.9] SPEAKER_01 | Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như là ý thức chúng ta giữ gìn trật tự kỳ cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ?
[00:50.1 → 00:54.0] SPEAKER_03 | Thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật
```

**PhoWhisper-large, thô:**

```text
[00:00.4 → 00:22.8] SPEAKER_04 | thưa quý vị tại kỳ họp thứ hai thì quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực của đời sống kinh tế và xã hội và người dân doanh nghiệp trong đó thì có dự án luật xử lý vi phạm hành chính sửa đổi hướng tới nâng cao ý thức chấp hành pháp luật thiết lập trật tự kỷ cương đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra những hiệu quả nghiêm trọng lâu dài đối với tính mạng sức khoẻ và môi trường sống.
[00:22.8 → 00:23.0] SPEAKER_04 | những bức ảnh chụp từ đầu năm một nghìn chín trăm bảy chín trăm năm một nghìn chín năm bảy chín.  ⚠ CÂU BỊA
[00:23.6 → 00:49.0] SPEAKER_01 | và để cùng trao đổi vấn đề này thì chương trình ngày hôm nay đã mời tới trường quay ông nguyễn hải long đại biểu quốc hội và là ủy viên chuyên trách của ủy ban công tác đại biểu của quốc hội xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ chào các bạn vâng à thưa ông từ góc độ lập pháp và thực tiễn vì sao việc nâng cao ý thức tự giác chấp hành pháp luật cũng như là ý thức ờ chúng ta giữ gìn trật tự kỷ cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ.
[00:49.0 → 00:49.1] — | ngoài ra tôi còn tham gia vào các cuộc thi thể thao khác trong năm nay.  ⚠ CÂU BỊA
[00:50.1 → 01:18.8] SPEAKER_03 | thì theo tôi à cái thông điệp quan trọng nhất mà của dự án luật đã mà trông như bạn nói trong dự án vừa rồi là mọi người rất quan tâm ý là vi phạm bị xử lý nghiêm mọi người đều bình đẳng trước pháp luật và quyết định xử phạt phải được thực thi đến cùng đó thì tôi muốn nhấn mạnh những bốn vấn đề thì thứ nhất là mức phạt phải đủ sức răn đe thì trong dự án luật thì cũng đã có nâng mức phạt lên và các bạn thấy là có cái mức phạt phải nâng đến bốn lần à ví dụ như là mức phạt trong lĩnh vực à.
```

#### `phapluat` 01:06.0–01:30.0

turbo bịa "La La School" giữa câu; "phòng cháy chữa cháy"; "răn đe".

**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):

```text
Ông Nguyễn Hải Long: đến cùng thì tôi muốn nhấn mạnh đến bốn vấn đề thứ nhất là mức phạt phải đủ sức răn đe thì trong dự án luật thì cũng đã có nâng mức phạt lên và các bạn thấy là có cái mức phạt phải nâng lên bốn lần ví dụ như là mức phạt trong lĩnh vực về phòng cháy chữa cháy nâng từ năm mươi triệu lên đến hai trăm triệu mà với những mức phạt như vậy thì cũng có doanh nghiệp người ta sẵn sàng vi phạm bởi vì lợi ích nó nhiều hơn
```

**large-v3-turbo, trước khi sửa:**

```text
[01:03.9 → 01:06.4] SPEAKER_03 | Và quyết định xử phạt phải được thực thi đến cùng
[01:07.2 → 01:08.9] SPEAKER_03 | Thì tôi muốn nhấn mạnh những 4 vấn đề
[01:08.9 → 01:11.0] SPEAKER_03 | Thì thứ nhất là mức phạt phải đủ sức gian đe
[01:11.0 → 01:13.5] SPEAKER_03 | Thì trong dự án luật thì cũng đã có nâng mức phạt lên
[01:13.5 → 01:16.4] SPEAKER_03 | Và các bạn thấy là có cái mức phạt phải nâng đến 4 lần
[01:17.0 → 01:18.5] SPEAKER_03 | Ví dụ như là mức phạt trong lĩnh vực
[01:18.5 → 01:19.3] SPEAKER_03 | Hãy subscribe cho kênh La La School Để không bỏ lỡ những video hấp dẫn  ⚠ CÂU BỊA
[01:19.4 → 01:23.8] SPEAKER_03 | Về phòng cháy chứ cháy, nâng từ 50 triệu đến 200 triệu
[01:24.1 → 01:29.3] SPEAKER_03 | Mà với những mức phạt như vậy thì có doanh nghiệp sẵn sàng vi phạm bởi vì lợi ích nó nhiều hơn
[01:29.3 → 01:31.9] SPEAKER_03 | Và thứ hai là phát hiện vi phạm kịp thời
```

**large-v3-turbo, sau khi sửa:**

```text
[01:03.9 → 01:06.4] SPEAKER_03 | Và quyết định xử phạt phải được thực thi đến cùng
[01:07.2 → 01:08.9] SPEAKER_03 | Thì tôi muốn nhấn mạnh những 4 vấn đề
[01:08.9 → 01:11.0] SPEAKER_03 | Thì thứ nhất là mức phạt phải đủ sức gian đe
[01:11.0 → 01:13.5] SPEAKER_03 | Thì trong dự án luật thì cũng đã có nâng mức phạt lên
[01:13.5 → 01:16.4] SPEAKER_03 | Và các bạn thấy là có cái mức phạt phải nâng đến 4 lần
[01:17.0 → 01:18.5] SPEAKER_03 | Ví dụ như là mức phạt trong lĩnh vực
[01:19.4 → 01:23.8] SPEAKER_03 | Về phòng cháy chứ cháy, nâng từ 50 triệu đến 200 triệu
[01:24.1 → 01:29.3] SPEAKER_03 | Mà với những mức phạt như vậy thì có doanh nghiệp sẵn sàng vi phạm bởi vì lợi ích nó nhiều hơn
[01:29.3 → 01:31.9] SPEAKER_03 | Và thứ hai là phát hiện vi phạm kịp thời
```

**PhoWhisper-large, thô:**

```text
[00:50.1 → 01:18.8] SPEAKER_03 | thì theo tôi à cái thông điệp quan trọng nhất mà của dự án luật đã mà trông như bạn nói trong dự án vừa rồi là mọi người rất quan tâm ý là vi phạm bị xử lý nghiêm mọi người đều bình đẳng trước pháp luật và quyết định xử phạt phải được thực thi đến cùng đó thì tôi muốn nhấn mạnh những bốn vấn đề thì thứ nhất là mức phạt phải đủ sức răn đe thì trong dự án luật thì cũng đã có nâng mức phạt lên và các bạn thấy là có cái mức phạt phải nâng đến bốn lần à ví dụ như là mức phạt trong lĩnh vực à.
[01:19.4 → 01:23.8] SPEAKER_03 | ờ về à phòng cháy chữa cháy đã nâng từ năm mươi triệu đến hai trăm triệu.
[01:24.1 → 01:53.5] SPEAKER_03 | mà với những mức phạt như vậy thì có doanh nghiệp mới sẵn sàng vi phạm bởi vì lợi ích nhiều hơn và thứ hai là phát hiện vi phạm kịp thời thì luật cũng đã sử dụng và cho phép dùng các thiết bị về kỹ thuật để phát hiện những vi phạm sớm để xử lý sớm thứ ba là bảo đảm và quyết định xử phạt được thực hiện trên thực tế ví dụ như là bổ sung thêm những hình thức như là niêm phong công trình ngừng cấp điện cấp nước để xử lý nghiêm những cái cơ sở đã cố tình vi phạm khi có quyết định xử lý rồi và thứ tư
```

#### `coso2` 00:55.0–01:52.0

turbo bịa "Ghiền Mì Gõ" rồi bỏ trống 23 s; lời người nhà bệnh nhân (≈100–109 s).

**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):

```text
BTV Nữ 1: quyền xem xét quyết định theo quy định của pháp luật hoàn thành trước ngày một tháng mười một năm hai nghìn không trăm hai mươi sáu giảm tải cho các bệnh viện tuyến trung ương đưa dịch vụ y tế chất lượng cao đến gần hơn với người dân đây là mục tiêu của việc mở rộng các cơ sở khám chữa bệnh và sau một thời gian đi vào hoạt động thì cơ sở hai của các bệnh viện như là bệnh viện nhi trung ương bạch mai và phụ sản trung ương đã phát huy hiệu quả nhiều người bệnh được cấp cứu điều trị chuyên sâu kịp thời ngay gần nơi họ sinh sống giảm thời gian di chuyển và áp lực cho các bệnh viện trung tâm bệnh nhân này vừa được cấp cứu và can thiệp tim mạch chỉ sau vài giờ bệnh nhân đã hoàn toàn tỉnh táo gia đình cho biết may mắn là quãng đường từ nhà đến bệnh viện bạch mai cơ sở ninh bình chỉ vài cây số
Người nhà bệnh nhân: những cái trường hợp cấp cứu mà đi lại gần thì nó sẽ giúp cho bệnh nhân cơ hội để sức khỏe tốt hơn ạ
Bác sĩ Tim mạch: với nhồi máu cơ tim cấp thì thời
```

**large-v3-turbo, trước khi sửa:**

```text
[00:53.6 → 00:57.3] SPEAKER_04 | Báo cáo cấp có thẩm quyền xem xét quyết định theo quy định của pháp luật
[00:57.3 → 00:59.2] SPEAKER_04 | hoàn thành trước ngày 1 tháng 11 năm
[01:01.0 → 01:02.8] SPEAKER_04 | Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn  ⚠ CÂU BỊA
[01:26.0 → 01:32.2] SPEAKER_03 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
[01:32.8 → 01:38.8] SPEAKER_03 | Gia đình cho biết, may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
[01:49.8 → 01:56.2] SPEAKER_07 | Với nhỏ máu cơ tim cấp thì thời gian là vàng, và mỗi tuyến chậm trễ thì vùng cơ tim chiều máu sẽ càng chậm trọng hơn.
```

**large-v3-turbo, sau khi sửa:**

```text
[00:53.6 → 00:57.3] SPEAKER_04 | Báo cáo cấp có thẩm quyền xem xét quyết định theo quy định của pháp luật
[00:57.3 → 00:59.2] SPEAKER_04 | hoàn thành trước ngày 1 tháng 11 năm
[01:01.3 → 01:06.5] SPEAKER_04 | giảm tài cho các bệnh viện tuyến trung ương, đưa dịch vụ y tế chất lượng cao đến gần hơn với người dân.
[01:06.7 → 01:09.2] SPEAKER_04 | Đây là mục tiêu của việc mở rộng các cơ sở khám chữa bệnh.
[01:09.3 → 01:16.1] SPEAKER_04 | Và sau một thời gian đi vào hoạt động, cơ sở 2 của các bệnh viện như Bệnh viện Nhi Trung ương, Bạch Mai và Phụ sản Trung ương đã phát hiện hiệu quả.
[01:16.4 → 01:23.6] SPEAKER_04 | Nhiều người bệnh được cấp cứu, điều trị chuyên sâu kịp thời, ngay gần nơi họ sinh sống, giảm thời gian di chuyển và áp lực cho các bệnh viện trung tâm.
[01:26.0 → 01:32.2] SPEAKER_03 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
[01:32.8 → 01:38.8] SPEAKER_03 | Gia đình cho biết, may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
[01:49.8 → 01:56.2] SPEAKER_07 | Với nhỏ máu cơ tim cấp thì thời gian là vàng, và mỗi tuyến chậm trễ thì vùng cơ tim chiều máu sẽ càng chậm trọng hơn.
```

**PhoWhisper-large, thô:**

```text
[00:30.4 → 00:55.5] SPEAKER_04 | báo cáo cấp có thẩm quyền đối với những nội dung vượt thẩm quyền bộ tài chính chủ trì phối hợp với bộ công thương bộ tư pháp và các cơ quan có liên quan rà soát cơ sở pháp lý thẩm quyền đánh giá đầy đủ tác động và tính khả thi của phương án giảm thuế suất thuế tiêu thụ đặc biệt đối với xăng các loại về không phần trăm từ ngày mùng một tháng mười một năm hai nghìn không trăm hai mươi sáu đến hết ngày ba mốt tháng ba năm hai nghìn không trăm hai bảy báo cáo cấp có thẩm quyền xem
[00:55.5 → 00:59.3] SPEAKER_04 | xét quyết định theo quy định của pháp luật hoàn thành trước ngày mùng một tháng mười một năm
[00:59.3 → 01:23.6] SPEAKER_04 | hai nghìn không trăm hai mươi sáu giảm tải cho các bệnh viện tuyến trung ương đưa dịch vụ y tế chất lượng cao đến gần hơn với người dân đây là mục tiêu của việc mở rộng các cơ sở khám chữa bệnh và sau một thời gian đi vào hoạt động thì cơ sở hai của các bệnh viện như là bệnh viện nhi trung ương bạch mai và phụ sản trung ương đã phát huy hiệu quả nhiều người bệnh được cấp cứu điều trị chuyên sâu kịp thời ngay gần nơi họ sinh sống giảm thời gian di chuyển và áp lực cho các bệnh viện trung tâm.
[01:23.6 → 01:23.8] — | đó là lý do tại sao chúng ta lại gặp nhau trong thời gian tới.  ⚠ CÂU BỊA
[01:26.0 → 01:49.0] SPEAKER_03 | bệnh nhân này vừa được cấp cứu và can thiệp tim mạch chỉ sau vài giờ bệnh nhân đã hoàn toàn tỉnh táo gia đình cho biết may mắn là quãng đường từ nhà đến bệnh viện bạch mai cơ sở ninh bình chỉ vài cây số những trường hợp cấp cứu mà đi lại gần thì nó sẽ giúp cho bệnh nhân có cơ hội để sức khoẻ tốt hơn.
[01:49.0 → 01:49.3] — | học trò tiếp theo trong tiếng nói việt nam tiếp theo đấu tranh tiếp theo đấu tranh việt nam trên toàn thế giới.  ⚠ CÂU BỊA
[01:49.8 → 02:14.7] SPEAKER_07 | với nhồi máu cơ tim cấp thì thời gian là vàng và mỗi tiếng chậm trễ thì cái vùng cơ tim thiếu máu nó sẽ càng trầm trọng hơn bệnh nhân được tiếp cận với tuyến cơ sở y tế mà có thể chụp và can thiệp hành bánh sớm nhất cho bệnh nhân thì cái thời gian là yếu tố quyết định giúp cho bệnh nhân giảm thiểu được cái tỷ lệ tử vong cũng như là các biến chứng của nhồi máu cơ tim sau này để người dân yên tâm các bệnh viện đã chuẩn bị nhân lực từ trước theo mô hình hai cơ sở
```

#### `coso2` 02:15.0–02:46.0

Lời nữ bệnh nhân (≈145–153 s); số "150.000".

**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):

```text
BTV Nữ 1: đội ngũ một chuẩn mực chuyên môn tại bệnh viện phụ sản trung ương cơ sở hai dù mới hoạt động mỗi ngày đã có gần bốn trăm lượt khám và mười lăm ca phẫu thuật
Nữ bệnh nhân: đi ra ngoài hà nội bọn em cũng phải đi từ năm không sáng hay bốn ba mươi sáng lại ra đấy xếp hàng hàng dài mới được đến lượt khám đi đến đây thì được khám luôn
BTV Nữ 1: sau ba tháng hoạt động bệnh viện bạch mai cơ sở ninh bình đã có một trăm năm mươi nghìn lượt khám ngoại trú hơn mười hai nghìn lượt cấp cứu và gần năm nghìn ca phẫu thuật
Đại diện Bệnh viện Bạch Mai: nếu như không có bệnh viện bạch mai cơ sở
```

**large-v3-turbo, trước khi sửa:**

```text
[02:13.1 → 02:16.8] SPEAKER_03 | Theo mô hình, hai cơ sở, một đội ngũ, một chuẩn mực chuyên môn.
[02:17.4 → 02:24.4] SPEAKER_03 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thuật.
[02:33.5 → 02:42.8] SPEAKER_03 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150 .000 lượt khám ngoại trú, hơn 12 .000 lượt cấp cứu và gần 5 .000 ca phẫu thuật.
[02:43.7 → 02:54.6] SPEAKER_09 | Nếu như không có bệnh viện Bệnh Mai cơ sở Ninh Bình thì 150 .000 lượt bệnh nhân khám ngoại chú sẽ phải di chuyển lên Hà Nội để mà khám và điều trị.
```

**large-v3-turbo, sau khi sửa:**

```text
[02:13.1 → 02:16.8] SPEAKER_03 | Theo mô hình, hai cơ sở, một đội ngũ, một chuẩn mực chuyên môn.
[02:17.4 → 02:24.4] SPEAKER_03 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thuật.
[02:33.5 → 02:42.8] SPEAKER_03 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150.000 lượt khám ngoại trú, hơn 12.000 lượt cấp cứu và gần 5.000 ca phẫu thuật.
[02:43.7 → 02:54.6] SPEAKER_09 | Nếu như không có bệnh viện Bệnh Mai cơ sở Ninh Bình thì 150.000 lượt bệnh nhân khám ngoại chú sẽ phải di chuyển lên Hà Nội để mà khám và điều trị.
```

**PhoWhisper-large, thô:**

```text
[02:14.7 → 02:16.9] SPEAKER_03 | một đội ngũ một chuẩn mực chuyên môn.
[02:17.4 → 02:42.9] SPEAKER_03 | tại bệnh viện phụ sản trung ương cơ sở hai dù mới hoạt động mỗi ngày đã có gần bốn trăm lượt khám và mười lăm ca phẫu thuật. thì ra ngoài hà nội bọn em cứ phải đi từ năm giờ sáng hay bốn rưỡi giờ sáng để ra để xếp hàng hàng dài mới được lượt khám đến đây được khám luôn sau ba tháng hoạt động bệnh viện bạch mai cơ sở ninh bình đã có một trăm năm mươi nghìn lượt khám ngoại trú hơn mười hai nghìn lượt cấp cứu và gần năm nghìn ca phẫu thuật.
[02:42.9 → 02:43.1] SPEAKER_03 | nhiều bà mẹ truyền thống đề nghị trước khi tiêu thụ thuốc từ trung quốc trở lại.  ⚠ CÂU BỊA
[02:43.7 → 03:04.7] SPEAKER_09 | nếu như không có bệnh viện bạch mai cơ sở ninh bình thì một trăm năm mươi nghìn lượt bệnh nhân khám gọi trú sẽ sẽ phải di chuyển lên hà nội để mà khám và điều trị hoặc là mười hai nghìn ca cấp cứu vì cũng sẽ phải di chuyển với một quãng đường rất xa và đối mặt với nguy cơ là ùn tắc rồi là giao thông vân vân.
```

#### `thegioi` 01:25.0–02:00.0

Tên riêng nước ngoài: Araghchi, Tehran, Hormuz; PhoWhisper bịa ở 113,7 s. Câu "nguyễn thiện kiêu và nguyễn thiện trang" ở 87,8 s cũng là câu bịa của PhoWhisper, nhưng chỉ 6,4 từ/giây nên quy tắc lọc **không** bắt được. Như vậy bản "đã lọc" của PhoWhisper vẫn còn sót một ít chữ bịa.

**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):

```text
BTV Nam 1: kiểm soát chi tiêu và tạo điều kiện thuận lợi hơn cho doanh nghiệp ngoại trưởng iran abbas araghchi hôm qua tuyên bố tehran sẽ không thay đổi chính sách ngay cả khi mỹ và israel nối lại các cuộc tấn công quân sự ông nhấn mạnh hoạt động hàng hải qua eo biển hormuz sẽ không thể trở lại như trước xung đột tuyên bố được đưa ra sau khi tổng thống mỹ donald trump để ngỏ khả năng tái khởi động chiến dịch quân sự nhằm vào iran ngoại trưởng iran cảnh báo mỹ và israel sẽ không đạt được kết quả khác biệt nếu tiếp tục tấn công tehran ông cũng cho rằng xung đột đã tạo ra những thay đổi căn bản trong khu vực đòi hỏi các bên phải chấp nhận thực tế mới
```

**large-v3-turbo, trước khi sửa:**

```text
[01:25.2 → 01:27.8] SPEAKER_03 | kiểm soát tri tiêu và tạo được kiện thuận lợi hơn cho doanh nghiệp.
[01:31.5 → 01:35.7] SPEAKER_03 | Ngoại trưởng Iran Abbas Araqchi ngày hôm qua tuyên bố Tehran sẽ không thay đổi chính sách
[01:35.7 → 01:38.4] SPEAKER_03 | ngay cả khi Mỹ và Israel đối lại các cuộc tấn công quân sự.
[01:38.7 → 01:42.6] SPEAKER_03 | Ông nhấn mạnh hoạt động hàng hải của biển Hormuz sẽ không thể trở lại như trước xung đột.
[01:42.9 → 01:47.1] SPEAKER_03 | Tuyên bố được đưa ra sau khi Tổng thống Mỹ Donald Trump để ngò khả năng tái khởi động
[01:47.1 → 01:48.4] SPEAKER_03 | chiến dịch quân sự nhằm vào Iran.
[01:48.7 → 01:52.1] SPEAKER_03 | Ngoại trưởng Iran cảnh báo Mỹ và Israel sẽ không đạt được kết quả khác biệt
[01:52.1 → 01:53.7] SPEAKER_03 | nếu tiếp tục tấn công Tehran.
[01:54.1 → 01:59.7] SPEAKER_03 | Ông cũng cho rằng, xung đột đã tạo ra những thay đổi căn bản trong khu vực, đòi hỏi các bên phải chấp nhận thực tế mới,
```

**large-v3-turbo, sau khi sửa:**

```text
[01:25.2 → 01:27.8] SPEAKER_03 | kiểm soát tri tiêu và tạo được kiện thuận lợi hơn cho doanh nghiệp.
[01:31.5 → 01:35.7] SPEAKER_03 | Ngoại trưởng Iran Abbas Araqchi ngày hôm qua tuyên bố Tehran sẽ không thay đổi chính sách
[01:35.7 → 01:38.4] SPEAKER_03 | ngay cả khi Mỹ và Israel đối lại các cuộc tấn công quân sự.
[01:38.7 → 01:42.6] SPEAKER_03 | Ông nhấn mạnh hoạt động hàng hải của biển Hormuz sẽ không thể trở lại như trước xung đột.
[01:42.9 → 01:47.1] SPEAKER_03 | Tuyên bố được đưa ra sau khi Tổng thống Mỹ Donald Trump để ngò khả năng tái khởi động
[01:47.1 → 01:48.4] SPEAKER_03 | chiến dịch quân sự nhằm vào Iran.
[01:48.7 → 01:52.1] SPEAKER_03 | Ngoại trưởng Iran cảnh báo Mỹ và Israel sẽ không đạt được kết quả khác biệt
[01:52.1 → 01:53.7] SPEAKER_03 | nếu tiếp tục tấn công Tehran.
[01:54.1 → 01:59.7] SPEAKER_03 | Ông cũng cho rằng, xung đột đã tạo ra những thay đổi căn bản trong khu vực, đòi hỏi các bên phải chấp nhận thực tế mới,
```

**PhoWhisper-large, thô:**

```text
[01:06.3 → 01:27.8] SPEAKER_03 | người lãnh đạo nền kinh tế lớn nhất mỹ latinh trong định cử tới tổng thống nua đại diện đảng lao động chủ trương duy trì và mở rộng các chương trình an sinh tăng đầu tư công tạo việc làm và nâng cao chất lượng giáo dục y tế trong khi đó nghị sĩ phờ la vi ô bồ sô na rô thuộc đảng tự do nhấn mạnh lập trường cứng rắn với tội phạm tinh giản bộ máy hành chính kiểm soát chỉ tiêu và tạo điều kiện thuận lợi hơn cho doanh nghiệp.
[01:27.8 → 01:28.9] SPEAKER_01 | nguyễn thiện kiêu và nguyễn thiện trang.
[01:31.5 → 01:53.7] SPEAKER_03 | ngoại trưởng i ran áp bát a rắc chi ngày hôm qua tuyên bố tê hê ran sẽ không thay đổi chính sách ngay cả khi mỹ và i sơ ren đối lại các cuộc tấn công quân sự ông nhấn mạnh hoạt động hàng hải ven biển hom bốt sẽ không thể trở lại như chưa xung đột tuyên bố được đưa ra sau khi tổng thống mỹ đô nan trăm để ngỏ khả năng tái khởi động chiến dịch quân sự nhằm vào i ran ngoại trưởng i ran cảnh báo mỹ và i sơ ren sẽ không đạt được kết quả khác biệt nếu tiếp tục tấn công tê hê ran.
[01:53.7 → 01:54.0] SPEAKER_03 | hạn chế gây phân hóa bệnh tâm thần và tâm hồn trong cơ thể trẻ nhỏ có thể dẫn đến đau đớn thận tâm thần và tâm hồn trong cơ thể trẻ nhỏ có thể dẫn đến đau đớn thận tâm.  ⚠ CÂU BỊA
[01:54.1 → 02:12.2] SPEAKER_03 | ông cũng cho rằng xung đột đã tạo ra những thay đổi căn bản trong khu vực do các bên phải chấp nhận thực tế mới trong đó có cơ chế quản lý và các tuyến vận tải qua biển hom bus iran cũng cho biết vẫn sẵn sàng nối lại đàm phán với mỹ thông qua trung gian pakistan dù hai bên chưa tìm được tiếng nói chung về các điều kiện chấm dứt đối độc.
```

#### `thegioi` 12:28.0–12:52.0

"drone" và "kinh tế tầm thấp".

**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):

```text
BTV Nữ 1: hạn chế giờ bay do quy định về tiếng ồn trong chiến lược phát triển kinh tế tầm thấp trung quốc đang mở rộng ứng dụng công nghệ bay vào nhiều lĩnh vực từ nông nghiệp logistics đến vận tải với sự hỗ trợ của trí tuệ nhân tạo và các công nghệ kết nối drone không chỉ là công cụ hỗ trợ sản xuất mà còn mở ra những mô hình kinh doanh mới vậy thiết bị bay không người lái thì đang tạo ra những giá trị kinh
```

**large-v3-turbo, trước khi sửa:**

```text
[12:24.1 → 12:29.8] SPEAKER_10 | Sân bay được kỳ vọng giàn tải cho sân bay hiện hữu của Sydney vốn bị hạn chế dơ bay do quy định về tính ồn.
[12:33.7 → 12:38.3] SPEAKER_10 | Trong chiến lược phát triển kinh tế tầm thấp, Trung Quốc đang mở rộng ứng dụng công nghệ bay vào nhiều lĩnh vực,
[12:38.4 → 12:40.7] SPEAKER_10 | từ nông nghiệp, logistic đến vận tải.
[12:40.9 → 12:44.0] SPEAKER_10 | Với sự hỗ trợ của trí tuệ nhân tạo và các công nghệ kết nối,
[12:44.2 → 12:48.2] SPEAKER_10 | drone không chỉ là công cụ hỗ trợ sản xuất mà còn mở ra những mô hình kinh doanh mới.
[12:48.7 → 12:52.6] SPEAKER_10 | Vậy thiết bị bay không người lái thì đang tạo ra những giá trị kinh tế như thế nào?
```

**large-v3-turbo, sau khi sửa:**

```text
[12:24.1 → 12:29.8] SPEAKER_10 | Sân bay được kỳ vọng giàn tải cho sân bay hiện hữu của Sydney vốn bị hạn chế dơ bay do quy định về tính ồn.
[12:33.7 → 12:38.3] SPEAKER_10 | Trong chiến lược phát triển kinh tế tầm thấp, Trung Quốc đang mở rộng ứng dụng công nghệ bay vào nhiều lĩnh vực,
[12:38.4 → 12:40.7] SPEAKER_10 | từ nông nghiệp, logistic đến vận tải.
[12:40.9 → 12:44.0] SPEAKER_10 | Với sự hỗ trợ của trí tuệ nhân tạo và các công nghệ kết nối,
[12:44.2 → 12:48.2] SPEAKER_10 | drone không chỉ là công cụ hỗ trợ sản xuất mà còn mở ra những mô hình kinh doanh mới.
[12:48.7 → 12:52.6] SPEAKER_10 | Vậy thiết bị bay không người lái thì đang tạo ra những giá trị kinh tế như thế nào?
```

**PhoWhisper-large, thô:**

```text
[12:06.7 → 12:29.8] SPEAKER_10 | sân bay quốc tế mới ở phía tây sydney australia ngày hôm nay chính thức đón những hành khách đầu tiên cách trung tâm sydney khoảng sáu mươi ki lô mét sân bay mới có thể hoạt động hai tư trên hai tư giờ ở chuyến bay chở khách đầu tiên do hãng jetstar khai thác kết nối sydney với golf coast được xây dựng trên diện tích một nghìn bảy trăm tám mươi héc ta sân bay được kỳ vọng giàn tải cho sân bay hiện hữu của sydney vốn bị hạn chế giờ bay do quy định về tiếng ồn.
[12:29.8 → 12:30.3] SPEAKER_10 | nhiều bà mẹ truyền thống thiếu thốn trách nhiệm trước khi thi đấu trong giai đoạn vừa kết thúc.  ⚠ CÂU BỊA
[12:33.7 → 12:54.5] SPEAKER_10 | trong chiến lược phát triển kinh tế tầm thấp trung quốc đang mở rộng ứng dụng công nghệ bay vào nhiều lĩnh vực từ nông nghiệp lô xi tích đến vận tải với sự hỗ trợ của trí tuệ nhân tạo và các công nghệ kết nối rôn không chỉ là công cụ hỗ trợ sản xuất mà còn mở ra những mô hình kinh doanh mới vậy thiết bị bay không người lái thì đang tạo ra những giá trị kinh tế như thế nào mời quý vị cùng theo dõi phóng sự ngay sau đây.
```

---

## 7. Raw output: trước và sau khi sửa

### 7.1. Output thô của `compare_fix.py`

```text
bài           WER trước  WER sau  CER trước  CER sau bịa trước bịa sau không chữ trước    sau số bị tách      thời gian
phapluat          8.32%    7.54%      6.39%    5.52%         1       0            2.2s   2.2s    0 → 0   70.8→74.5s
coso2            12.03%    6.78%     10.32%    5.44%         1       0           35.1s  14.5s    5 → 0   55.8→57.3s
thegioi           3.67%    3.67%      1.87%    1.87%         0       0            5.9s   5.9s    9 → 0   146.5→139.9s
babble_10db      16.39%   12.96%     13.16%   10.20%         1       0           26.5s   9.2s    0 → 0   55.4→64.4s
babble_5db       41.36%   30.44%     34.09%   25.09%         6       0           93.1s  73.6s    0 → 0   53.2→64.4s
pink_5db         13.79%   13.79%      9.54%    9.54%         0       0            2.3s   2.3s    0 → 0   56.2→62.4s
pink_0db         24.87%   21.80%     18.54%   15.64%         1       0            6.4s   2.2s    0 → 0   52.3→61.4s
```

Cột "không chữ" là số giây tiếng nói không ra chữ. Cột "số bị tách" là số câu có dạng `150 .000`, `1 -11`, `0 %`.

### 7.2. Test của bộ lọc

```text
tests/test_upload_job.py::HallucinationFilterTests::test_call_to_action_with_long_tail_is_dropped PASSED [ 16%]
tests/test_upload_job.py::HallucinationFilterTests::test_impossible_speech_rate_is_dropped PASSED [ 33%]
tests/test_upload_job.py::HallucinationFilterTests::test_known_phrases_are_dropped PASSED [ 50%]
tests/test_upload_job.py::HallucinationFilterTests::test_prompt_is_trimmed PASSED [ 66%]
tests/test_upload_job.py::HallucinationFilterTests::test_real_sentences_are_kept PASSED [ 83%]
tests/test_upload_job.py::HallucinationFilterTests::test_word_pieces_without_space_join_previous_word PASSED [100%]
======================= 6 passed, 9 deselected in 0.71s =======================
..............................................                           [100%]
46 passed in 7.50s
```

### 7.3. Đoạn trước và sau trên bản nhiễu

#### `babble_10db` 00:34.0–01:00.0 (bài phapluat trộn tiếng người nói)

**large-v3-turbo, trước khi sửa:**

```text
[00:37.5 → 00:39.1] SPEAKER_01 | Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn  ⚠ CÂU BỊA
[00:58.5 → 01:06.3] SPEAKER_03 | rất quan tâm là vi phạm bị xử lý nghiêm, mọi người đều bình đẳng trước pháp luật và quyết định xử phạt phải được thực thi đến cùng.
```

**large-v3-turbo, sau khi sửa:**

```text
[00:37.5 → 00:42.6] SPEAKER_01 | từ gấp độ lầm pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật
[00:42.6 → 00:49.0] SPEAKER_01 | cũng như là ý thức chúng ta giữ gìn trật tự thủy cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ?
[00:50.2 → 00:54.0] SPEAKER_03 | Thì theo tôi, cái thông điệp quan trọng nhất mà của dự án luật,
[00:55.9 → 00:58.5] SPEAKER_03 | chẳng như bạn nói trong dự án vừa rồi là mọi người
[00:58.5 → 01:06.3] SPEAKER_03 | rất quan tâm là vi phạm bị xử lý nghiêm, mọi người đều bình đẳng trước pháp luật và quyết định xử phạt phải được thực thi đến cùng.
```

#### `babble_5db` 03:22.0–03:54.0 (bài phapluat trộn tiếng người nói)

**large-v3-turbo, trước khi sửa:**

```text
[03:22.2 → 03:23.5] SPEAKER_07 | Thì dự thảo thì
[03:26.2 → 03:31.5] SPEAKER_07 | Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn  ⚠ CÂU BỊA
[03:52.6 → 03:53.4] SPEAKER_07 | trả giá thay cho họ
```

**large-v3-turbo, sau khi sửa:**

```text
[03:22.2 → 03:23.5] SPEAKER_07 | Thì dự thảo thì
[03:26.3 → 03:34.4] SPEAKER_07 | Trước khi hậu quả trả ra, không phải đợi đến khi mà có tình trạng là ô nhiễm môi trường hay là cháy nổ, rồi khi đấy chúng ta mới xử phạt.
[03:34.8 → 03:41.1] SPEAKER_07 | Thứ hai là người vi phạm khắp cổ vụ quả, không để thu lợi người cho mình, nhưng mà cái thiệt hại để cho xã hội của nhà nước.
[03:42.0 → 03:44.7] SPEAKER_07 | Thứ ba là phải công khai, không tin về vi phạm.
[03:45.2 → 03:52.5] SPEAKER_07 | Và một chế tài tốt không chỉ khiến người vi phạm trả giá, mà còn phải quan trọng hơn là ngăn chặn những người vô tội phải
[03:52.6 → 03:53.4] SPEAKER_07 | trả giá thay cho họ
```

---

## 8. Raw output: chia chunk và nhiễu

### 8.1. VAD và chunk của ba bài

```text
phapluat regions 49 chunks 21 speech 456.7 of 473.8 s
coso2 regions 64 chunks 20 speech 471.1 of 509.1 s
thegioi regions 91 chunks 54 speech 1124.0 of 1245.5 s
phapluat chunks 21 len min 4.6 median 24.1 max 30.0 | <5s: 1 <10s: 1 | forced cuts 1 | noise floor -33.0 dBFS
coso2 chunks 20 len min 12.2 median 25.1 max 30.0 | <5s: 0 <10s: 0 | forced cuts 2 | noise floor -44.4 dBFS
thegioi chunks 54 len min 4.8 median 24.2 max 30.0 | <5s: 1 <10s: 9 | forced cuts 5 | noise floor -22.9 dBFS
```

### 8.2. Lỗi theo khoảng cách tới mép chunk (`chunk_errors.py`)

```text
large-v3-turbo   phapluat ≤1 s: 169 từ, lỗi 7.1%  1–3 s: 362 từ, lỗi 8.6%  >3 s: 1391 từ, lỗi 7.3%
large-v3-turbo   coso2    ≤1 s: 178 từ, lỗi 15.7%  1–3 s: 313 từ, lỗi 8.9%  >3 s: 1413 từ, lỗi 12.3%
      mất (59.1, 86.2, 112, 'trong chunk', 'hai nghìn không trăm hai mươi sáu giảm tải cho các bệnh')
      mất (98.6, 110.0, 25, 'trong chunk', 'những cái trường hợp cấp cứu mà đi lại gần thì nó')
      mất (144.4, 153.7, 38, 'trong chunk', 'đi ra ngoài hà nội bọn em cũng phải đi từ năm')
large-v3-turbo   thegioi  ≤1 s: 394 từ, lỗi 5.3%  1–3 s: 914 từ, lỗi 3.3%  >3 s: 3374 từ, lỗi 3.6%
phowhisper-large phapluat ≤1 s: 168 từ, lỗi 7.1%  1–3 s: 365 từ, lỗi 7.9%  >3 s: 1389 từ, lỗi 7.8%
phowhisper-large coso2    ≤1 s: 167 từ, lỗi 2.4%  1–3 s: 311 từ, lỗi 0.6%  >3 s: 1426 từ, lỗi 2.9%
phowhisper-large thegioi  ≤1 s: 403 từ, lỗi 15.9%  1–3 s: 906 từ, lỗi 4.9%  >3 s: 3373 từ, lỗi 6.3%
      mất (643.7, 645.5, 19, 'trong chunk', 'rõ rệt năm hai nghìn không trăm hai mươi lăm tổng số')
```

Dòng `mất` là đoạn từ 5 từ trở lên bị mất liền nhau: (từ giây, đến giây, số từ, nằm trong chunk hay ngoài VAD, đầu đoạn bị mất). Cả 4 đoạn đều nằm `trong chunk`, nghĩa là VAD đã đưa vào nhưng Whisper không ra chữ.

### 8.3. Chạy lại riêng 3 chunk bị mất chữ (`retry_chunks.py`)

`nsp` là `no_speech_prob`, `lp` là `avg_logprob` của câu.

```text

######## chunk 58.73–83.88
--- hiện tại: 1 câu, có chữ 1.8/25.1s, 0.7s
      61.1-  62.8 nsp=0.00 lp=-0.12 | Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
--- tắt ngưỡng no_speech/logprob: 1 câu, có chữ 1.8/25.1s, 0.4s
      61.1-  62.8 nsp=0.00 lp=-0.12 | Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
--- temperature dự phòng: 1 câu, có chữ 1.8/25.1s, 0.4s
      61.1-  62.8 nsp=0.00 lp=-0.12 | Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
--- hallucination_silence 2s: 4 câu, có chữ 21.6/25.1s, 1.6s
      61.3-  66.5 nsp=0.00 lp=-0.06 | Giảm tài cho các bệnh viện tuyến trung ương, đưa dịch vụ y tế chất lượng cao đến gần hơn với người dân.
      66.7-  69.2 nsp=0.00 lp=-0.06 | Đây là mục tiêu của việc mở rộng các cơ sở khám chữa bệnh.
      69.3-  76.1 nsp=0.00 lp=-0.06 | Sau một thời gian đi vào hoạt động, cơ sở 2 của các bệnh viện như Bệnh viện Nhi Trung ương, Bạch Mai và Phụ sả
      76.4-  83.6 nsp=0.00 lp=-0.06 | Nhiều người bệnh được cấp cứu, điều trị chuyên sâu kịp thời, ngay gần nơi họ sinh sống, giảm thời gian di chuy
--- từng vùng VAD riêng (2 vùng):
      58.7-  60.8 | Hãy đăng ký kênh để ủng hộ kênh của mình nhé!
      61.2-  83.9 | giảm tài cho các bệnh viện tuyến trung ương, đưa dịch vụ y tế chất lượng cao đến gần hơn với người dân. Đây là mục tiêu 

######## chunk 86.01–109.35
--- hiện tại: 2 câu, có chữ 12.2/23.3s, 0.9s
      86.0-  92.2 nsp=0.00 lp=-0.06 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
      92.8-  98.8 nsp=0.00 lp=-0.06 | Gia đình cho biết, may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
--- tắt ngưỡng no_speech/logprob: 2 câu, có chữ 12.2/23.3s, 0.9s
      86.0-  92.2 nsp=0.00 lp=-0.06 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
      92.8-  98.8 nsp=0.00 lp=-0.06 | Gia đình cho biết, may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
--- temperature dự phòng: 2 câu, có chữ 12.2/23.3s, 0.9s
      86.0-  92.2 nsp=0.00 lp=-0.06 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
      92.8-  98.8 nsp=0.00 lp=-0.06 | Gia đình cho biết, may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
--- hallucination_silence 2s: 2 câu, có chữ 12.2/23.3s, 0.9s
      86.0-  92.2 nsp=0.00 lp=-0.06 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
      92.8-  98.8 nsp=0.00 lp=-0.06 | Gia đình cho biết, may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
--- từng vùng VAD riêng (5 vùng):
      86.0-  92.7 | Bệnh nhân này vừa được cấp cứu và can thiệp tim mạch. Chỉ sau vài giờ, bệnh nhân đã hoàn toàn tỉnh táo.
      92.8-  99.2 | Gia đình cho biết may mắn là quãng đường từ nhà đến Bệnh viện Bạch Mai cơ sở Ninh Bình chỉ vài cây số.
     100.2- 104.0 | những trường hợp cấp cứu mà đi lại gần thì nó sẽ
     104.4- 107.4 | giúp cho bệnh nhân có cơ hội để...
     107.9- 109.3 | Sức khỏe tốt hơn

######## chunk 137.4–163.08
--- hiện tại: 2 câu, có chữ 16.4/25.7s, 0.8s
     137.4- 144.4 nsp=0.00 lp=-0.06 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thu
     153.5- 162.8 nsp=0.00 lp=-0.06 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150.000 lượt khám ngoại trú, hơn 12.000 lượt c
--- tắt ngưỡng no_speech/logprob: 2 câu, có chữ 16.4/25.7s, 0.8s
     137.4- 144.4 nsp=0.00 lp=-0.06 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thu
     153.5- 162.8 nsp=0.00 lp=-0.06 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150.000 lượt khám ngoại trú, hơn 12.000 lượt c
--- temperature dự phòng: 2 câu, có chữ 16.4/25.7s, 0.8s
     137.4- 144.4 nsp=0.00 lp=-0.06 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thu
     153.5- 162.8 nsp=0.00 lp=-0.06 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150.000 lượt khám ngoại trú, hơn 12.000 lượt c
--- hallucination_silence 2s: 2 câu, có chữ 16.4/25.7s, 0.8s
     137.4- 144.4 nsp=0.00 lp=-0.06 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thu
     153.5- 162.8 nsp=0.00 lp=-0.06 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150.000 lượt khám ngoại trú, hơn 12.000 lượt c
--- từng vùng VAD riêng (3 vùng):
     137.4- 144.7 | Tại Bệnh viện Phụ sản Trung ương cơ sở 2, dù mới hoạt động, mỗi ngày đã có gần 400 lượt khám và 15 ca phẫu thuật.
     145.0- 152.7 | Đi ra ngoài Hà Nội bọn em có phải đi từ 5h sáng hay 4h30 giờ sáng hay ra để xếp hàng hàng dài để được lượt khám, delay đ
     153.6- 163.1 | Sau 3 tháng hoạt động, Bệnh viện Bạch Mai cơ sở Ninh Bình đã có 150.000 lượt khám ngoại chú, hơn 12.000 lượt cấp cứu và 
```

### 8.4. Bản nhiễu qua pipeline, trước khi sửa (`score_noise.py`)

```text
bản              WER     CER  WERlọc  CERlọc  thay/mất/chèn câu bịa  VAD bắt VAD thừa tiếng không chữ  người gán đúng thời gian
sạch           8.32%   6.39%   7.54%   5.52%   57/  69/  19       1   100.0%     0.0s      2.2s (0.5%)      6    96.8% 70.8
      bịa: Hãy subscribe cho kênh La La School Để không bỏ lỡ những video hấp dẫn
pink_20db      9.05%   6.57%   8.79%   6.36%   74/  71/  24       1    98.7%     0.8s      2.2s (0.5%)      6    96.8% 72.3
      bịa: Đăng ký kênh để nhận thông tin.
pink_10db      9.83%   7.19%   9.83%   7.19%   92/  68/  29       0    98.4%     1.5s      2.2s (0.5%)      6    96.8% 58.3
pink_5db      13.79%   9.54%  13.79%   9.54%  153/  83/  29       0    98.5%     2.9s      2.3s (0.5%)      6    97.6% 56.2
pink_0db      24.87%  18.54%  24.92%  19.05%  264/ 190/  25       1    98.8%     4.5s     16.2s (3.6%)      5    89.2% 52.3
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
babble_20db   12.70%  10.41%  12.70%  10.41%   68/ 158/  18       0    98.8%     3.4s     19.9s (4.4%)      5    97.8% 54.3
babble_10db   16.39%  13.16%  16.39%  13.74%   90/ 205/  20       1    99.8%    13.7s     29.1s (6.4%)      6    98.5% 55.4
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
babble_5db    41.36%  34.09%  41.62%  36.79%  134/ 648/  18       6   100.0%    17.0s    138.2s (30.3%)      8    94.4% 53.2
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
      bịa: Các bạn hãy đăng ký kênh để ủng hộ kênh của chúng mình nhé.
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
babble_0db    89.91%  80.65%  91.31%  87.96%   96/1654/   5      16   100.0%    17.1s    372.9s (81.6%)      6    61.9% 40.3
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
      bịa: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
```

Cột `VAD bắt` là tỉ lệ tiếng nói của bản sạch mà VAD trên bản nhiễu còn bắt được. `VAD thừa` là số giây VAD coi là tiếng nói nhưng bản sạch không có. `người` là số người nói pyannote tìm ra.

### 8.5. Thử các cách sửa (`score_exp.py`)

```text
babble_10db  A_hien_tai         WER  16.39% CER  13.16% | lọc: WER  16.39% S/D/I 105/190/20 bịa 1 chunks 20 23s
babble_10db  B_halluc_silence   WER  12.96% CER  10.20% | lọc: WER  12.96% S/D/I 96/133/20 bịa 0 chunks 20 24s
babble_10db  C_chunk15          WER  15.30% CER  11.53% | lọc: WER  15.40% S/D/I 119/155/20 bịa 2 chunks 37 24s
babble_10db  D_chunk15_halluc   WER  15.30% CER  11.53% | lọc: WER  15.40% S/D/I 119/155/20 bịa 2 chunks 37 25s
babble_10db  E_afftdn           WER  14.72% CER  11.37% | lọc: WER  14.78% S/D/I 111/153/19 bịa 1 chunks 21 20s
babble_5db   A_hien_tai         WER  41.36% CER  34.09% | lọc: WER  41.62% S/D/I 216/560/19 bịa 6 chunks 17 18s
babble_5db   B_halluc_silence   WER  30.28% CER  24.09% | lọc: WER  30.44% S/D/I 202/359/21 bịa 3 chunks 17 23s
babble_5db   C_chunk15          WER  48.02% CER  39.35% | lọc: WER  48.49% S/D/I 279/638/6 bịa 13 chunks 34 21s
babble_5db   D_chunk15_halluc   WER  48.02% CER  39.35% | lọc: WER  48.49% S/D/I 279/638/6 bịa 13 chunks 34 19s
babble_5db   E_afftdn           WER  41.78% CER  35.05% | lọc: WER  42.09% S/D/I 253/532/18 bịa 7 chunks 18 23s
coso2        A_hien_tai         WER  12.03% CER  10.32% | lọc: WER  12.08% S/D/I 47/182/0 bịa 1 chunks 20 22s
coso2        B_halluc_silence   WER   6.78% CER   5.44% | lọc: WER   6.78% S/D/I 35/94/0 bịa 0 chunks 20 22s
coso2        C_chunk15          WER  13.13% CER  10.40% | lọc: WER  13.29% S/D/I 100/150/0 bịa 4 chunks 43 24s
coso2        D_chunk15_halluc   WER   5.88% CER   4.30% | lọc: WER   5.88% S/D/I 62/50/0 bịa 1 chunks 43 29s
coso2        E_afftdn           WER  10.87% CER   9.21% | lọc: WER  10.92% S/D/I 48/159/0 bịa 1 chunks 20 21s
phapluat     A_hien_tai         WER   8.32% CER   6.39% | lọc: WER   7.54% S/D/I 57/69/34 bịa 1 chunks 21 23s
phapluat     B_halluc_silence   WER   8.32% CER   6.39% | lọc: WER   7.54% S/D/I 57/69/34 bịa 1 chunks 21 23s
phapluat     E_afftdn           WER   7.54% CER   5.51% | lọc: WER   7.54% S/D/I 56/78/11 bịa 0 chunks 21 22s
pink_0db     A_hien_tai         WER  24.87% CER  18.54% | lọc: WER  24.92% S/D/I 278/175/25 bịa 1 chunks 20 21s
pink_0db     B_halluc_silence   WER  21.80% CER  15.64% | lọc: WER  21.80% S/D/I 270/124/25 bịa 0 chunks 20 22s
pink_0db     C_chunk15          WER  39.33% CER  31.63% | lọc: WER  39.75% S/D/I 307/424/25 bịa 6 chunks 38 24s
pink_0db     D_chunk15_halluc   WER  35.28% CER  27.67% | lọc: WER  35.64% S/D/I 301/352/25 bịa 5 chunks 38 25s
pink_0db     E_afftdn           WER  19.93% CER  13.71% | lọc: WER  19.93% S/D/I 253/101/29 bịa 0 chunks 20 23s
pink_5db     A_hien_tai         WER  13.79% CER   9.54% | lọc: WER  13.79% S/D/I 153/83/29 bịa 0 chunks 20 22s
pink_5db     B_halluc_silence   WER  13.79% CER   9.54% | lọc: WER  13.79% S/D/I 153/83/29 bịa 0 chunks 20 22s
pink_5db     C_chunk15          WER  17.79% CER  13.28% | lọc: WER  17.85% S/D/I 151/165/26 bịa 1 chunks 39 26s
pink_5db     D_chunk15_halluc   WER  17.79% CER  13.28% | lọc: WER  17.85% S/D/I 151/165/26 bịa 1 chunks 39 24s
pink_5db     E_afftdn           WER  14.10% CER  10.50% | lọc: WER  13.58% S/D/I 145/82/44 bịa 2 chunks 19 23s
thegioi      A_hien_tai         WER   3.67% CER   1.87% | lọc: WER   3.67% S/D/I 141/20/11 bịa 0 chunks 54 58s
thegioi      B_halluc_silence   WER   3.67% CER   1.87% | lọc: WER   3.67% S/D/I 141/20/11 bịa 0 chunks 54 56s
thegioi      E_afftdn           WER   4.04% CER   2.30% | lọc: WER   4.04% S/D/I 138/41/10 bịa 0 chunks 54 58s
```

---

## 9. Raw output: log chạy job

Mỗi log là output nguyên văn của `run_job.py`:
- thời điểm đổi trạng thái;
- thời gian cả job;
- thông tin job;
- số câu và số người nói;
- thời lượng nói của từng nhãn;
- 12 câu đầu.

### So sánh hai model

<details>
<summary><code>phapluat</code> — large-v3-turbo</summary>

```text
upload 201 0.1 s
job 95bab45f-bc17-4b87-8f02-6a1409cd2c9e
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    9.1s] ('transcribing', None, None)
[   35.9s] ('diarizing', None, None)
[   70.8s] ('ready', None, None)
elapsed 70.8 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 95 speakers ['SPEAKER_04', 'SPEAKER_01', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_00']
  SPEAKER_03: 282s
  SPEAKER_01: 59s
  SPEAKER_04: 34s
  SPEAKER_02: 24s
  SPEAKER_00: 18s
  SPEAKER_05: 17s
words 1862 segments with >1 word speaker 46
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi hướng tới nâng cao ý thức chấp hành pháp luật, thiết l
     23.6 SPEAKER_01: Và để cùng trao đổi về vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biể
     33.1 SPEAKER_01: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.5 SPEAKER_03: Chào các bạn.
     37.0 SPEAKER_01: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     50.1 SPEAKER_03: Thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật
     56.0 SPEAKER_03: Trong như bạn nói trong dự án vừa rồi là mọi người rất quan tâm
     59.7 SPEAKER_03: Là vi phạm phải bị xử lý nghiêm
     62.2 SPEAKER_03: Mọi người đều bình đẳng trước pháp luật
     63.9 SPEAKER_03: Và quyết định xử phạt phải được thực thi đến cùng
     67.2 SPEAKER_03: Thì tôi muốn nhấn mạnh những 4 vấn đề
```

</details>

<details>
<summary><code>coso2</code> — large-v3-turbo</summary>

```text
upload 201 0.1 s
job bf03529e-c881-47e1-b3f9-5a10893becf0
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    8.8s] ('transcribing', None, None)
[   29.9s] ('diarizing', None, None)
[   55.8s] ('ready', None, None)
elapsed 55.8 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 509136, "diarization_device": "cuda"}
pass 2 segments 69 speakers ['SPEAKER_04', 'SPEAKER_03', 'SPEAKER_07', 'SPEAKER_09', 'SPEAKER_06', 'SPEAKER_01', 'SPEAKER_00', 'SPEAKER_02', 'SPEAKER_08']
  SPEAKER_02: 90s
  SPEAKER_01: 80s
  SPEAKER_03: 62s
  SPEAKER_04: 59s
  SPEAKER_08: 52s
  SPEAKER_00: 24s
  SPEAKER_09: 21s
  SPEAKER_07: 18s
  SPEAKER_06: 12s
words 1649 segments with >1 word speaker 32
      0.7 SPEAKER_04: Kết luận cuộc họp về các kịch bản điều hành giá xăng dầu và điện vào hôm nay,
      4.8 SPEAKER_04: Phó Thủ tướng Chính phủ Nguyễn Văn Thắng yêu cầu EVN ra soát tính toán có phương án giảm giá bán lẻ điện bình 
     10.5 SPEAKER_04: áp dụng từ ngày 1 tháng 11 năm 2026 đến hết ngày 31 tháng 3 năm 2027 theo đúng quy định của pháp luật.
     18.6 SPEAKER_04: Báo cáo Bộ Công Thương kiểm tra ra soát và cho ý kiến.
     21.6 SPEAKER_04: Bộ Công Thương chủ trì có ý kiến đối với phương án giá bán lẻ điện bình quân của EVN
     25.9 SPEAKER_04: để đáp ứng tiến độ giảm giá điện từ ngày 1 tháng 11 năm 2026.
     30.5 SPEAKER_04: Báo cáo cấp có thẩm quyền đối với những nội dung vượt thẩm quyền
     33.8 SPEAKER_04: Bộ Tài chính chủ trì phối hợp với Bộ Công thương, Bộ Tư pháp và các cơ quan có liên quan
     38.1 SPEAKER_04: ra soát cơ sở pháp lý thẩm quyền, đánh giá đầy đủ tác động và tính khả thi
     42.8 SPEAKER_04: của phương án giảm thuế xuất, thuế tiêu tụ đặc biệt đối với xăng các loại về 0 %
     48.1 SPEAKER_04: từ ngày 1 -11 -2026 đến hết ngày 31 -3 -2027
     53.6 SPEAKER_04: Báo cáo cấp có thẩm quyền xem xét quyết định theo quy định của pháp luật
```

</details>

<details>
<summary><code>thegioi</code> — large-v3-turbo</summary>

```text
upload 201 0.2 s
job dd6f80c9-44f2-497f-af5c-cfd4e51be397
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[   17.8s] ('transcribing', None, None)
[   82.7s] ('diarizing', None, None)
[  146.5s] ('ready', None, None)
elapsed 146.5 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 1245504, "diarization_device": "cuda"}
pass 2 segments 209 speakers ['SPEAKER_03', 'SPEAKER_09', 'SPEAKER_10', 'SPEAKER_06', 'SPEAKER_08', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_04', 'SPEAKER_11', 'SPEAKER_00', 'SPEAKER_07']
  SPEAKER_03: 250s
  SPEAKER_10: 190s
  SPEAKER_05: 155s
  SPEAKER_09: 143s
  SPEAKER_08: 114s
  SPEAKER_11: 70s
  SPEAKER_04: 43s
  SPEAKER_06: 27s
  SPEAKER_02: 18s
  SPEAKER_07: 16s
  SPEAKER_00: 14s
words 4555 segments with >1 word speaker 55
      4.4 SPEAKER_03: Chính phủ Trung Quốc cam kết tăng hỗ trợ các gia đình xây dựng xã hội thân thiện với sinh đẻ
      8.6 SPEAKER_03: nhằm ứng phó tư giảm dân số và lực lượng lao động.
     21.0 SPEAKER_09: Xung đột tại Trung Đông đang làm thay đổi bản đồ cung ứng khí tự nhiên hóa lỏng LNG trên toàn cầu.
     28.5 SPEAKER_10: Trung Quốc tăng tốc khai thác thị trường kinh tế tầm thấp, cơ hội tỷ đô đi cùng thách thức về an toàn và thươn
     36.9 SPEAKER_06: Cuộc bỏ phiếu trong vòng 2 cuộc bầu cử Tổng thống Brazil đã kết thúc cách đây hơn 1 giờ đồng hồ.
     41.8 SPEAKER_06: Thời gian bỏ phiếu đã được kéo dài thêm 2 tiếng, theo đề nghị của cả 2 bên.
     46.0 SPEAKER_03: Tổng thống Lula de Silva lo ngại các sự cố ảnh hưởng đến mạng lưới xe buýt công cộng
     50.8 SPEAKER_03: tại 2 thành phố lớn là Sao Paulo và Salvador.
     53.5 SPEAKER_03: Trong khi đó, ứng cử viên đối lập Flavio Bolsonaro lại bày tỏ lo ngại,
     57.2 SPEAKER_03: thực tế xấu ảnh hưởng đến cử tri định bỏ phiếu tại Sao Paulo và bang Santa Catarina.
     62.3 SPEAKER_03: Gần 160 triệu cử tri Brazil đủ điều kiện tham gia bỏ phiếu để lựa chọn
     66.5 SPEAKER_03: lãnh đạo, nền kinh tế lớn nhất Mỹ Latin trong địa quy tế.
```

</details>

<details>
<summary><code>phapluat</code> — PhoWhisper-large</summary>

```text
upload 201 0.1 s
job 69a97768-ebca-4b42-9eff-663bcf07ae54
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[   10.8s] ('transcribing', None, None)
[  124.9s] ('diarizing', None, None)
[  159.8s] ('ready', None, None)
elapsed 159.8 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 36 speakers ['SPEAKER_04', 'SPEAKER_01', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_00']
  SPEAKER_03: 316s
  SPEAKER_01: 57s
  SPEAKER_02: 24s
  SPEAKER_04: 24s
  SPEAKER_05: 23s
  SPEAKER_00: 12s
  None: 1s
words 2348 segments with >1 word speaker 25
      0.4 SPEAKER_04: thưa quý vị tại kỳ họp thứ hai thì quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh 
     22.8 SPEAKER_04: những bức ảnh chụp từ đầu năm một nghìn chín trăm bảy chín trăm năm một nghìn chín năm bảy chín.
     23.6 SPEAKER_01: và để cùng trao đổi vấn đề này thì chương trình ngày hôm nay đã mời tới trường quay ông nguyễn hải long đại bi
     49.0 None: ngoài ra tôi còn tham gia vào các cuộc thi thể thao khác trong năm nay.
     50.1 SPEAKER_03: thì theo tôi à cái thông điệp quan trọng nhất mà của dự án luật đã mà trông như bạn nói trong dự án vừa rồi là
     79.4 SPEAKER_03: ờ về à phòng cháy chữa cháy đã nâng từ năm mươi triệu đến hai trăm triệu.
     84.1 SPEAKER_03: mà với những mức phạt như vậy thì có doanh nghiệp mới sẵn sàng vi phạm bởi vì lợi ích nhiều hơn và thứ hai là 
    113.5 SPEAKER_03: là phải siết chặt lại kỷ cương của cán bộ công chức làm thực thi hành nhiệm vụ và tôi cho rằng là pháp luật mu
    140.4 SPEAKER_04: thế nào về cái mục tiêu này ạ.
    142.0 SPEAKER_03: thì tôi cho rằng ý là xuất phát từ thế thôi là người vi phạm thì thì à chắc chưa chắc là người đã gánh chịu hậ
    166.2 None: ngoài tác phẩm nghệ thuật cô còn tham gia các cuộc thi tập thể thao truyền hình trong công nghệ môn thể thao t
    166.5 SPEAKER_03: buộc tháo dỡ nhưng vì lợi ích quá lớn họ không tháo dỡ rồi cuối cùng thì tám năm sau năm hai không hai ba đã x
```

</details>

<details>
<summary><code>coso2</code> — PhoWhisper-large</summary>

```text
upload 201 0.1 s
job 077a597a-5363-4445-9f62-3f522cff1655
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    8.8s] ('transcribing', None, None)
[  124.9s] ('diarizing', None, None)
[  149.9s] ('ready', None, None)
elapsed 149.9 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 509136, "diarization_device": "cuda"}
pass 2 segments 39 speakers ['SPEAKER_04', 'SPEAKER_03', 'SPEAKER_07', 'SPEAKER_09', 'SPEAKER_01', 'SPEAKER_00', 'SPEAKER_02', 'SPEAKER_08']
  SPEAKER_01: 93s
  SPEAKER_03: 92s
  SPEAKER_02: 87s
  SPEAKER_04: 83s
  SPEAKER_08: 55s
  SPEAKER_00: 27s
  SPEAKER_07: 25s
  SPEAKER_09: 21s
  None: 2s
words 2316 segments with >1 word speaker 28
      0.7 SPEAKER_04: kết luận cuộc họp về các kịch bản điều hành giá xăng dầu và điện vào hôm nay phó thủ tướng chính phủ nguyễn vă
     26.8 SPEAKER_04: tiến độ giảm giá điện từ ngày mùng một tháng mười một năm hai nghìn không trăm hai mươi sáu.
     30.4 SPEAKER_04: báo cáo cấp có thẩm quyền đối với những nội dung vượt thẩm quyền bộ tài chính chủ trì phối hợp với bộ công thư
     55.5 SPEAKER_04: xét quyết định theo quy định của pháp luật hoàn thành trước ngày mùng một tháng mười một năm
     59.3 SPEAKER_04: hai nghìn không trăm hai mươi sáu giảm tải cho các bệnh viện tuyến trung ương đưa dịch vụ y tế chất lượng cao 
     83.6 None: đó là lý do tại sao chúng ta lại gặp nhau trong thời gian tới.
     86.0 SPEAKER_03: bệnh nhân này vừa được cấp cứu và can thiệp tim mạch chỉ sau vài giờ bệnh nhân đã hoàn toàn tỉnh táo gia đình 
    109.0 None: học trò tiếp theo trong tiếng nói việt nam tiếp theo đấu tranh tiếp theo đấu tranh việt nam trên toàn thế giới
    109.8 SPEAKER_07: với nhồi máu cơ tim cấp thì thời gian là vàng và mỗi tiếng chậm trễ thì cái vùng cơ tim thiếu máu nó sẽ càng t
    134.7 SPEAKER_03: một đội ngũ một chuẩn mực chuyên môn.
    137.4 SPEAKER_03: tại bệnh viện phụ sản trung ương cơ sở hai dù mới hoạt động mỗi ngày đã có gần bốn trăm lượt khám và mười lăm 
    162.9 SPEAKER_03: nhiều bà mẹ truyền thống đề nghị trước khi tiêu thụ thuốc từ trung quốc trở lại.
```

</details>

<details>
<summary><code>thegioi</code> — PhoWhisper-large</summary>

```text
upload 201 0.2 s
job dfb75c74-e86e-4a36-820f-381dbcdff958
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[   17.9s] ('transcribing', None, None)
[  272.8s] ('diarizing', None, None)
[  327.8s] ('ready', None, None)
elapsed 327.8 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 1245504, "diarization_device": "cuda"}
pass 2 segments 91 speakers ['SPEAKER_03', 'SPEAKER_09', 'SPEAKER_10', 'SPEAKER_01', 'SPEAKER_08', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_04', 'SPEAKER_11', 'SPEAKER_00', 'SPEAKER_07']
  SPEAKER_03: 293s
  SPEAKER_10: 212s
  SPEAKER_05: 172s
  SPEAKER_09: 151s
  SPEAKER_08: 122s
  SPEAKER_11: 71s
  SPEAKER_04: 31s
  SPEAKER_00: 25s
  SPEAKER_02: 21s
  SPEAKER_07: 21s
  None: 3s
  SPEAKER_01: 1s
words 5330 segments with >1 word speaker 49
      4.4 SPEAKER_03: chính phủ trung quốc cam kết tăng hỗ trợ các gia đình xây dựng xã hội thân thiện với sinh đẻ nhằm ứng phó thu 
     11.1 SPEAKER_03: những bức ảnh chụp trên trang trọng thế hệ của tô hoài.
     21.0 SPEAKER_09: xâm lược tại trung đông đang làm thay đổi bản đồ cung ứng khí tự nhiên hóa lỏng lng trên toàn cầu.
     28.5 SPEAKER_10: trung quốc tăng tốc khai thác thị trường kinh tế tầm thấp cơ hội tỷ đô đi cùng thách thức về an toàn và thương
     36.9 SPEAKER_03: cuộc bỏ phiếu trong vòng hai cuộc bầu cử tổng thống bờ ra xin đã kết thúc cách đây hơn một giờ đồng hồ thời gi
     63.0 SPEAKER_03: sáu mươi triệu cử tri brazil đủ điều kiện tham gia bỏ phiếu để lựa chọn
     66.3 SPEAKER_03: người lãnh đạo nền kinh tế lớn nhất mỹ latinh trong định cử tới tổng thống nua đại diện đảng lao động chủ trươ
     87.8 SPEAKER_01: nguyễn thiện kiêu và nguyễn thiện trang.
     91.5 SPEAKER_03: ngoại trưởng i ran áp bát a rắc chi ngày hôm qua tuyên bố tê hê ran sẽ không thay đổi chính sách ngay cả khi m
    113.7 SPEAKER_03: hạn chế gây phân hóa bệnh tâm thần và tâm hồn trong cơ thể trẻ nhỏ có thể dẫn đến đau đớn thận tâm thần và tâm
    114.1 SPEAKER_03: ông cũng cho rằng xung đột đã tạo ra những thay đổi căn bản trong khu vực do các bên phải chấp nhận thực tế mớ
    132.2 SPEAKER_03: các tác giả và truyền thông tin cao cấp thông báo vấn đề tiêu cực triều tiên sẽ trở thành báo cáo thông báo th
```

</details>

### large-v3-turbo sau khi sửa

<details>
<summary><code>phapluat</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.2 s
job 643b9b21-f39c-4efb-91c7-a9351e38acdd
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[   10.1s] ('transcribing', None, None)
[   38.2s] ('diarizing', None, None)
[   74.5s] ('ready', None, None)
elapsed 74.5 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 94 speakers ['SPEAKER_04', 'SPEAKER_01', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_00']
  SPEAKER_03: 281s
  SPEAKER_01: 59s
  SPEAKER_04: 34s
  SPEAKER_02: 24s
  SPEAKER_00: 18s
  SPEAKER_05: 17s
words 1847 segments with >1 word speaker 45
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi hướng tới nâng cao ý thức chấp hành pháp luật, thiết l
     23.6 SPEAKER_01: Và để cùng trao đổi về vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biể
     33.1 SPEAKER_01: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.5 SPEAKER_03: Chào các bạn.
     37.0 SPEAKER_01: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     50.1 SPEAKER_03: Thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật
     56.0 SPEAKER_03: Trong như bạn nói trong dự án vừa rồi là mọi người rất quan tâm
     59.7 SPEAKER_03: Là vi phạm phải bị xử lý nghiêm
     62.2 SPEAKER_03: Mọi người đều bình đẳng trước pháp luật
     63.9 SPEAKER_03: Và quyết định xử phạt phải được thực thi đến cùng
     67.2 SPEAKER_03: Thì tôi muốn nhấn mạnh những 4 vấn đề
```

</details>

<details>
<summary><code>coso2</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.1 s
job 055bf512-e29b-4366-846c-a9ce9a5f36fd
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    8.1s] ('transcribing', None, None)
[   32.2s] ('diarizing', None, None)
[   57.3s] ('ready', None, None)
elapsed 57.3 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 509136, "diarization_device": "cuda"}
pass 2 segments 72 speakers ['SPEAKER_04', 'SPEAKER_03', 'SPEAKER_07', 'SPEAKER_09', 'SPEAKER_06', 'SPEAKER_01', 'SPEAKER_00', 'SPEAKER_02', 'SPEAKER_08']
  SPEAKER_02: 90s
  SPEAKER_01: 80s
  SPEAKER_04: 79s
  SPEAKER_03: 62s
  SPEAKER_08: 52s
  SPEAKER_00: 24s
  SPEAKER_09: 21s
  SPEAKER_07: 18s
  SPEAKER_06: 12s
words 1726 segments with >1 word speaker 34
      0.7 SPEAKER_04: Kết luận cuộc họp về các kịch bản điều hành giá xăng dầu và điện vào hôm nay,
      4.8 SPEAKER_04: Phó Thủ tướng Chính phủ Nguyễn Văn Thắng yêu cầu EVN ra soát tính toán có phương án giảm giá bán lẻ điện bình 
     10.5 SPEAKER_04: áp dụng từ ngày 1 tháng 11 năm 2026 đến hết ngày 31 tháng 3 năm 2027 theo đúng quy định của pháp luật.
     18.6 SPEAKER_04: Báo cáo Bộ Công Thương kiểm tra ra soát và cho ý kiến.
     21.6 SPEAKER_04: Bộ Công Thương chủ trì có ý kiến đối với phương án giá bán lẻ điện bình quân của EVN
     25.9 SPEAKER_04: để đáp ứng tiến độ giảm giá điện từ ngày 1 tháng 11 năm 2026.
     30.5 SPEAKER_04: Báo cáo cấp có thẩm quyền đối với những nội dung vượt thẩm quyền
     33.8 SPEAKER_04: Bộ Tài chính chủ trì phối hợp với Bộ Công thương, Bộ Tư pháp và các cơ quan có liên quan
     38.1 SPEAKER_04: ra soát cơ sở pháp lý thẩm quyền, đánh giá đầy đủ tác động và tính khả thi
     42.8 SPEAKER_04: của phương án giảm thuế xuất, thuế tiêu tụ đặc biệt đối với xăng các loại về 0%
     48.1 SPEAKER_04: từ ngày 1-11-2026 đến hết ngày 31-3-2027
     53.6 SPEAKER_04: Báo cáo cấp có thẩm quyền xem xét quyết định theo quy định của pháp luật
```

</details>

<details>
<summary><code>thegioi</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.2 s
job 01d01cd7-3ec4-46c0-998b-be7ce627bddf
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[   17.1s] ('transcribing', None, None)
[   78.5s] ('diarizing', None, None)
[  139.9s] ('ready', None, None)
elapsed 139.9 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 1245504, "diarization_device": "cuda"}
pass 2 segments 209 speakers ['SPEAKER_03', 'SPEAKER_09', 'SPEAKER_10', 'SPEAKER_06', 'SPEAKER_08', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_04', 'SPEAKER_11', 'SPEAKER_00', 'SPEAKER_07']
  SPEAKER_03: 250s
  SPEAKER_10: 190s
  SPEAKER_05: 155s
  SPEAKER_09: 143s
  SPEAKER_08: 114s
  SPEAKER_11: 70s
  SPEAKER_04: 43s
  SPEAKER_06: 27s
  SPEAKER_02: 18s
  SPEAKER_07: 16s
  SPEAKER_00: 14s
words 4544 segments with >1 word speaker 55
      4.4 SPEAKER_03: Chính phủ Trung Quốc cam kết tăng hỗ trợ các gia đình xây dựng xã hội thân thiện với sinh đẻ
      8.6 SPEAKER_03: nhằm ứng phó tư giảm dân số và lực lượng lao động.
     21.0 SPEAKER_09: Xung đột tại Trung Đông đang làm thay đổi bản đồ cung ứng khí tự nhiên hóa lỏng LNG trên toàn cầu.
     28.5 SPEAKER_10: Trung Quốc tăng tốc khai thác thị trường kinh tế tầm thấp, cơ hội tỷ đô đi cùng thách thức về an toàn và thươn
     36.9 SPEAKER_06: Cuộc bỏ phiếu trong vòng 2 cuộc bầu cử Tổng thống Brazil đã kết thúc cách đây hơn 1 giờ đồng hồ.
     41.8 SPEAKER_06: Thời gian bỏ phiếu đã được kéo dài thêm 2 tiếng, theo đề nghị của cả 2 bên.
     46.0 SPEAKER_03: Tổng thống Lula de Silva lo ngại các sự cố ảnh hưởng đến mạng lưới xe buýt công cộng
     50.8 SPEAKER_03: tại 2 thành phố lớn là Sao Paulo và Salvador.
     53.5 SPEAKER_03: Trong khi đó, ứng cử viên đối lập Flavio Bolsonaro lại bày tỏ lo ngại,
     57.2 SPEAKER_03: thực tế xấu ảnh hưởng đến cử tri định bỏ phiếu tại Sao Paulo và bang Santa Catarina.
     62.3 SPEAKER_03: Gần 160 triệu cử tri Brazil đủ điều kiện tham gia bỏ phiếu để lựa chọn
     66.5 SPEAKER_03: lãnh đạo, nền kinh tế lớn nhất Mỹ Latin trong địa quy tế.
```

</details>

<details>
<summary><code>babble_10db</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.1 s
job 1672ba6e-dddd-4155-b53d-46276e62dae7
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    6.1s] ('transcribing', None, None)
[   36.2s] ('diarizing', None, None)
[   64.4s] ('ready', None, None)
elapsed 64.4 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 78 speakers ['SPEAKER_04', 'SPEAKER_01', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_00']
  SPEAKER_03: 281s
  SPEAKER_01: 53s
  SPEAKER_04: 34s
  SPEAKER_02: 24s
  SPEAKER_05: 17s
  SPEAKER_00: 16s
words 1786 segments with >1 word speaker 18
      0.0 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, thiết 
     14.9 SPEAKER_04: đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra những hiệu quả nghiêm trọng, lâu 
     23.5 SPEAKER_01: Và để cùng trao đổi vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu Q
     37.5 SPEAKER_01: từ gấp độ lầm pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật
     42.6 SPEAKER_01: cũng như là ý thức chúng ta giữ gìn trật tự thủy cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ?
     50.2 SPEAKER_03: Thì theo tôi, cái thông điệp quan trọng nhất mà của dự án luật,
     55.9 SPEAKER_03: chẳng như bạn nói trong dự án vừa rồi là mọi người
     58.5 SPEAKER_03: rất quan tâm là vi phạm bị xử lý nghiêm, mọi người đều bình đẳng trước pháp luật và quyết định xử phạt phải đư
     67.3 SPEAKER_03: Thì tôi muốn nhấn mạnh những 4 vấn đề. Thứ nhất là mức phạt phải đủ sức gian đe. Trong giá luật thì cũng đã có
     89.7 SPEAKER_03: Và thứ hai là phát hiện vi phạm kịp thời, thì luật cũng đã sử dụng và cho phép dụng các thiết bị về kỹ thuật đ
     98.1 SPEAKER_03: Thứ ba là bảo đảm quyết định xử phạm được thực hiện trên thực tế, dụ như là bổ sung thêm những hình thức như l
```

</details>

<details>
<summary><code>babble_5db</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.1 s
job d532e647-eef8-4243-af1a-88ab2df2f52d
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    5.0s] ('transcribing', None, None)
[   36.2s] ('diarizing', None, None)
[   64.4s] ('ready', None, None)
elapsed 64.4 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 89 speakers ['SPEAKER_06', 'SPEAKER_02', 'SPEAKER_07', 'SPEAKER_05', 'SPEAKER_03', 'SPEAKER_04', 'SPEAKER_00']
  SPEAKER_07: 217s
  SPEAKER_02: 53s
  SPEAKER_03: 23s
  SPEAKER_06: 22s
  SPEAKER_00: 19s
  SPEAKER_04: 13s
  SPEAKER_05: 11s
words 1519 segments with >1 word speaker 14
      0.0 SPEAKER_06: Thưa quý vị, tại kỳ họp thứ 2, quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_06: Trong đó thì có dự án luật xử lý vi phạm hành chính sở đổi, hướng tới nâng cao ý thức chấp hành pháp luật,
     13.5 SPEAKER_06: thiết lập trật tự, kỳ cương, đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra nhữn
     19.7 SPEAKER_06: lâu dài đối với tính mạng, sức khỏe và đôi trường sống.
     23.5 SPEAKER_02: Và để chúng trao đổi vấn đề này thì chương trình hôm nay đã mới tới trưởng quay ông Nguyễn Hải Long, đại biểu 
     37.5 SPEAKER_02: từ các đội lấm phát và thực tiễn, vì sao việc nâng cao ý thức tự giác, chất hành pháp luật
     42.6 SPEAKER_02: cũng như là ý thức chúng ta giữ gìn trật tự thử cương lại là yêu cầu quan trọng trong giai đoạn hiện nay ạ?
     50.0 SPEAKER_07: Thì theo tôi, cái thông điệp quan trọng nhất của dự án hóa luật
     54.0 SPEAKER_07: đó là, như bạn nói trong thề án vừa rồi, mọi người
     58.5 SPEAKER_07: rất quan tâm là vi phạm bị xử lý nghiêm, mọi người đều bình đẳng trước pháp luật và quyết định xử phạt được từ
     67.2 SPEAKER_07: Tôi muốn những 4 vấn đề. Thứ nhất là mức phạt phải đủ sức nhan đen.
     71.5 SPEAKER_07: Trong gián luật thì chúng ta có nâng mức phạt lên và các bạn thấy là có mức phạt phải nâng đến 4 lần.
```

</details>

<details>
<summary><code>pink_5db</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.1 s
job 8360eae5-41c3-4414-894c-79ec482ffaf7
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    7.0s] ('transcribing', None, None)
[   34.2s] ('diarizing', None, None)
[   62.4s] ('ready', None, None)
elapsed 62.4 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 80 speakers ['SPEAKER_04', 'SPEAKER_00', 'SPEAKER_05', 'SPEAKER_02', 'SPEAKER_03', 'SPEAKER_01']
  SPEAKER_05: 285s
  SPEAKER_00: 59s
  SPEAKER_04: 34s
  SPEAKER_02: 23s
  SPEAKER_01: 20s
  SPEAKER_03: 14s
words 1847 segments with >1 word speaker 30
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2 thì Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh v
      8.2 SPEAKER_04: Trong đó thì có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, kế
     23.6 SPEAKER_00: Và để cùng trao đổi về vấn đề này thì chương trình ngày hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đạ
     33.1 SPEAKER_00: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.5 SPEAKER_05: Chào mừng các bạn.
     37.0 SPEAKER_00: Thưa ông, từ gấp độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     50.1 SPEAKER_05: Ừ thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật đó mà cho như bạn nói trong
     57.0 SPEAKER_05: tháng vừa rồi là mọi người rất quan tâm đấy là vi phạm vệ định xử lý nghiêm mọi người được bình
     63.3 SPEAKER_05: đẳng trước pháp luật và quyết định sửa phạt phải được thứ khi đến cùng thì tôi muốn nhấn mạnh
     68.2 SPEAKER_05: những bốn vấn đề thì thứ nhất là mức phạt phải đủ sức gian đe thì trong dạng luật thì cũng đã có
     72.8 SPEAKER_05: nâng mức phạt lên và các bạn thấy là có cái mức phạt phải nâng lên bốn lần ví dụ như là mức phạt
     78.0 SPEAKER_05: trong mĩnh vực là
```

</details>

<details>
<summary><code>pink_0db</code> — large-v3-turbo, sau sửa</summary>

```text
upload 201 0.1 s
job 8b24f1fe-24ea-4481-8cb8-446759bcfd09
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    6.0s] ('transcribing', None, None)
[   34.2s] ('diarizing', None, None)
[   61.4s] ('ready', None, None)
elapsed 61.4 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 86 speakers ['SPEAKER_03', 'SPEAKER_01', 'SPEAKER_00', 'SPEAKER_04', 'SPEAKER_02']
  SPEAKER_03: 313s
  SPEAKER_01: 57s
  SPEAKER_04: 23s
  SPEAKER_00: 17s
  SPEAKER_02: 17s
words 1802 segments with >1 word speaker 25
      0.4 SPEAKER_03: Thưa quý vị, tại kỳ họp thứ 2, quốc hội đang thảo luận về dự án luật quan trọng liên quan đến các lĩnh vực của
      8.3 SPEAKER_03: Trong đó, có dự án luật xử lý vi phạm hành trí sửa đổi, đối với nâng cao ý thức chấp hành pháp luật, kết lập t
     16.5 SPEAKER_03: giúp những hành vi vi phạm có thể gây ra những hợp quả nghiêm trọng lâu dài đến với tính mạng, sức khỏe và nơi
     23.6 SPEAKER_01: Và để cùng trao đổi tấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu Q
     33.1 SPEAKER_01: Thì cảm ơn ông đã nhận lời mời tham gia xin chuyển hả?
     35.5 SPEAKER_00: Vâng, cô bạn.
     37.0 SPEAKER_01: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự xác, chấp hành pháp luật cũng như là
     50.1 SPEAKER_03: Ừ thì theo tôi cái công việc quan trọng nhất mà của dự án ngược cái mầm cho như bạn hỏi trong
     57.0 SPEAKER_03: gián vừa rồi và mọi người rất quan tâm đấy là vi phạm định xử lý nghiêm mọi người đều bình đẳng
     63.4 SPEAKER_03: các pháp luật và quyết định trở phạt phải được thứ khi đến cùng thì tôi muốn nhấn mạnh những
     68.4 SPEAKER_03: 4 vấn đề thì thứ nhất là mức phạt của điều chức gần đe thì trong dự án ngược thì cũng đã có nâng
     73.0 SPEAKER_03: mức phạt lên và các bạn thấy là có cái mức phạt để nâng đến 4 lần như là mức phạt trong những vực
```

</details>

### Bản nhiễu, large-v3-turbo trước khi sửa

<details>
<summary><code>pink_20db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job a1cdb85a-132b-4352-bbdf-0fd5423ba142
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    8.0s] ('transcribing', None, None)
[   36.2s] ('diarizing', None, None)
[   72.3s] ('ready', None, None)
elapsed 72.3 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 95 speakers ['SPEAKER_04', 'SPEAKER_00', 'SPEAKER_05', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_01']
  SPEAKER_05: 288s
  SPEAKER_00: 59s
  SPEAKER_04: 27s
  SPEAKER_03: 24s
  SPEAKER_02: 17s
  SPEAKER_01: 17s
words 1858 segments with >1 word speaker 43
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, thiết 
     23.6 SPEAKER_00: Và để cùng trao đổi vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu q
     33.1 SPEAKER_00: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.5 SPEAKER_05: Chào các bạn.
     37.0 SPEAKER_00: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     49.9 SPEAKER_05: Thì theo tôi cái thông điệp quan trọng nhất
     52.7 SPEAKER_05: Mà của dự án luật
     56.0 SPEAKER_05: Trong như bạn nói trong dự án vừa rồi
     58.0 SPEAKER_05: Mọi người rất quan tâm
     59.7 SPEAKER_05: Là vi phạm phải bị xử lý nghiêm
     62.2 SPEAKER_05: Mọi người đều bình đẳng trước pháp luật
```

</details>

<details>
<summary><code>pink_10db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job b98b2e9d-77a0-4c05-af5f-beef7ff0d561
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    6.0s] ('transcribing', None, None)
[   33.1s] ('diarizing', None, None)
[   58.3s] ('ready', None, None)
elapsed 58.3 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 98 speakers ['SPEAKER_04', 'SPEAKER_00', 'SPEAKER_05', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_01']
  SPEAKER_05: 278s
  SPEAKER_00: 59s
  SPEAKER_04: 33s
  SPEAKER_03: 23s
  SPEAKER_01: 17s
  SPEAKER_02: 17s
words 1860 segments with >1 word speaker 37
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, kết lậ
     23.6 SPEAKER_00: Và để cùng trao đổi về vấn đề này thì chương trình ngày hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đạ
     33.1 SPEAKER_00: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.5 SPEAKER_05: Chào các bạn.
     37.0 SPEAKER_00: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     49.8 SPEAKER_05: thì theo tôi
     50.8 SPEAKER_05: cái thông điệp quan trọng nhất
     52.7 SPEAKER_05: Mà của dự án luật
     56.0 SPEAKER_05: Trong như bạn nói trong dự án vừa rồi
     58.0 SPEAKER_05: Mọi người rất quan tâm
     59.7 SPEAKER_05: Là vi phạm vệ định xử lý nghiêm
```

</details>

<details>
<summary><code>pink_5db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job d3340366-bc21-42ce-8d8d-7e9ba2dca02b
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    6.0s] ('transcribing', None, None)
[   32.2s] ('diarizing', None, None)
[   56.2s] ('ready', None, None)
elapsed 56.2 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 80 speakers ['SPEAKER_04', 'SPEAKER_00', 'SPEAKER_05', 'SPEAKER_02', 'SPEAKER_03', 'SPEAKER_01']
  SPEAKER_05: 285s
  SPEAKER_00: 59s
  SPEAKER_04: 34s
  SPEAKER_02: 23s
  SPEAKER_01: 20s
  SPEAKER_03: 14s
words 1847 segments with >1 word speaker 30
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2 thì Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh v
      8.2 SPEAKER_04: Trong đó thì có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, kế
     23.6 SPEAKER_00: Và để cùng trao đổi về vấn đề này thì chương trình ngày hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đạ
     33.1 SPEAKER_00: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.5 SPEAKER_05: Chào mừng các bạn.
     37.0 SPEAKER_00: Thưa ông, từ gấp độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     50.1 SPEAKER_05: Ừ thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật đó mà cho như bạn nói trong
     57.0 SPEAKER_05: tháng vừa rồi là mọi người rất quan tâm đấy là vi phạm vệ định xử lý nghiêm mọi người được bình
     63.3 SPEAKER_05: đẳng trước pháp luật và quyết định sửa phạt phải được thứ khi đến cùng thì tôi muốn nhấn mạnh
     68.2 SPEAKER_05: những bốn vấn đề thì thứ nhất là mức phạt phải đủ sức gian đe thì trong dạng luật thì cũng đã có
     72.8 SPEAKER_05: nâng mức phạt lên và các bạn thấy là có cái mức phạt phải nâng lên bốn lần ví dụ như là mức phạt
     78.0 SPEAKER_05: trong mĩnh vực là
```

</details>

<details>
<summary><code>pink_0db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job 7013c266-8f39-4663-aebc-88ea6cff9cda
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    6.0s] ('transcribing', None, None)
[   31.2s] ('diarizing', None, None)
[   52.3s] ('ready', None, None)
elapsed 52.3 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 84 speakers ['SPEAKER_03', 'SPEAKER_01', 'SPEAKER_00', 'SPEAKER_04', 'SPEAKER_02']
  SPEAKER_03: 313s
  SPEAKER_01: 55s
  SPEAKER_04: 23s
  SPEAKER_00: 17s
  SPEAKER_02: 17s
words 1751 segments with >1 word speaker 25
      0.4 SPEAKER_03: Thưa quý vị, tại kỳ họp thứ 2, quốc hội đang thảo luận về dự án luật quan trọng liên quan đến các lĩnh vực của
      8.3 SPEAKER_03: Trong đó, có dự án luật xử lý vi phạm hành trí sửa đổi, đối với nâng cao ý thức chấp hành pháp luật, kết lập t
     16.5 SPEAKER_03: giúp những hành vi vi phạm có thể gây ra những hợp quả nghiêm trọng lâu dài đến với tính mạng, sức khỏe và nơi
     23.6 SPEAKER_01: Và để cùng trao đổi tấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu Q
     33.1 SPEAKER_01: Thì cảm ơn ông đã nhận lời mời tham gia xin chuyển hả?
     35.5 SPEAKER_00: Vâng, cô bạn.
     37.0 SPEAKER_01: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự xác, chấp hành pháp luật cũng như là
     50.1 SPEAKER_03: Ừ thì theo tôi cái công việc quan trọng nhất mà của dự án ngược cái mầm cho như bạn hỏi trong
     57.0 SPEAKER_03: gián vừa rồi và mọi người rất quan tâm đấy là vi phạm định xử lý nghiêm mọi người đều bình đẳng
     63.4 SPEAKER_03: các pháp luật và quyết định trở phạt phải được thứ khi đến cùng thì tôi muốn nhấn mạnh những
     68.4 SPEAKER_03: 4 vấn đề thì thứ nhất là mức phạt của điều chức gần đe thì trong dự án ngược thì cũng đã có nâng
     73.0 SPEAKER_03: mức phạt lên và các bạn thấy là có cái mức phạt để nâng đến 4 lần như là mức phạt trong những vực
```

</details>

<details>
<summary><code>babble_20db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job 0eeffb9c-8ff2-4185-b6af-a9f782a4e9d4
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    6.0s] ('transcribing', None, None)
[   32.1s] ('diarizing', None, None)
[   54.3s] ('ready', None, None)
elapsed 54.3 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 97 speakers ['SPEAKER_04', 'SPEAKER_01', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_05']
  SPEAKER_03: 273s
  SPEAKER_01: 60s
  SPEAKER_04: 34s
  SPEAKER_02: 23s
  SPEAKER_05: 15s
words 1758 segments with >1 word speaker 30
      0.4 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.3 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, thiết 
     23.6 SPEAKER_01: Và để cùng trao đổi về vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biể
     33.1 SPEAKER_01: Xin cảm ơn ông đã nhận lời mời tham gia chương trình ạ.
     35.6 SPEAKER_03: Chào các bạn.
     37.0 SPEAKER_01: Thưa ông, từ góc độ lập pháp và thực tiễn, vì sao việc nâng cao ý thức tự giác, chấp hành pháp luật cũng như l
     50.1 SPEAKER_03: Thì theo tôi cái thông điệp quan trọng nhất mà của dự án luật
     56.0 SPEAKER_03: Trong như bạn nói trong dự án vừa rồi là mọi người rất quan tâm
     59.7 SPEAKER_03: Là vi phạm phải bị xử lý nghiêm
     62.2 SPEAKER_03: Mọi người đều bình đẳng trước pháp luật
     63.9 SPEAKER_03: Và quyết định sửa phạt phải được thực thi đến cùng
     67.2 SPEAKER_03: Thì tôi muốn nhấn mạnh những 4 vấn đề
```

</details>

<details>
<summary><code>babble_10db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job a71b9423-95d1-4028-81cd-c8b175015f2a
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    8.1s] ('transcribing', None, None)
[   32.2s] ('diarizing', None, None)
[   55.4s] ('ready', None, None)
elapsed 55.4 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 75 speakers ['SPEAKER_04', 'SPEAKER_01', 'SPEAKER_03', 'SPEAKER_02', 'SPEAKER_05', 'SPEAKER_00']
  SPEAKER_03: 275s
  SPEAKER_01: 43s
  SPEAKER_04: 34s
  SPEAKER_02: 24s
  SPEAKER_05: 17s
  SPEAKER_00: 16s
words 1729 segments with >1 word speaker 19
      0.0 SPEAKER_04: Thưa quý vị, tại kỳ họp thứ 2, Quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_04: Trong đó có dự án luật xử lý vi phạm hành chính sửa đổi, hướng tới nâng cao ý thức chấp hành pháp luật, thiết 
     14.9 SPEAKER_04: đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra những hiệu quả nghiêm trọng, lâu 
     23.5 SPEAKER_01: Và để cùng trao đổi vấn đề này thì chương trình hôm nay đã mời tới trường quay ông Nguyễn Hải Long, đại biểu Q
     37.5 SPEAKER_01: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
     58.5 SPEAKER_03: rất quan tâm là vi phạm bị xử lý nghiêm, mọi người đều bình đẳng trước pháp luật và quyết định xử phạt phải đư
     67.3 SPEAKER_03: Thì tôi muốn nhấn mạnh những 4 vấn đề. Thứ nhất là mức phạt phải đủ sức gian đe. Trong giá luật thì cũng đã có
     89.7 SPEAKER_03: Và thứ hai là phát hiện vi phạm kịp thời, thì luật cũng đã sử dụng và cho phép dụng các thiết bị về kỹ thuật đ
     98.1 SPEAKER_03: Thứ ba là bảo đảm quyết định xử phạm được thực hiện trên thực tế, dụ như là bổ sung thêm những hình thức như l
    112.6 SPEAKER_03: Và thứ tư là phải xếp chặt lại kể cương của khán bộ công chức làm thi hành nhiệm vụ
    117.9 SPEAKER_03: Và tôi cho rằng là pháp
    119.2 SPEAKER_03: luật muốn thực hiện nghiêm minh thì phải nghiêm minh trong xử lý và công bằng cho áp dụng và thuận thiện trong
```

</details>

<details>
<summary><code>babble_5db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job bdab26f6-cf4a-4845-afe9-14e807ddee3e
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    5.0s] ('transcribing', None, None)
[   29.1s] ('diarizing', None, None)
[   53.2s] ('ready', None, None)
elapsed 53.2 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 84 speakers ['SPEAKER_06', 'SPEAKER_02', 'SPEAKER_07', 'SPEAKER_05', 'SPEAKER_03', 'SPEAKER_04', 'SPEAKER_00']
  SPEAKER_07: 204s
  SPEAKER_02: 43s
  SPEAKER_03: 23s
  SPEAKER_06: 22s
  SPEAKER_00: 19s
  SPEAKER_04: 17s
  SPEAKER_05: 11s
words 1360 segments with >1 word speaker 16
      0.0 SPEAKER_06: Thưa quý vị, tại kỳ họp thứ 2, quốc hội đang thảo luận nhiều dự án luật quan trọng liên quan đến các lĩnh vực 
      8.2 SPEAKER_06: Trong đó thì có dự án luật xử lý vi phạm hành chính sở đổi, hướng tới nâng cao ý thức chấp hành pháp luật,
     13.5 SPEAKER_06: thiết lập trật tự, kỳ cương, đồng thời bảo vệ an ninh con người trước những hành vi vi phạm có thể gây ra nhữn
     19.7 SPEAKER_06: lâu dài đối với tính mạng, sức khỏe và đôi trường sống.
     23.5 SPEAKER_02: Và để chúng trao đổi vấn đề này thì chương trình hôm nay đã mới tới trưởng quay ông Nguyễn Hải Long, đại biểu 
     37.5 SPEAKER_02: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
     58.5 SPEAKER_07: rất quan tâm là vi phạm bị xử lý nghiêm, mọi người đều bình đẳng trước pháp luật và quyết định xử phạt được từ
     67.2 SPEAKER_07: Tôi muốn những 4 vấn đề. Thứ nhất là mức phạt phải đủ sức nhan đen.
     71.5 SPEAKER_07: Trong gián luật thì chúng ta có nâng mức phạt lên và các bạn thấy là có mức phạt phải nâng đến 4 lần.
     77.0 SPEAKER_07: Ví dụ như là mức phạt trong lĩnh vực phòng cháy cháy nâng từ 50 triệu đến 200 triệu.
     84.2 SPEAKER_07: Mà với những mức phạm như vậy
     85.9 SPEAKER_07: Thì có một doanh nghiệp mình khẳng trình
```

</details>

<details>
<summary><code>babble_0db</code> — large-v3-turbo, trước sửa</summary>

```text
upload 201 0.1 s
job de388ea9-ca35-4725-b60d-5a352d03019f
[    0.0s] ('queued', None, None)
[    1.0s] ('preprocessing', None, None)
[    4.0s] ('transcribing', None, None)
[   16.1s] ('diarizing', None, None)
[   40.3s] ('ready', None, None)
elapsed 40.3 s
{"status": "ready", "error_code": null, "error_message": null, "warnings": [], "duration_ms": 473760, "diarization_device": "cuda"}
pass 2 segments 27 speakers ['SPEAKER_01', 'SPEAKER_08', 'SPEAKER_05', 'SPEAKER_07', 'SPEAKER_00', 'SPEAKER_04', 'SPEAKER_02']
  SPEAKER_05: 133s
  SPEAKER_07: 31s
  SPEAKER_00: 19s
  SPEAKER_04: 9s
  SPEAKER_02: 6s
  SPEAKER_08: 5s
  SPEAKER_01: 2s
words 498 segments with >1 word speaker 23
      1.7 SPEAKER_01: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
     37.2 SPEAKER_08: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
     62.5 SPEAKER_05: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
     95.9 SPEAKER_05: Các bạn hãy đăng ký kênh để ủng hộ kênh của chúng mình nhé.
    116.0 SPEAKER_05: Các bạn hãy đăng ký kênh để ủng hộ kênh của mình nhé.
    145.6 SPEAKER_05: thì chưa chắc là người đã đánh chịu ổ quả, trong khi nếu người không có lỗi thì đã đánh chịu ổ quả của khuẩn.
    154.8 SPEAKER_05: Thì ví dụ như khi trái trung cơ mới đi tại Hà Nội, các bạn thấy rằng là chủ công trình xây dựng trái quy định 
    164.8 SPEAKER_05: Có bất định sự phạm, bố tháo rỡ nhưng bị gợi ít quá lớn, không tháo rỡ.
    170.0 SPEAKER_05: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
    178.9 SPEAKER_05: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
    203.0 SPEAKER_05: Các bạn hãy đăng ký kênh để ủng hộ kênh của mình nhé.
    236.9 SPEAKER_07: Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
```

</details>


---

## 10. Vị trí file

| Nội dung | Vị trí |
|---|---|
| Script đo, `results*.json`, raw log | `Báo Cáo/do-cer-2026-10-29/` |
| Transcript thô đầy đủ của 21 lần chạy (`[mm:ss → mm:ss] NHÃN \| chữ`) | `data/raw-output-2026-10-29/` |
| Transcript JSON gốc từ API và file VRAM | thư mục scratchpad của phiên làm việc. `run_all.sh` tạo lại được |
| Bản nhiễu `.wav` | volume Docker `audio-data`, thư mục `/data/noisetest/` |
| Model PhoWhisper đã chuyển | volume Docker `hf-cache`, thư mục `/cache/huggingface/phowhisper-large-ct2` |

Transcript đầy đủ được đặt trong `data/`, nằm trong `.gitignore`, vì chúng chứa nội dung bản tin VTV24. Các đoạn trích trong báo cáo này chỉ dùng để minh họa lỗi.
