"""VAD bỏ sót lời nói nhỏ? In rms từng 5 giây, vùng VAD ở vài ngưỡng, và chữ Whisper khi nhận dạng thẳng khoảng."""
import sys, tempfile
from pathlib import Path
import numpy as np
from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _whisper_engine
from app.services.stt_engine import VAD_PARAMETERS, speech_regions

audio, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
work = Path(tempfile.mkdtemp())
normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
whole = np.asarray(pcm)
print(f"rms cả bài {float(np.sqrt((whole ** 2).mean())):.4f}")
for t in np.arange(lo, hi, 5):
    piece = slice_pcm(pcm, t, t + 5)
    print(f"  {t:6.1f}s rms {float(np.sqrt((piece ** 2).mean())):.4f} đỉnh {float(np.abs(piece).max()):.3f}")
for threshold in (VAD_PARAMETERS.get("threshold", 0.5), 0.35, 0.2):
    regions = speech_regions(pcm, {**VAD_PARAMETERS, "threshold": threshold})
    inside = [(round(s, 1), round(e, 1)) for s, e in regions if e > lo and s < hi]
    print(f"VAD threshold {threshold}: {sum(min(e, hi) - max(s, lo) for s, e in inside):.1f}s có tiếng {inside}")
engine = _whisper_engine()
for greedy in (False, True):
    out = engine.transcribe(slice_pcm(pcm, lo, hi), None, greedy=greedy)
    print(f"Whisper thẳng {lo}-{hi} greedy={greedy}: {[r['text'][:60] for r in out]}")
