"""Chạy lại vài chunk bằng turbo với các cấu hình giải mã khác nhau, in phần thời gian có chữ.

Dùng (trong worker-gpu): python retry_chunks.py file.mp3 start:end [start:end ...]
"""
import sys
import tempfile
import time
from pathlib import Path

from faster_whisper import WhisperModel

from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.stt_engine import speech_regions

BASE = dict(language="vi", task="transcribe", beam_size=5, word_timestamps=True, condition_on_previous_text=False,
            vad_filter=False, temperature=0.0, compression_ratio_threshold=2.4, log_prob_threshold=-1.0,
            no_speech_threshold=0.6)
CONFIGS = {
    "hiện tại": {},
    "tắt ngưỡng no_speech/logprob": {"no_speech_threshold": None, "log_prob_threshold": None},
    "temperature dự phòng": {"temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]},
    "hallucination_silence 2s": {"hallucination_silence_threshold": 2.0},
}

tmp = Path(tempfile.mkdtemp())
normalize(Path(sys.argv[1]), tmp / "a.opus", tmp / "a.f32", 10800)
pcm = load_pcm(tmp / "a.f32")
model = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8")
for spec in sys.argv[2:]:
    a, b = (float(x) for x in spec.split(":"))
    print(f"\n######## chunk {a}–{b}")
    audio = slice_pcm(pcm, a, b)
    for name, extra in CONFIGS.items():
        t0 = time.time()
        segs, _ = model.transcribe(audio, **{**BASE, **extra})
        segs = list(segs)
        covered = sum(s.end - s.start for s in segs)
        print(f"--- {name}: {len(segs)} câu, có chữ {covered:.1f}/{b - a:.1f}s, {time.time() - t0:.1f}s")
        for s in segs:
            print(f"    {a + s.start:6.1f}-{a + s.end:6.1f} nsp={s.no_speech_prob:.2f} lp={s.avg_logprob:.2f} | {s.text.strip()[:110]}")
    # Thử cắt nhỏ: mỗi vùng VAD trong chunk là một lần gọi.
    regions = [(max(x, a), min(y, b)) for x, y in speech_regions(audio) for x, y in [(x + a, y + a)]]
    print(f"--- từng vùng VAD riêng ({len(regions)} vùng):")
    for x, y in regions:
        segs, _ = model.transcribe(slice_pcm(pcm, x, y), **BASE)
        text = " ".join(s.text.strip() for s in segs)
        print(f"    {x:6.1f}-{y:6.1f} | {text[:120]}")
