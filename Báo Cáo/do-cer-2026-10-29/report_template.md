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
{{RAW:rawlogs/evaluate.txt}}
```

Cách đọc: `raw` là chữ đúng như pipeline xuất ra; `filtered` là sau khi bỏ câu bịa bằng cùng một quy tắc cho cả hai model; `nofill` là WER khi bỏ từ đệm; `termCER` là CER trên thuật ngữ; `exact` là số lần thuật ngữ khớp nguyên cụm; `spk` là tỉ lệ từ gán đúng người nói; `flagged` là số câu bịa; `time` là thời gian cả job.

### 6.2. Các đoạn so sánh song song

Mỗi đoạn có bản gỡ băng, `large-v3-turbo` trước khi sửa, `large-v3-turbo` sau khi sửa, và `PhoWhisper-large` thô, theo cùng một khung thời gian. Chữ của model là `text_raw` lấy nguyên từ `GET /api/jobs/{id}/transcript`. Dòng có `⚠ CÂU BỊA` là câu bị quy tắc lọc ở mục 4 bắt.

{{EXCERPTS_MODELS}}

---

## 7. Raw output: trước và sau khi sửa

### 7.1. Output thô của `compare_fix.py`

```text
{{RAW:rawlogs/compare_fix.txt}}
```

Cột "không chữ" là số giây tiếng nói không ra chữ. Cột "số bị tách" là số câu có dạng `150 .000`, `1 -11`, `0 %`.

### 7.2. Test của bộ lọc

```text
{{RAW:rawlogs/pytest_filter.txt}}
```

### 7.3. Đoạn trước và sau trên bản nhiễu

{{EXCERPTS_NOISE}}

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
{{RAW:rawlogs/chunk_errors.txt}}
```

Dòng `mất` là đoạn từ 5 từ trở lên bị mất liền nhau: (từ giây, đến giây, số từ, nằm trong chunk hay ngoài VAD, đầu đoạn bị mất). Cả 4 đoạn đều nằm `trong chunk`, nghĩa là VAD đã đưa vào nhưng Whisper không ra chữ.

### 8.3. Chạy lại riêng 3 chunk bị mất chữ (`retry_chunks.py`)

`nsp` là `no_speech_prob`, `lp` là `avg_logprob` của câu.

```text
{{RAW:rawlogs/retry_chunks.txt}}
```

### 8.4. Bản nhiễu qua pipeline, trước khi sửa (`score_noise.py`)

```text
{{RAW:rawlogs/score_noise.txt}}
```

Cột `VAD bắt` là tỉ lệ tiếng nói của bản sạch mà VAD trên bản nhiễu còn bắt được. `VAD thừa` là số giây VAD coi là tiếng nói nhưng bản sạch không có. `người` là số người nói pyannote tìm ra.

### 8.5. Thử các cách sửa (`score_exp.py`)

```text
{{RAW:rawlogs/score_exp.txt}}
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

{{RUNLOGS}}

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
