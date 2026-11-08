"""Chunk đúng mốc VAD: app beam 5, app greedy, và faster-whisper không có hallucination_silence_threshold."""
import sys, tempfile
from pathlib import Path
from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _real_regions, _whisper_engine
from app.services.vad_chunker import build_chunks

audio, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
work = Path(tempfile.mkdtemp())
normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
chunks = [c for c in build_chunks(_real_regions(pcm)) if c.end > lo and c.start < hi]
engine = _whisper_engine()
for c in chunks:
    piece = slice_pcm(pcm, c.start, c.end)
    beam = engine.transcribe(piece, None)
    greedy = engine.transcribe(piece, None, greedy=True)
    segs, _ = engine.model.transcribe(piece, language="vi", beam_size=5, word_timestamps=True,
        condition_on_previous_text=False, vad_filter=False, temperature=0.0)
    raw = [s.text.strip()[:40] for s in segs]
    print(f"chunk {c.start:.3f}-{c.end:.3f}: beam {len(beam)} câu, greedy {len(greedy)} câu, thô-không-hst {len(raw)} {raw[:2]}")
    if not beam:
        print("   greedy:", [r['text'][:60] for r in greedy[:3]])
