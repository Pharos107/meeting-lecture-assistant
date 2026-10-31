"""Chạy trong container worker-gpu: dựng lại vùng VAD và chunk đúng như pipeline cho từng file.

Dùng: python diag_chunks.py out.json file1.mp3 [file2.mp3 ...]
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from app.services.audio_processor import SAMPLE_RATE, load_pcm, normalize
from app.services.stt_engine import speech_regions
from app.services.vad_chunker import build_chunks

out = {}
for src in sys.argv[2:]:
    tmp = Path(tempfile.mkdtemp())
    audio = normalize(Path(src), tmp / "a.opus", tmp / "a.f32", 10800)
    pcm = load_pcm(tmp / "a.f32")
    regions = speech_regions(pcm)
    chunks = build_chunks(regions)

    def rms_db(a, b):
        seg = pcm[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)]
        return float(20 * np.log10(np.sqrt(np.mean(seg.astype(np.float64) ** 2)) + 1e-9)) if len(seg) else None

    # Ồn nền: trung bình năng lượng ngoài vùng có tiếng.
    mask = np.ones(len(pcm), dtype=bool)
    for a, b in regions:
        mask[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)] = False
    gaps = pcm[mask]
    noise_db = float(20 * np.log10(np.sqrt(np.mean(gaps.astype(np.float64) ** 2)) + 1e-9)) if len(gaps) else None
    out[Path(src).stem] = {
        "duration": len(pcm) / SAMPLE_RATE,
        "regions": [[round(a, 2), round(b, 2), rms_db(a, b)] for a, b in regions],
        "chunks": [[round(c.start, 2), round(c.end, 2), len(c.slices), c.last_forced] for c in chunks],
        "noise_db": noise_db,
    }
    print(Path(src).stem, "regions", len(regions), "chunks", len(chunks), "speech", round(sum(b - a for a, b in regions), 1),
          "of", round(len(pcm) / SAMPLE_RATE, 1), "s", flush=True)
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
