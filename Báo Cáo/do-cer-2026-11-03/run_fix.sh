#!/usr/bin/env bash
# Chạy lại turbo với code đã sửa bộ lọc (mount ./backend vào worker-gpu) trên 3 bài có câu bịa lọt.
set -u
S="${S:?đặt S là thư mục làm việc chứa run_job.py}"
P="E:/lehai/Documents/Project/STT"
cd "$P"
export MSYS_NO_PATHCONV=1
printf 'services:\n  worker-gpu:\n    environment:\n      WHISPER_MODEL: large-v3-turbo\n    volumes:\n      - %s/backend:/app\n' "$P" > "$S/override_fix.yml"
docker compose -f docker-compose.yml -f "$S/override_fix.yml" up -d --force-recreate --no-deps worker-gpu >/dev/null 2>&1
until docker compose logs worker-gpu --since 2m 2>&1 | grep -q "ready\."; do sleep 2; done
echo "worker filter: $(docker compose exec -T worker-gpu grep -c 'không bỏ lỡ những video' /app/app/services/stt_engine.py)"
mkdir -p "$S/runs_fix/large-v3-turbo"
for clip in acid aldehyd hop1; do
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -l 1 > "$S/runs_fix/large-v3-turbo/$clip.vram" &
  smi=$!
  docker compose exec -T -e OUT=/tmp/out.json -e META=/tmp/meta.json backend \
    python /tmp/run_job.py "/tmp/$clip.mp3" > "$S/runs_fix/large-v3-turbo/$clip.log" 2>&1
  kill $smi 2>/dev/null; taskkill /F /IM nvidia-smi.exe >/dev/null 2>&1
  docker cp stt-backend-1:/tmp/out.json "$S/runs_fix/large-v3-turbo/$clip.json"
  docker cp stt-backend-1:/tmp/meta.json "$S/runs_fix/large-v3-turbo/$clip.meta.json"
  echo "$clip $(grep -E '^elapsed' "$S/runs_fix/large-v3-turbo/$clip.log")"
done
docker compose up -d --force-recreate --no-deps worker-gpu >/dev/null 2>&1
echo done
