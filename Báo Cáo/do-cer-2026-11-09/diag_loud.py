import sys, tempfile
from pathlib import Path
from app.services.audio_processor import load_pcm, normalize
from app.services import stt_engine as E
work = Path(tempfile.mkdtemp())
normalize(Path(sys.argv[1]), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
regions = E.speech_regions(pcm)
sq, n = 0.0, 0
for s, e in regions:
    a, b = E._rms(pcm, s, e); sq += a; n += b
floor = E.LOUD_GAP_RATIO * (sq / n) ** 0.5
print("floor", round(floor, 4), "rms tiếng", round((sq / n) ** 0.5, 4))
for i in range(len(regions) - 1):
    s, e = regions[i][1], regions[i + 1][0]
    if 420 < s < 460 and e - s >= 3:
        a, b = E._rms(pcm, s, e)
        print(round(s, 1), round(e, 1), "rms", round((a / b) ** 0.5, 4))
full = E.add_loud_gaps(pcm, regions)
print("thêm", len(full) - len(regions), [(round(s), round(e)) for s, e in full if (s, e) not in regions][:12])
