import sys, tempfile
from pathlib import Path
import numpy as np
from app.services.audio_processor import load_pcm, normalize
work = Path(tempfile.mkdtemp())
normalize(Path(sys.argv[1]), work / "a.opus", work / "a.pcm", 10800)
pcm = np.asarray(load_pcm(work / "a.pcm"))
big = np.abs(pcm) > 1.5
print("mẫu", len(pcm), "max", float(np.nanmax(np.abs(pcm))), "nan", int(np.isnan(pcm).sum()), "inf", int(np.isinf(pcm).sum()), ">1.5:", int(big.sum()))
if big.any():
    idx = np.flatnonzero(big)
    print("vị trí (giây):", sorted(set(int(i / 16000) for i in idx[:2000]))[:30])
