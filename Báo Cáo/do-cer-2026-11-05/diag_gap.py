"""Vì sao một khoảng trống không được fill_empty_spans vá: in vùng VAD, chunk, chữ Whisper, và khoảng trống tìm được.

Chạy trong worker-gpu: python diag_gap.py <file audio> <giây bắt đầu> <giây kết thúc>
"""
import sys
import tempfile
from pathlib import Path

from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _real_regions, _whisper_engine
from app.services.vad_chunker import build_chunks, empty_spans

audio, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
# Đi đúng đường của pipeline: file gốc -> Opus canonical -> PCM f32le 16 kHz.
work = Path(tempfile.mkdtemp())
normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
regions = _real_regions(pcm)
print("VAD regions trong khoảng:", [(round(s, 1), round(e, 1)) for s, e in regions if e > lo and s < hi])
chunks = [c for c in build_chunks(regions) if c.end > lo and c.start < hi]
engine = _whisper_engine()
for chunk in chunks:
    print(f"\n== chunk {chunk.start:.1f}-{chunk.end:.1f}, slices {[(round(s.start, 1), round(s.end, 1)) for s in chunk.slices]}")
    produced = engine.transcribe(slice_pcm(pcm, chunk.start, chunk.end), None)
    for raw in produced:
        words = raw.get("words") or []
        span = (chunk.start + words[0]["start"], chunk.start + words[-1]["end"]) if words else None
        print(f"  seg {span} {raw.get('text', '')[:100]}")
    spans = empty_spans(chunk, produced)
    print("  empty_spans:", [(round(s, 1), round(e, 1)) for s, e in spans])
    for s, e in spans:
        from app.services.vad_chunker import SpeechChunk, SpeechSlice
        again = engine.transcribe(slice_pcm(pcm, s, e), None)
        print(f"   refill {s:.1f}-{e:.1f}: {[r.get('text', '')[:80] for r in again]}")
