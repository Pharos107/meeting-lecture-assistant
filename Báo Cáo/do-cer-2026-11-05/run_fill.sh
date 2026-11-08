#!/usr/bin/env bash
# Đo lại #19: chạy large-v3-turbo với code hiện tại (có fill_empty_spans) trên 7 bài thực tế.
# Mount ./backend vào backend và worker-gpu để chắc chạy đúng code trong repo, không phụ thuộc image cũ.
set -u
S="${S:?đặt S là thư mục làm việc chứa run_job.py}"
P="E:/lehai/Documents/Project/STT"
D="$P/data/Data thực tế"
cd "$P"
export MSYS_NO_PATHCONV=1

declare -A AUDIO=(
  [phoi21]="2.1 - PHÔI THAI HỌC PHÂN TỬ VÀ DỊ TẬT BẨM SINH P1 - SDH Y HÀ NỘI - KIẾN THỨC Y HỌC - DI TRUYỀN - SẢN PHỤ KHOA.mp3"
  [phoi42]="4.2 PHÔI THAI HỌC HỆ TIÊU HOÁ - SDH 2025 YHN - KIẾN THỨC Y HỌC - DI TRUYỀN - SẢN PHỤ KHOA.mp3"
  [aldehyd]="Aldehyd - Ceton phần 1 - Bài giảng hóa hữu cơ 1 - Tài Liệu Dược Khoa UMP- độ khó nghe rất khó.mp3"
  [acid]="Bài tập acid đơn chức và dẫn xuất phần 2 - Bài giảng hóa hữu cơ 1 - Tài Liệu Dược Khoa UMP - độ khó nghe rất khó.mp3"
  [quahat]="Quả và Hạt part 2 - PGS.TS Trương Thị Đẹp - Bài giảng Thực Vật Dược - Tài Liệu Dược Khoa UMP.mp3"
  [hop1]="VideoMetting_1_28p.mp3"
  [hop2]="VideoMetting_2_14p.mp3"
)
CLIPS="${CLIPS:-quahat phoi21 phoi42 aldehyd acid hop2 hop1}"
MODEL=large-v3-turbo

printf 'services:\n  backend:\n    volumes:\n      - %s/backend:/app\n  worker-gpu:\n    environment:\n      WHISPER_MODEL: %s\n    volumes:\n      - %s/backend:/app\n' "$P" "$MODEL" "$P" > "$S/override_fill.yml"
docker compose -f docker-compose.yml -f "$S/override_fill.yml" up -d postgres redis backend worker-gpu >/dev/null 2>&1
until docker compose logs worker-gpu --since 3m 2>&1 | grep -q "ready\."; do sleep 2; done
echo "worker fill_empty_spans: $(docker compose exec -T worker-gpu grep -c 'fill_empty_spans' /app/app/services/pipeline.py)"
until docker compose exec -T backend python -c "import httpx;httpx.get('http://127.0.0.1:8000/api/health').raise_for_status()" >/dev/null 2>&1; do sleep 2; done

docker cp "$S/run_job.py" stt-backend-1:/tmp/run_job.py
mkdir -p "$S/runs/$MODEL"
for clip in $CLIPS; do
  docker cp "$D/${AUDIO[$clip]}" "stt-backend-1:/tmp/$clip.mp3"
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -l 1 > "$S/runs/$MODEL/$clip.vram" &
  smi=$!
  docker compose exec -T -e OUT=/tmp/out.json -e META=/tmp/meta.json backend \
    python /tmp/run_job.py "/tmp/$clip.mp3" > "$S/runs/$MODEL/$clip.log" 2>&1
  kill $smi 2>/dev/null; taskkill /F /IM nvidia-smi.exe >/dev/null 2>&1
  docker cp stt-backend-1:/tmp/out.json "$S/runs/$MODEL/$clip.json"
  docker cp stt-backend-1:/tmp/meta.json "$S/runs/$MODEL/$clip.meta.json"
  echo "$MODEL $clip $(grep -E '^elapsed' "$S/runs/$MODEL/$clip.log") peakVRAM=$(sort -n "$S/runs/$MODEL/$clip.vram" | tail -1)MiB"
done
echo done
