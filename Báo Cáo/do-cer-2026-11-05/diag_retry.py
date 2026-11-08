"""Thử cách nhận dạng lại một khoảng mà Whisper ra câu bịa (lời mời đăng ký kênh) thay cho lời nói thật.

Chạy trong worker-gpu: python diag_retry.py <file audio> <giây bắt đầu> <giây kết thúc>
"""
import sys
import tempfile
from pathlib import Path

from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _whisper_engine
from app.services.stt_engine import HALLUCINATION_SILENCE_S, is_hallucination

audio, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
work = Path(tempfile.mkdtemp())
normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
model = _whisper_engine().model
BASE = dict(language="vi", task="transcribe", beam_size=5, word_timestamps=True, condition_on_previous_text=False,
            vad_filter=False, temperature=0.0, compression_ratio_threshold=2.4, log_prob_threshold=-1.0,
            no_speech_threshold=0.6, hallucination_silence_threshold=HALLUCINATION_SILENCE_S)


def run(name, start, end, **change):
    segs, _ = model.transcribe(slice_pcm(pcm, start, end), **{**BASE, **change})
    kept = [s.text.strip() for s in segs if not is_hallucination(s.text)]
    dropped = sum(1 for s in segs if is_hallucination(s.text))
    print(f"== {name} [{start:.1f}-{end:.1f}] giữ {len(kept)}, lọc {dropped}: {' / '.join(kept)[:200]}")


run("như app", lo, hi)
run("prompt trung tính", lo, hi, initial_prompt="Biên bản cuộc họp, lời nói tự nhiên.")
run("temperature 0.4 cố định", lo, hi, temperature=0.4)
run("beam 1", lo, hi, beam_size=1)
mid = (lo + hi) / 2
run("nửa đầu", lo, mid)
run("nửa sau", mid, hi)
run("kèm 3 giây trước", max(0.0, lo - 3), hi)
run("kèm 3 giây trước + prompt", max(0.0, lo - 3), hi, initial_prompt="Biên bản cuộc họp, lời nói tự nhiên.")
