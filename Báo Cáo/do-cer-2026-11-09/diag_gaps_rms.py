"""Khoảng giữa hai vùng VAD dài từ 3 giây: rms của khoảng, theo từng bài. Để chọn ngưỡng 'khoảng trống mà to'."""
import sys, tempfile
from pathlib import Path
import numpy as np
from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _real_regions

for audio in sys.argv[1:]:
    work = Path(tempfile.mkdtemp())
    normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
    pcm = load_pcm(work / "a.pcm")
    regions = _real_regions(pcm)
    total = len(pcm) / 16000
    edges = [(0.0, regions[0][0])] + [(regions[i][1], regions[i + 1][0]) for i in range(len(regions) - 1)] + [(regions[-1][1], total)]
    gaps = [(s, e) for s, e in edges if e - s >= 3.0]
    speech = np.concatenate([slice_pcm(pcm, s, e) for s, e in regions])
    rms_speech = float(np.sqrt((speech ** 2).mean()))
    rows = []
    for s, e in gaps:
        piece = slice_pcm(pcm, s, e)
        rows.append((float(np.sqrt((piece ** 2).mean())), s, e))
    rows.sort(reverse=True)
    loud = [r for r in rows if r[0] >= 0.3 * rms_speech]
    print(f"{Path(audio).stem}: rms tiếng {rms_speech:.4f}, {len(gaps)} khoảng >=3s tổng {sum(e - s for _, s, e in rows):.0f}s, "
          f"khoảng to >=30% rms tiếng: {len(loud)} tổng {sum(e - s for _, s, e in loud):.0f}s")
    print("   to nhất:", [(round(r, 3), round(s), round(e - s, 1)) for r, s, e in rows[:6]])
    print("   nhỏ nhất:", [(round(r, 3), round(s), round(e - s, 1)) for r, s, e in rows[-3:]])
