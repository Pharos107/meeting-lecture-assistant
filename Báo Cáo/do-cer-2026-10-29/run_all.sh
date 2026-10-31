#!/usr/bin/env bash
# Chạy 3 bài với từng model, lưu transcript, thời gian từng bước và đỉnh VRAM vào runs/<model>/.
set -u
S="C:/Users/lehai/AppData/Local/Temp/claude/E--lehai-Documents-Project-STT/1675a218-225b-42ea-92f4-beb0c3cb63f5/scratchpad"
P="E:/lehai/Documents/Project/STT"
D="$P/data/phóng sự 7p"
cd "$P"

declare -A AUDIO=(
  [phapluat]="Nâng cao ý thức, trách nhiệm của nhân dân trước pháp luật  VTV24 - VTV24.mp3"
  [coso2]="Cơ sở 2 giảm tải bệnh viện tuyến Trung ương  Cụm tin  VTV24 - VTV24.mp3"
  [thegioi]="Thế giới toàn cảnh ngày 26_10 Iran tuyên bố không nhượng bộ nếu Mỹ và Israel tấn công trở lại - VTV24.mp3"
)

docker cp "$S/run_job.py" stt-backend-1:/tmp/run_job.py
for clip in phapluat coso2 thegioi; do
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
  for clip in phapluat coso2 thegioi; do
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -l 1 > "$S/runs/$model/$clip.vram" &
    smi=$!
    MSYS_NO_PATHCONV=1 docker compose exec -T -e OUT=/tmp/out.json -e META=/tmp/meta.json backend \
      python /tmp/run_job.py "/tmp/$clip.mp3" > "$S/runs/$model/$clip.log" 2>&1
    kill $smi 2>/dev/null; taskkill //F //IM nvidia-smi.exe >/dev/null 2>&1
    MSYS_NO_PATHCONV=1 docker cp stt-backend-1:/tmp/out.json "$S/runs/$model/$clip.json"
    MSYS_NO_PATHCONV=1 docker cp stt-backend-1:/tmp/meta.json "$S/runs/$model/$clip.meta.json"
    echo "$model $clip $(grep -E '^elapsed|status' "$S/runs/$model/$clip.log" | tr '\n' ' ' | cut -c1-160) peakVRAM=$(sort -n "$S/runs/$model/$clip.vram" | tail -1)MiB"
  done
done

# Trả worker về cấu hình mặc định trong .env.
docker compose up -d --force-recreate --no-deps worker-gpu >/dev/null 2>&1
echo done
