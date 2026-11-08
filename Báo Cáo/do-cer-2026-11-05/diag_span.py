"""Thử nhiều cách giải mã trên một khoảng mà WhisperEngine trả rỗng, để biết chữ mất ở đâu.

Chạy trong worker-gpu: python diag_span.py <file audio> <giây bắt đầu> <giây kết thúc>
In đoạn thô của faster-whisper (trước bộ lọc của app) cùng no_speech_prob, avg_logprob, compression_ratio.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _whisper_engine
from app.services.stt_engine import HALLUCINATION_SILENCE_S, is_hallucination, too_fast

audio, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
work = Path(tempfile.mkdtemp())
normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
model = _whisper_engine().model
piece = slice_pcm(pcm, lo, hi)
print(f"span {lo}-{hi}s rms={float(np.sqrt((piece ** 2).mean())):.4f} peak={float(np.abs(piece).max()):.3f}")

BASE = dict(language="vi", task="transcribe", beam_size=5, word_timestamps=True, condition_on_previous_text=False,
            vad_filter=False, temperature=0.0, compression_ratio_threshold=2.4, log_prob_threshold=-1.0,
            no_speech_threshold=0.6, hallucination_silence_threshold=HALLUCINATION_SILENCE_S)
VARIANTS = {
    "app (như WhisperEngine)": {},
    "bỏ hallucination_silence_threshold": {"hallucination_silence_threshold": None},
    "bỏ no_speech_threshold": {"no_speech_threshold": None},
    "bỏ cả hai": {"hallucination_silence_threshold": None, "no_speech_threshold": None},
    "dải temperature": {"temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]},
    "không word_timestamps": {"word_timestamps": False, "hallucination_silence_threshold": None},
}
for name, change in VARIANTS.items():
    segs, info = model.transcribe(piece, **{**BASE, **change})
    segs = list(segs)
    print(f"\n== {name}: {len(segs)} đoạn")
    for s in segs:
        dropped = "LỌC" if is_hallucination(s.text) or too_fast(s.text, s.start, s.end) else "giữ"
        print(f"  [{lo + s.start:.1f}-{lo + s.end:.1f}] nsp={s.no_speech_prob:.2f} lp={s.avg_logprob:.2f} "
              f"cr={s.compression_ratio:.2f} {dropped}: {s.text.strip()[:120]}")

# Cùng khoảng nhưng kèm 3 giây ngữ cảnh phía trước, xem Whisper có ra chữ khi không bị cắt sát đầu câu.
pad = slice_pcm(pcm, max(0.0, lo - 3), hi)
segs, _ = model.transcribe(pad, **{**BASE, "hallucination_silence_threshold": None})
print("\n== kèm 3 giây trước:")
for s in segs:
    print(f"  [{lo - 3 + s.start:.1f}-{lo - 3 + s.end:.1f}] nsp={s.no_speech_prob:.2f} {s.text.strip()[:120]}")
