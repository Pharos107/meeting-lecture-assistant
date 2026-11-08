import sys, tempfile, resource
from pathlib import Path
import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps
from app.services.audio_processor import load_pcm, normalize
from app.services.stt_engine import VAD_PARAMETERS, _clamped_view, add_loud_gaps
work = Path(tempfile.mkdtemp())
normalize(Path(sys.argv[1]), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
a = rss(); view = _clamped_view(pcm); b = rss()
print("clamp MB", round(b - a))
stamps = get_speech_timestamps(np.asarray(pcm, dtype=np.float32), VadOptions(**VAD_PARAMETERS)); c = rss()
print("Silero gốc MB", round(c - b))
regions = [(s["start"] / 16000, s["end"] / 16000) for s in stamps]
add_loud_gaps(pcm, regions); d = rss()
print("loud gaps MB", round(d - c))
