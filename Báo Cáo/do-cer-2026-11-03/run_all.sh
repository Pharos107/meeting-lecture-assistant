#!/usr/bin/env bash
# Chạy 7 bài thực tế với từng model qua API, lưu transcript, thời gian từng bước và đỉnh VRAM vào runs/<model>/.
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
CLIPS="quahat phoi21 phoi42 aldehyd acid hop2 hop1"

docker cp "$S/run_job.py" stt-backend-1:/tmp/run_job.py
for clip in $CLIPS; do
  docker cp "$D/${AUDIO[$clip]}" "stt-backend-1:/tmp/$clip.mp3"
done

for model in large-v3-turbo phowhisper-large; do
  if [ "$model" = phowhisper-large ]; then
    WHISPER_MODEL=/cache/huggingface/phowhisper-large-ct2
  else
    WHISPER_MODEL=large-v3-turbo
  fi
  printf 'services:\n  worker-gpu:\n    environment:\n      WHISPER_MODEL: %s\n' "$WHISPER_MODEL" > "$S/override.yml"
  docker compose -f docker-compose.yml -f "$S/override.yml" up -d --force-recreate --no-deps worker-gpu >/dev/null 2>&1
  until docker compose logs worker-gpu --since 2m 2>&1 | grep -q "ready\."; do sleep 2; done
  echo "== $model: worker WHISPER_MODEL=$(docker compose exec -T worker-gpu printenv WHISPER_MODEL)"
  mkdir -p "$S/runs/$model"
  for clip in $CLIPS; do
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -l 1 > "$S/runs/$model/$clip.vram" &
    smi=$!
    docker compose exec -T -e OUT=/tmp/out.json -e META=/tmp/meta.json backend \
      python /tmp/run_job.py "/tmp/$clip.mp3" > "$S/runs/$model/$clip.log" 2>&1
    kill $smi 2>/dev/null; taskkill /F /IM nvidia-smi.exe >/dev/null 2>&1
    docker cp stt-backend-1:/tmp/out.json "$S/runs/$model/$clip.json"
    docker cp stt-backend-1:/tmp/meta.json "$S/runs/$model/$clip.meta.json"
    echo "$model $clip $(grep -E '^elapsed|status' "$S/runs/$model/$clip.log" | tr '\n' ' ' | cut -c1-160) peakVRAM=$(sort -n "$S/runs/$model/$clip.vram" | tail -1)MiB"
  done
done

# Trả worker về cấu hình mặc định trong .env.
docker compose up -d --force-recreate --no-deps worker-gpu >/dev/null 2>&1
echo done
